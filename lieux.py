"""Tes lieux du quotidien (SKEMA, travail) : géocodage et temps de trajet.

- Géocodage : Géoplateforme de l'IGN (gratuit, sans clé), repli sur api-adresse.
- Trajets en transports : calculateur officiel d'Île-de-France Mobilités (PRIM,
  gratuit, nécessite une clé PRIM_API_KEY). Sans clé, le site et Telegram
  proposent simplement un lien Google Maps.
"""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

ICI = os.path.dirname(os.path.abspath(__file__))
CACHE_LIEUX = os.path.join(ICI, "data", "lieux.json")
CACHE_TRAJETS = os.path.join(ICI, "data", "trajets.json")
GEOCODEURS = ("https://data.geopf.fr/geocodage/search", "https://api-adresse.data.gouv.fr/search/")
PRIM_URLS = ("https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/journeys",
             "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/coverage/idfm/journeys")
PARIS = ZoneInfo("Europe/Paris")


def _lire(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _ecrire(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def geocoder(adresse):
    for url in GEOCODEURS:
        try:
            r = requests.get(url, params={"q": adresse, "limit": 1}, timeout=20)
            if r.ok and r.json().get("features"):
                lon, lat = r.json()["features"][0]["geometry"]["coordinates"]
                return lat, lon
        except (requests.RequestException, ValueError, KeyError, IndexError):
            continue
    return None


_CENTRES = {}


def centre_commune(ville, cp):
    """Centre de la commune (ou de l'arrondissement pour Paris), en cache dans data/lieux.json."""
    cle = f"centre:{cp or ''}:{ville or ''}".lower()
    if not _CENTRES:
        _CENTRES.update(_lire(CACHE_LIEUX) or {})
    if cle not in _CENTRES:
        q = f"{ville or ''} {cp or ''}".strip()
        r = None
        for url in GEOCODEURS:
            try:
                rep = requests.get(url, params={"q": q, "type": "municipality", "limit": 1}, timeout=20)
                if rep.ok and rep.json().get("features"):
                    lon, lat = rep.json()["features"][0]["geometry"]["coordinates"]
                    r = [lat, lon]
                    break
            except (requests.RequestException, ValueError, KeyError, IndexError):
                continue
        if r is None:
            return None
        _CENTRES[cle] = r
        _ecrire(CACHE_LIEUX, {**(_lire(CACHE_LIEUX) or {}), cle: r})
    return tuple(_CENTRES[cle])


def charger_lieux(conf):
    """[{nom, adresse, lat, lon}] — les coordonnées sont mises en cache dans data/."""
    cache, modifie, lieux = _lire(CACHE_LIEUX), False, []
    for l in conf.get("lieux", []):
        l = dict(l)
        if "lat" not in l:
            if l["adresse"] in cache:
                l["lat"], l["lon"] = cache[l["adresse"]]
            elif (pos := geocoder(l["adresse"])):
                l["lat"], l["lon"] = pos
                cache[l["adresse"]] = pos
                modifie = True
            else:
                print(f"[lieux] adresse introuvable : {l['adresse']}")
        lieux.append(l)
    if modifie:
        _ecrire(CACHE_LIEUX, cache)
    return lieux


def _prochain_matin():
    """Prochain jour ouvré à 8h30 : un trajet « type » pour aller en cours."""
    j = datetime.now(PARIS) + timedelta(days=1)
    while j.weekday() >= 5:
        j += timedelta(days=1)
    return j.strftime("%Y%m%dT083000")


class Trajets:
    def __init__(self):
        self.cle = os.environ.get("PRIM_API_KEY", "")
        self.cache = _lire(CACHE_TRAJETS)
        self.modifie = False
        self.url_ok = None
        self.erreurs = 0

    @property
    def actif(self):
        return bool(self.cle) and self.erreurs < 3

    def minutes(self, lat, lon, lieu):
        if lieu.get("lat") is None:
            return None
        k = f"{lat:.4f},{lon:.4f}>{lieu['nom']}"
        if k in self.cache:
            return self.cache[k]
        if not self.actif:
            return None
        params = {"from": f"{lon};{lat}", "to": f"{lieu['lon']};{lieu['lat']}",
                  "datetime": _prochain_matin(), "count": 3}
        for url in ([self.url_ok] if self.url_ok else PRIM_URLS):
            try:
                r = requests.get(url, params=params, headers={"apikey": self.cle, "Accept": "application/json"}, timeout=25)
            except requests.RequestException as ex:
                print(f"[trajets] {ex}")
                continue
            if r.status_code == 404 and not self.url_ok:
                continue
            if not r.ok:
                print(f"[trajets] HTTP {r.status_code} {r.text[:150]}")
                self.erreurs += 1
                return None
            self.url_ok = url
            durees = [j.get("duration") for j in r.json().get("journeys", []) if j.get("duration")]
            if not durees:
                return None
            m = round(min(durees) / 60)
            self.cache[k] = m
            self.modifie = True
            return m
        self.erreurs += 1
        return None

    def sauver(self):
        if self.modifie:
            _ecrire(CACHE_TRAJETS, self.cache)
