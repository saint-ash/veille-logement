"""Veille logement — T1/T2 meublés près d'une gare (92, Paris, 94, 95), particuliers et agences.

Usage :
    python main.py               # un passage (GitHub le lance toutes les 10 min)
    python main.py --dry-run     # affiche les notifs au lieu de les envoyer
    python main.py --test-notif  # envoie un message de test sur Telegram
"""
import argparse
import json
import os
import sys
import tomllib
from datetime import datetime
from zoneinfo import ZoneInfo

import re

import gares
import securite
from analyse import evaluer, references
from dashboard import construire
from geo import gare_la_plus_proche, haversine_km, minutes_a_pied
from lieux import Trajets, charger_lieux
from notify import Notifier, entete
from store import Store

ICI = os.path.dirname(os.path.abspath(__file__))
PARIS = ZoneInfo("Europe/Paris")
MAX_NOTIFS_PAR_PASSAGE = 25


def charger_secrets(path=os.path.join(ICI, "secrets.env")):
    """Lancement sur ton PC : lit TELEGRAM_TOKEN=... etc. depuis secrets.env."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for ligne in f:
            if "=" in ligne and not ligne.lstrip().startswith("#"):
                k, v = ligne.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


def charger_config(path=os.path.join(ICI, "config.toml")):
    with open(path, "rb") as f:
        return tomllib.load(f)


RE_NON_MEUBLE = re.compile(r"non[- ]?meubl|\b(?:studio|appartement|logement|location|loué|t[1-5]|f[1-5]|pièces?)\s+vides?\b", re.I)
RE_MEUBLE = re.compile(r"\bmeubl[ée]e?s?\b|\bmeuble\b|\bfurnished\b", re.I)
RE_RDC = re.compile(r"rez[- ]de[- ]chauss[ée]e|\brdc\b", re.I)


def est_meuble(a):
    """True / False / None (inconnu). Le texte de l'annonce prime sur le champ du site."""
    texte = f"{a.get('titre', '')} {a.get('description', '')}"
    if RE_NON_MEUBLE.search(texte):
        return False
    if RE_MEUBLE.search(texte):
        return True
    return a.get("meuble") if isinstance(a.get("meuble"), bool) else None


def est_rdc(a):
    if a.get("etage") == 0:
        return True
    texte = f"{a.get('titre', '')} {a.get('description', '')}".lower()
    return bool(RE_RDC.search(texte)) and "surélev" not in texte


def arrondissement_de(a):
    """75015 / 75116 / « Paris 15e » / « Paris 15ème » -> 15 ; None hors de Paris."""
    cp = str(a.get("code_postal") or "")
    if len(cp) == 5 and cp.startswith("75") and cp[2] in "01":
        n = int(cp[-2:])
        return n if 1 <= n <= 20 else None
    m = re.search(r"paris\s*(\d{1,2})\s*(?:e|er|ème|eme)?\b", f"{a.get('ville', '')} {a.get('titre', '')}", re.I)
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 20 else None


def garder(a, conf):
    """Applique les critères. Renvoie l'annonce enrichie, ou None si rejetée."""
    r, g, sec = conf["recherche"], conf["geo"], conf.get("securite", {})
    cp = a.get("code_postal") or ""
    if cp and not cp.startswith(tuple(g["departements"])):
        return None
    arr = arrondissement_de(a)
    if arr and g.get("paris_arrondissements") and arr not in g["paris_arrondissements"]:
        return None
    if arr in g.get("paris_coups_de_coeur", []):
        a["coup_de_coeur"] = True
    if cp.startswith("750") and len(cp) == 5 and int(cp[-2:] or 0) in g.get("paris_arrondissements_exclus", []):
        return None
    prix = a.get("prix")
    if prix is not None and not (r.get("loyer_min", 0) <= prix <= r["loyer_max"]):
        return None
    if a.get("surface") is not None and a["surface"] < r.get("surface_min", 0):
        return None
    if a.get("pieces") is not None and not (r["pieces_min"] <= a["pieces"] <= r["pieces_max"]):
        return None
    texte = f"{a.get('titre', '')} {a.get('description', '')}".lower()
    if any(m.lower() in texte for m in r.get("mots_exclus", [])):
        return None

    meuble = est_meuble(a)
    a["meuble"] = meuble
    if r.get("meuble") == "oui":
        # inconnu : on garde les alertes mail (le filtre « meublé » est réglé sur le site d'origine)
        if meuble is False or (meuble is None and not a["cle"].startswith("mail:")):
            return None
    elif r.get("meuble") == "non" and meuble is True:
        return None
    if r.get("exclure_rdc") and est_rdc(a):
        return None

    if not a.get("ville"):  # alertes mail : on cherche la commune dans le titre
        for v in sorted(g.get("villes", []), key=lambda v: -len(v["nom"])):
            if securite._norm(v["nom"]) in securite._norm(a.get("titre", "")):
                a["ville"] = v["nom"]
                break
    commune = securite.commune_de(a.get("ville"), cp, conf)
    if commune is None and (a["cle"].startswith("bienici:") or conf["sources"]["emails"].get("communes_strictes", True)):
        return None  # hors des communes choisies (ex. alerte Studapart trop large : Bezons…)
    if commune:
        a["insee"] = commune["insee"]
        if commune.get("coup_de_coeur"):
            a["coup_de_coeur"] = True
        for code in securite.codes_securite(commune, cp):
            infos = conf.get("_securite", {}).get(code)
            if infos:
                a["securite"] = {**infos, "code": code}
                if infos["niveau"] < sec.get("niveau_min", 1):
                    return None
                break

    pres_gare = (commune or {}).get("zone", "gare") == "gare"
    if a.get("lat") is not None and a.get("lon") is not None:
        for z in sec.get("zones_a_eviter", []):
            if haversine_km(a["lat"], a["lon"], z["lat"], z["lon"]) * 1000 < z.get("rayon_m", 300):
                return None
        res = gare_la_plus_proche(a["lat"], a["lon"], conf["stations"])
        flou = a.get("rayon_flou_km", 0) or 0
        if res is None or max(0.0, res[1] - flou) > g["distance_max_km"]:
            if pres_gare:
                return None
            res = res if res and res[1] <= 1.5 else None  # « toute la commune » : gare affichée si proche
        if res:
            gare, dist = res
            a.update(gare=gare["nom"], lignes=gare.get("lignes", []), gare_lat=gare["lat"], gare_lon=gare["lon"],
                     distance_km=round(dist, 3), minutes=minutes_a_pied(dist), position_approx=flou > 0.3)
    elif a["cle"].startswith("bienici:") and pres_gare:
        return None  # pas de position : impossible de vérifier la proximité d'une gare
    return a


def nettoyer(a):
    """Allège l'annonce avant de l'enregistrer / l'afficher."""
    desc = (a.pop("description", "") or "").strip()
    if desc and desc != a.get("titre"):
        a["extrait"] = desc[:280] + ("…" if len(desc) > 280 else "")
    return a


def collecter(conf, fixtures=False):
    annonces = []
    if fixtures:
        from sources import bienici, emails
        dossier = os.path.join(ICI, "tests", "fixtures")
        with open(os.path.join(dossier, "bienici.json"), encoding="utf-8") as f:
            annonces += [bienici.normaliser(x) for x in json.load(f)["realEstateAds"]]
        for nom in sorted(os.listdir(dossier)):
            if nom.endswith(".html"):
                with open(os.path.join(dossier, nom), encoding="utf-8") as f:
                    annonces += emails.extraire_annonces(f.read(), nom.split("_")[0])
        return annonces

    if conf["sources"]["bienici"].get("actif"):
        from sources import bienici
        try:
            annonces += bienici.recuperer(conf)
        except Exception as ex:  # une source en panne ne bloque pas les autres
            print(f"[bienici] erreur : {ex}")
    if conf["sources"].get("pages", {}).get("actif"):
        from sources import pages
        try:
            annonces += pages.recuperer(conf)
        except Exception as ex:
            print(f"[pages] erreur : {ex}")
    if conf["sources"]["emails"].get("actif"):
        from sources import emails
        try:
            annonces += emails.recuperer(conf)
        except Exception as ex:
            print(f"[emails] erreur : {ex}")
    return annonces


def jour_paris(iso_utc):
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(PARIS).date().isoformat()


def bilan_du_jour(store, conf, notif, maintenant):
    heure = conf["notifications"].get("bilan_quotidien_heure", 20)
    aujourdhui = maintenant.date().isoformat()
    if heure < 0 or maintenant.hour < heure or store.meta.get("bilan") == aujourdhui:
        return
    store.meta["bilan"] = aujourdhui
    du_jour = [a for a in store.annonces.values() if jour_paris(a["vu_le"]) == aujourdhui]
    baisses = [a for a in store.annonces.values() if a.get("baisse_le") and jour_paris(a["baisse_le"]) == aujourdhui]
    lignes = [f"🌙 <b>Bilan du jour</b> — {len(du_jour)} nouvelle(s) annonce(s), {len(baisses)} baisse(s) de prix"]
    for a in sorted(du_jour, key=lambda a: -a.get("score", 0))[:3]:
        lignes.append(f'• <a href="{a["url"]}">{entete(a)}</a> — {a.get("ville") or a["source"]} · {a.get("score", "?")}/100')
    if not du_jour:
        lignes.append("Rien de neuf aujourd'hui. Le robot continue de chercher 👀")
    notif.envoyer_texte("\n".join(lignes), notif.url_site or None)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fixtures", action="store_true", help="données de test hors-ligne")
    ap.add_argument("--test-notif", action="store_true")
    ap.add_argument("--data", default=None, help="dossier de mémoire (tests)")
    ap.add_argument("--site", default=os.path.join(ICI, "docs"), help="dossier du site généré")
    ap.add_argument("--maintenant", default=None, help="date/heure simulée (tests), ex. 2026-11-20T20:05")
    args = ap.parse_args(argv)

    charger_secrets()
    conf = charger_config()
    notif = Notifier(conf["notifications"], dry_run=args.dry_run)
    notif.lieux = conf.get("lieux", [])
    if args.test_notif:
        notif.envoyer_texte("✅ <b>Veille logement</b> : les notifications fonctionnent !", notif.url_site or None)
        return 0

    maintenant = (datetime.fromisoformat(args.maintenant).replace(tzinfo=PARIS) if args.maintenant
                  else datetime.now(PARIS))
    store = Store(args.data) if args.data else Store()
    if args.fixtures:
        with open(os.path.join(ICI, "tests", "fixtures", "ssmsi.csv"), encoding="utf-8") as f:
            conf["_securite"] = securite.calculer(f)
        lieux = [{"nom": "SKEMA", "adresse": "5 Quai Marcel Dassault, 92150 Suresnes", "lat": 48.8655, "lon": 2.2290},
                 {"nom": "Porte Maillot", "adresse": "Place de la Porte Maillot, 75017 Paris", "lat": 48.8780, "lon": 2.2845}]
    else:
        conf["_securite"] = securite.charger(conf)
        conf["stations"] = gares.charger(conf)
        lieux = charger_lieux(conf)
    trajets = Trajets()
    brutes = collecter(conf, fixtures=args.fixtures)

    nouvelles, baisses = [], []
    for a in brutes:
        prec = store.get(a["cle"])
        if prec is None:
            store.marquer(a["cle"], a.get("prix"))
            if (ok := garder(a, conf)) is not None:
                nouvelles.append(ok)
        elif a.get("prix") and prec.get("p") and a["prix"] < prec["p"] - 0.5:
            ancien = prec["p"]
            store.marquer(a["cle"], a["prix"])
            if (ok := garder(a, conf)) is not None:
                ok["tags"] = sorted(set(store.annonces.get(ok["cle"], {}).get("tags", [])) | {"baisse"})
                ok["baisse_le"] = maintenant.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
                baisses.append((ok, ancien))

    modifiees = nouvelles + [b for b, _ in baisses]
    for a in modifiees:
        if a.get("lat") is not None and lieux:
            a["distances"] = {l["nom"]: round(haversine_km(a["lat"], a["lon"], l["lat"], l["lon"]), 1)
                              for l in lieux if l.get("lat") is not None}
            a["trajets"] = {l["nom"]: trajets.minutes(a["lat"], a["lon"], l) for l in lieux}
    trajets.sauver()
    ref_de = references(list(store.annonces.values()) + modifiees, conf["score"]["prix_m2_reference"])
    for a in modifiees:
        evaluer(a, conf, ref_de)
        store.retenir(nettoyer(a))
    for a in store.annonces.values():  # les médianes bougent : on rafraîchit les notes
        evaluer(a, conf, ref_de)
    nouvelles.sort(key=lambda a: a.get("date") or a.get("vu_le") or "")
    print(f"{len(brutes)} annonces récupérées · {len(nouvelles)} nouvelles retenues · {len(baisses)} baisse(s) de prix")

    c_notif = conf["notifications"]
    if store.premier_lancement and not c_notif.get("notifier_existant_au_premier_lancement"):
        lignes = [f"🟢 <b>Veille logement démarrée</b>\n{len(nouvelles)} annonces correspondent déjà à tes critères. "
                  "Voici les mieux notées ; ensuite tu ne recevras que les nouvelles."]
        for a in sorted(nouvelles, key=lambda a: -a.get("score", 0))[:10]:
            lignes.append(f'• <a href="{a["url"]}">{entete(a)}</a> — {a.get("ville") or a["source"]} · {a.get("score")}/100')
        notif.envoyer_texte("\n".join(lignes), notif.url_site or None)
    else:
        a_envoyer = [a for a in nouvelles if a.get("score", 0) >= c_notif.get("score_min", 0)]
        for a in a_envoyer[:MAX_NOTIFS_PAR_PASSAGE]:
            notif.envoyer_annonce(a)
        if len(a_envoyer) > MAX_NOTIFS_PAR_PASSAGE:
            notif.envoyer_texte(f"… et {len(a_envoyer) - MAX_NOTIFS_PAR_PASSAGE} autres annonces sur ton tableau de bord.",
                                notif.url_site or None)
        for a, ancien in baisses:
            notif.envoyer_annonce(a, baisse_depuis=ancien)

    bilan_du_jour(store, conf, notif, maintenant)
    construire(list(store.annonces.values()), conf, args.site, lieux=lieux)
    if not args.dry_run or args.data:
        store.sauver()
    return 0


if __name__ == "__main__":
    sys.exit(main())
