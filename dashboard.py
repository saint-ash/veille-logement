"""Génère le site (docs/index.html) à partir des annonces retenues."""
import json
import os
import shutil
import time

ICI = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(ICI, "dashboard", "template.html")
CHAMPS = ("cle", "source", "url", "titre", "extrait", "prix", "prix_initial", "surface", "pieces", "ville",
          "code_postal", "lat", "lon", "gare", "gare_lat", "gare_lon", "distance_km", "minutes", "position_approx",
          "photo", "photos", "vu_le", "baisse_le", "score", "prix_m2", "ratio_marche", "tags", "meuble", "charges",
          "lignes", "etage", "securite", "trajets", "note_detail", "annonceur", "frais_agence", "coup_de_coeur")


def donnees(annonces, conf, demo=False, lieux=()):
    return {
        "maj": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "demo": demo,
        "lien_dossier": conf.get("candidature", {}).get("lien_dossier", ""),
        "criteres": {k: conf["recherche"].get(k) for k in ("loyer_max", "surface_min", "pieces_min", "pieces_max")}
        | {"distance_max_km": conf["geo"]["distance_max_km"]},
        "stations": [{"nom": s["nom"], "lat": s["lat"], "lon": s["lon"], "lignes": s.get("lignes", [])}
                     for s in conf["stations"] if s.get("actif", True)],
        "lieux": [{"nom": l["nom"], "adresse": l.get("adresse", ""), "lat": l.get("lat"), "lon": l.get("lon")} for l in lieux],
        "annonces": [{k: a[k] for k in CHAMPS if a.get(k) not in (None, "", [])} for a in annonces],
    }


def rendre(payload):
    with open(TEMPLATE, encoding="utf-8") as f:
        modele = f.read()
    js = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return modele.replace("__DONNEES__", js)


def construire(annonces, conf, sortie, demo=False, lieux=()):
    os.makedirs(sortie, exist_ok=True)
    with open(os.path.join(sortie, "index.html"), "w", encoding="utf-8") as f:
        f.write(rendre(donnees(annonces, conf, demo, lieux)))
    for nom in ("manifest.webmanifest", "icon.svg"):
        src = os.path.join(ICI, "dashboard", nom)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(sortie, nom))
    # GitHub Pages : ne pas passer le site dans Jekyll
    open(os.path.join(sortie, ".nojekyll"), "w").close()
