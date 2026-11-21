"""Source « alertes mail » : relaie vers Telegram les alertes que Leboncoin,
SeLoger, PAP, etc. t'envoient par e-mail.

Pourquoi pas un scraping direct de ces sites ? Leboncoin et SeLoger sont protégés
par un anti-bot (DataDome) et leurs CGU l'interdisent. Leurs alertes mail, elles,
sont faites pour ça : tu dessines la zone autour des gares RER A sur leur site,
et ce module centralise tout au même endroit, sans doublons.
"""
import base64
from urllib.parse import urljoin, urlparse
import email
import hashlib
import html
import json
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

MOTS_PIED_DE_PAGE = ("désinscri", "desinscri", "désabonn", "desabonn", "unsubscribe", "préférences", "preferences",
                     "confidentialit", "mentions légales", "application", "app store", "google play", "facebook",
                     "instagram", "gérer mes alertes", "gérer mon alerte", "gérer votre alerte", "modifier",
                     "voir toutes", "voir plus d", "pass prioritaire", "je m'inscris", "webinaire")
INDICES_ANNONCE = re.compile(r"(€|m²|m2|pi[eè]ce|studio|\bT[1-5]\b|\bF[1-5]\b|appartement)", re.I)
TEXTE_BOUTON = re.compile(r"voir (?:l'annonce|l’annonce|le logement|le bien|ce bien|l'offre|le studio|l'appartement)|découvrir (?:le bien|l'annonce)", re.I)
# Liens qui mènent à une annonce (après décodage des liens de suivi)
URL_ANNONCE = re.compile(
    r"pap\.fr/annonces?/|studapart\.com/\w+/(?:property|residence)/|leboncoin\.fr/(?:ad|vi|locations)/|"
    r"seloger\.com/annonces/|bienici\.com/annonce/|logic-immo\.com/(?:detail|annonce)|locservice\.fr/.*(?:annonce|location-)|"
    r"lodgis\.com/.*(?:appartement|apartment|studio)|parisattitude\.com/.*(?:location|rent)|immojeune\.com/.*(?:logement|location)|"
    r"lokaviz\.fr/.*(?:logement|annonce)|entreparticuliers\.com/annonces?|paruvendu\.fr/immobilier/.*location|"
    r"locservice\.fr/.+/\d+\.html|"
    r"lesiteimmo\.com/louer/appartement-[^/]+/[^/]+/\d+|immojeune\.com/location-etudiant/[^/]+/[^/]+_\d+\.html", re.I)
RE_PRIX = re.compile(r"(\d{1,2},\d{3}(?!\d)|\d[\d\s  .]{0,7}(?:,\d{1,2})?)\s?(?:€|&euro;|eur\b)", re.I)  # « 1,020€ » = 1 020 €
RE_SURFACE = re.compile(r"(\d{1,3}(?:[.,]\d)?)\s?m(?:²|2)\b", re.I)
RE_PIECES = re.compile(r"(\d)\s?pi[eè]ces?|\b[TF]([1-5])\b|(studio)", re.I)
RE_CP = re.compile(r"\b(7[5789]|9[1-5])\d{3}\b")


def _nombre(s):
    s = s.strip()
    if re.fullmatch(r"\d{1,2},\d{3}", s):  # virgule des milliers (format anglais)
        s = s.replace(",", "")
    return float(re.sub(r"[\s  .]", "", s).replace(",", "."))


def url_reelle(href):
    """Décode les liens de suivi (Mandrill, redirections ?url=…) pour retrouver l'adresse de l'annonce."""
    u = html.unescape(href or "").strip()
    if "mandrillapp.com" in u and (m := re.search(r"[?&]p=([A-Za-z0-9_\-]+)", u)):
        b = m.group(1) + "=" * (-len(m.group(1)) % 4)
        try:
            return json.loads(json.loads(base64.urlsafe_b64decode(b))["p"])["url"].replace("\\/", "/")
        except (ValueError, KeyError, TypeError):
            return u
    q = parse_qs(urlparse(u).query)
    for k in ("url", "u", "redirect", "target", "dest", "destination"):
        if k in q and q[k][0].startswith("http"):
            return q[k][0]
    return u


PARAMS_PRIVES = re.compile(r"^(utm_|email|e$|md5|token|hash|uid|user|mc_|_hs|trk)", re.I)


def nettoyer_url(u):
    """Retire les paramètres de suivi et ceux qui contiennent ton adresse mail (le site peut être public)."""
    p = urlparse(u)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not PARAMS_PRIVES.match(k)]
    return urlunparse(p._replace(query=urlencode(q)))


def cle_url(u):
    """Adresse canonique (sans paramètres de suivi) : la même annonce reçue deux fois = une seule notif."""
    p = urlparse(u)
    chemin = p.path.rstrip("/")
    if not chemin and p.query:  # lien de suivi « https://click.site/?qs=… » : l'identité est dans le paramètre
        return f"{p.netloc.lower().removeprefix('www.')}?{p.query}"
    return f"{p.netloc.lower().removeprefix('www.')}{chemin}"


class _Flux(HTMLParser):
    """Transforme le HTML en suite d'évènements : ('texte', str) et ('lien', href, texte, image)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ev, self._a, self._img, self._txt = [], None, None, []

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if tag == "a":
            self._a, self._img, self._txt = at.get("href"), None, []
        elif tag == "img" and self._a is not None and not self._img:
            src = at.get("src") or ""
            if src.startswith("http") and not re.search(r"logo|icon|picto|pixel|track|open\.", src, re.I):
                self._img = src
        elif tag in ("br", "p", "div", "tr", "td", "li"):
            self.handle_data("\n")

    def handle_data(self, data):
        if self._a is not None:
            self._txt.append(data)
        elif data.strip():
            self.ev.append(("texte", data))

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            self.ev.append(("lien", self._a, " ".join(" ".join(self._txt).split()), self._img))
            self._a = None


def _lire_carte(a, texte):
    texte = " ".join(texte.split())
    if m := RE_PRIX.search(texte):
        a["prix"] = _nombre(m.group(1))
    if m := RE_SURFACE.search(texte):
        a["surface"] = _nombre(m.group(1))
    if m := RE_PIECES.search(texte):
        a["pieces"] = 1 if m.group(3) else int(m.group(1) or m.group(2))
    if m := RE_CP.search(texte):
        a["code_postal"] = m.group(0)
    return a


def ressemble_annonce(url, domaine):
    """Page web : lien vers une fiche d'annonce du même site (identifiant de 5 chiffres ou plus, ou UUID)."""
    p = urlparse(url)
    if domaine not in p.netloc:
        return False
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-", p.path):
        return True
    seg = p.path.rstrip("/").rsplit("/", 1)[-1]
    nums = re.findall(r"\d{5,}", f"{seg}?{p.query}")
    return any(not re.fullmatch(r"(?:75|77|78|9[1-5])\d{3}", n) for n in nums)  # 75015 = code postal, pas un id


ENTETE_ALERTE = re.compile(r"^\s*(?:\d+ )?nouvelles? annonces?\b|pourraient vous int[ée]resser|^\s*localisation diff[ée]rente\s*$"
                           r"|correspondant à (?:certains de )?vos crit|augmentez vos chances|cr[ée]ant votre (?:dossier|profil)"
                           r"|consultez vos premiers r[ée]sultats", re.I)
SUIVI_OPAQUE = re.compile(r"^https?://click\.[^/]*seloger\.com/|^https?://[^/]*\.(?:sendgrid|mailjet|sparkpost)", re.I)


def extraire_annonces(html_body, domaine, max_liens=10, base=None, motif=None):
    """Découpe une alerte mail en annonces.

    Les sites mettent l'annonce dans une « carte » : un lien sur la photo, du texte
    (type, ville, prix, surface) puis un bouton « Voir l'annonce » vers la même adresse.
    On regroupe donc tout ce qui se trouve entre la première et la dernière occurrence
    d'un même lien d'annonce. Si le lien n'apparaît qu'une fois, on prend son texte et
    les quelques lignes qui suivent.
    """
    f = _Flux()
    f.feed(html_body or "")
    ev = f.ev
    cles = []  # (index, clé, url réelle, image) des liens d'annonce
    if base:  # page web : liens relatifs (« /louer/… ») -> adresse complète
        ev = [(e[0], urljoin(base, e[1] or ""), *e[2:]) if e[0] == "lien" else e for e in ev]
    for i, e in enumerate(ev):
        if e[0] != "lien" or not (e[1] or "").startswith("http"):
            continue
        reel = url_reelle(e[1])
        if any(m in e[2].lower() for m in MOTS_PIED_DE_PAGE):
            continue
        if SUIVI_OPAQUE.search(reel) and not TEXTE_BOUTON.search(e[2]):
            continue  # liens de suivi tous différents : seul le bouton « Voir l'annonce » délimite une carte
        if (URL_ANNONCE.search(reel) or TEXTE_BOUTON.search(e[2]) or (len(e[2]) >= 6 and INDICES_ANNONCE.search(e[2]))
                or (base and (motif.search(reel) if motif else ressemble_annonce(reel, domaine)))):
            cles.append((i, cle_url(reel), reel, e[3]))
    ordre, cartes, occ = [], {}, {}
    for i, k, reel, img in cles:
        c = cartes.setdefault(k, {"debut": i, "fin": i, "url": reel, "photo": None})
        if k not in ordre:
            ordre.append(k)
        c["fin"] = i
        c["photo"] = c["photo"] or img
        occ.setdefault(k, []).append(i)
    # une carte ne doit pas englober d'autres annonces (lien répété en haut de page, carrousel…) :
    # on remonte depuis la dernière occurrence tant qu'aucun autre lien d'annonce ne s'intercale
    positions = [(i, k) for i, k, _, _ in cles]
    for k, idx in occ.items():
        debut = idx[-1]
        for j in range(len(idx) - 2, -1, -1):
            if any(idx[j] < i < debut and kk != k for i, kk in positions):
                break
            debut = idx[j]
        cartes[k]["debut"] = debut
    debuts = sorted(c["debut"] for c in cartes.values())
    fins = sorted(c["fin"] for c in cartes.values())
    annonces = []
    for k in ordre:
        c = cartes[k]
        fin = c["fin"]
        if fin == c["debut"] and TEXTE_BOUTON.search(ev[fin][2] or ""):
            # bouton « Voir l'annonce » seul (liens de suivi tous différents, ex. SeLoger) :
            # la carte est AVANT le bouton, depuis la fin de la carte précédente
            precedent = max((x for x in fins if x < fin), default=-1)
            c["debut"] = max(precedent + 1, fin - 14)
        elif fin == c["debut"]:  # lien unique : son texte + ce qui suit, jusqu'au prochain lien d'annonce
            suivant = next((d for d in debuts if d > fin), len(ev))
            fin = min(suivant - 1, fin + 6)
        morceaux = []
        for e in ev[c["debut"]:fin + 1]:
            t = e[1] if e[0] == "texte" else e[2]
            if t and not TEXTE_BOUTON.fullmatch(t.strip()) and not any(m in t.lower() for m in MOTS_PIED_DE_PAGE):
                morceaux.append(t)
        morceaux = [m for m in morceaux if not ENTETE_ALERTE.search(m)]
        texte = " · ".join(x for x in (" ".join(m.split()) for m in morceaux) if x)
        if not c["photo"]:  # photo sur un lien voisin (liens de suivi tous différents)
            c["photo"] = next((e[3] for e in ev[c["debut"]:fin + 1] if e[0] == "lien" and len(e) > 3 and e[3]), None)
        if not INDICES_ANNONCE.search(texte):
            continue
        a = {"cle": "mail:" + hashlib.sha1(k.encode()).hexdigest()[:16], "source": domaine, "url": nettoyer_url(c["url"]),
             "titre": texte[:150], "description": texte}
        if c["photo"]:
            a["photo"] = c["photo"]
        a = _lire_carte(a, texte)
        if SUIVI_OPAQUE.search(c["url"]):
            # lien de suivi chiffré, différent à chaque mail : la clé anti-doublon vient du contenu
            contenu = f"{domaine}|{a.get('prix')}|{a.get('surface')}|{a.get('code_postal')}|{a.get('pieces')}"
            a["cle"] = "mail:" + hashlib.sha1(contenu.encode()).hexdigest()[:16]
        annonces.append(a)
        if len(annonces) >= max_liens:
            break
    return annonces


def _corps_html(msg):
    texte = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        payload = part.get_payload(decode=True) or b""
        contenu = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html":
            return contenu
        # texte brut : on fabrique des pseudo-liens « ligne → URL »
        texte = "".join(f'<a href="{u}">{l}</a>' for l, u in re.findall(r"(.{6,150}?)\s*(https?://\S+)", contenu))
    return texte or ""


def recuperer(conf):
    """Lit les alertes reçues ces 2 derniers jours, sans rien modifier dans la boîte mail
    (pas de « lu », pas de déplacement). Les doublons sont filtrés par l'adresse de l'annonce."""
    c = conf["sources"]["emails"]
    user, mdp = os.environ.get("IMAP_USER"), os.environ.get("IMAP_PASSWORD")
    if not (user and mdp):
        print("[emails] IMAP_USER / IMAP_PASSWORD absents, source ignorée")
        return []
    depuis = (datetime.now() - timedelta(days=c.get("jours", 2))).strftime("%d-%b-%Y")
    annonces, lus = [], 0
    with imaplib.IMAP4_SSL(c.get("imap_host", "imap.gmail.com")) as M:
        M.login(user, mdp.replace(" ", ""))
        M.select(c.get("dossier", "INBOX"), readonly=True)
        _, data = M.search(None, "SINCE", depuis)
        for num in data[0].split():
            _, h = M.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
            expediteur = parseaddr(email.message_from_bytes(h[0][1]).get("From", ""))[1].lower()
            domaine = next((x for x in c["expediteurs"] if expediteur.endswith(x)), None)
            if not domaine:
                continue  # pas une alerte immo : on n'ouvre même pas le mail
            _, d = M.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(d[0][1])
            sujet = str(make_header(decode_header(msg.get("Subject", ""))))
            trouvees = extraire_annonces(_corps_html(msg), domaine, c.get("liens_max_par_mail", 15))
            if domaine in c.get("sites_particuliers", []):
                for t in trouvees:
                    t["annonceur"] = "particulier"
            lus += 1
            annonces += trouvees
            if trouvees:
                print(f"[emails] {domaine} « {sujet[:50]} » → {len(trouvees)} annonce(s)")
    print(f"[emails] {lus} alerte(s) lue(s), {len(annonces)} annonce(s) extraite(s)")
    return annonces
