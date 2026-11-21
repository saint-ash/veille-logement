"""Source « pages de résultats » : lit directement les pages publiques de sites
d'annonces ouverts (ImmoJeune, Studapart, LocService, Location-Etudiant, Lesiteimmo…).

Règles de bonne conduite, appliquées automatiquement :
- on lit d'abord le robots.txt du site : si la page est interdite aux robots, on ne la lit pas ;
- une seule requête par page et par passage, avec une pause entre deux pages ;
- si le site répond 403 / 429 / captcha, on s'arrête là pour ce site (aucun contournement).

L'extraction réutilise le découpage en « cartes » des alertes mail : chaque lien
d'annonce + le texte autour (prix, surface, ville, code postal).
"""
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

from sources.emails import extraire_annonces

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
PAUSE_S = 3
_robots = {}


def autorise(url, session):
    """True si le robots.txt du site autorise la lecture de cette page."""
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        rp = robotparser.RobotFileParser()
        try:
            r = session.get(base + "/robots.txt", timeout=15)
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            rp.parse([])
        _robots[base] = rp
    return _robots[base].can_fetch("*", url)


def recuperer(conf, session=None):
    pages = conf["sources"].get("pages", {})
    if not pages.get("actif"):
        return []
    session = session or requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})
    annonces, bloques = [], set()
    for i, site in enumerate(pages.get("sites", [])):
        domaine = urlparse(site["url"]).netloc.removeprefix("www.")
        if domaine in bloques:
            continue
        if i:
            time.sleep(PAUSE_S)
        if not autorise(site["url"], session):
            print(f"[pages] {site['nom']} : interdit par le robots.txt du site, ignoré")
            continue
        try:
            r = session.get(site["url"], timeout=30)
        except requests.RequestException as ex:
            print(f"[pages] {site['nom']} : {ex}")
            continue
        if r.status_code in (403, 429) or "captcha" in r.text[:5000].lower():
            print(f"[pages] {site['nom']} : accès refusé (HTTP {r.status_code}), site ignoré")
            bloques.add(domaine)
            continue
        if r.status_code != 200:
            print(f"[pages] {site['nom']} : HTTP {r.status_code}")
            continue
        brutes = extraire_annonces(r.text, domaine, site.get("max", 40))
        # une page de résultats contient aussi des liens de menu (« Location studio Paris ») : sans prix, on jette
        trouvees = [a for a in brutes if a.get("prix") and (a.get("surface") or a.get("pieces"))]
        if brutes and not trouvees:
            print(f"[pages] {site['nom']} : {len(brutes)} lien(s) sans prix, ex. {[b['url'][:70] for b in brutes[:3]]}")
        for a in trouvees:
            a["source"] = site["nom"]
            if site.get("particuliers"):
                a["annonceur"] = "particulier"
        exemple = f" — ex. « {trouvees[0]['titre'][:60]} »" if trouvees else ""
        print(f"[pages] {site['nom']} : {len(r.text) // 1024} Ko, {len(trouvees)} annonce(s){exemple}")
        annonces += trouvees
    return annonces
