"""Toutes les gares et stations d'Île-de-France (métro, RER, Transilien, tram).

Source : jeu de données officiel « Emplacement des gares IDF » d'Île-de-France
Mobilités (un point par gare et par ligne). Téléchargé une fois par mois et mis
en cache dans data/gares.json. En cas d'échec, on utilise les [[stations]] de
config.toml.
"""
import json
import os
import re
import time
import unicodedata

import requests

from geo import haversine_km

ICI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ICI, "data", "gares.json")
URLS = (
    "https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/emplacement-des-gares-idf/exports/json",
    "https://data.iledefrance-mobilites.fr/explore/dataset/emplacement-des-gares-idf/download/?format=json",
)
RAFRAICHIR_JOURS = 30
ALIAS_MODES = {"TRAIN": ("TRAIN", "TRANSILIEN", "TER"), "TRAMWAY": ("TRAM",), "METRO": ("METRO",), "RER": ("RER",)}


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace("'", " ").split())


def _champ(rec, *noms):
    for n in noms:
        if rec.get(n) not in (None, ""):
            return rec[n]
    return None


def _coord(rec):
    g = _champ(rec, "geo_point_2d", "geo_point", "coordonnees")
    if isinstance(g, dict) and "lat" in g:
        return float(g["lat"]), float(g["lon"])
    if isinstance(g, (list, tuple)) and len(g) == 2:
        return float(g[0]), float(g[1])
    shape = rec.get("geo_shape") or {}
    geom = shape.get("geometry", shape)
    if geom.get("type") == "Point":
        lon, lat = geom["coordinates"][:2]
        return float(lat), float(lon)
    return None


def normaliser(records, modes=("METRO", "RER", "TRAIN")):
    """Liste brute -> [{nom, lat, lon, lignes}] (une entrée par gare, lignes fusionnées)."""
    voulus = tuple(m for k in modes for m in ALIAS_MODES.get(k.upper(), (k.upper(),)))
    gares = []
    for rec in records:
        rec = rec.get("fields", rec)
        rec = {k.lower(): v for k, v in rec.items()}
        mode = str(_champ(rec, "mode", "mode_") or "").upper()
        if not mode.startswith(voulus):
            continue
        nom = _champ(rec, "nom_long", "nomlong", "nom_gares", "nom_iv", "nom")
        pos = _coord(rec)
        if not nom or not pos:
            continue
        indice = str(_champ(rec, "indice_lig", "ligne", "res_com") or "").replace("METRO", "").replace("RER", "").strip()
        ligne = ("M" + indice) if mode.startswith("METRO") and indice else ("T" + indice.lstrip("T") if mode.startswith("TRAM") else indice)
        if not re.fullmatch(r"[A-Z]?\d{0,2}[A-Z]?(?:BIS|B)?", ligne.upper()) or len(ligne) > 5:
            ligne = ""  # ex. « TER GRAND-EST » : on n'affiche pas de pastille
        for g in gares:  # même nom à moins de 400 m : même gare, on fusionne les lignes
            if _norm(g["nom"]) == _norm(nom) and haversine_km(g["lat"], g["lon"], *pos) < 0.4:
                if ligne and ligne not in g["lignes"]:
                    g["lignes"].append(ligne)
                break
        else:
            gares.append({"nom": nom, "lat": round(pos[0], 5), "lon": round(pos[1], 5), "lignes": [ligne] if ligne else []})
    return gares


def charger(conf):
    """Gares IDFM (cache mensuel), sinon les [[stations]] de la config."""
    secours = conf.get("stations", [])
    modes = conf["geo"].get("modes", ["METRO", "RER", "TRAIN"])
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    if cache.get("gares") and cache.get("modes") == modes and cache.get("v") == 2 and time.time() - cache.get("t", 0) < RAFRAICHIR_JOURS * 86400:
        return cache["gares"]
    for url in URLS:
        try:
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            gares = normaliser(r.json(), modes)
            if len(gares) < 100:
                raise ValueError(f"seulement {len(gares)} gares")
            cache = {"t": int(time.time()), "v": 2, "modes": modes, "source": url, "gares": gares}
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            print(f"[gares] {len(gares)} gares Île-de-France chargées")
            return gares
        except Exception as ex:
            print(f"[gares] {url[:60]}… : {ex}")
    if cache.get("gares"):
        return cache["gares"]
    print("[gares] données IDFM indisponibles : gares de secours de config.toml")
    return secours
