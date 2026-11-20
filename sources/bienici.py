"""Source Bien'ici : utilise l'API JSON publique qu'appelle le site lui-même.

Bien'ici agrège les annonces de milliers d'agences (dont beaucoup sont aussi
sur SeLoger / Logic-Immo). Une requête par page, toutes les 15 min : c'est
l'équivalent d'une personne qui rafraîchit la page de résultats.
"""
import json
import os

import requests

SEARCH_URL = "https://www.bienici.com/realEstateAds.json"
SUGGEST_URL = "https://res.bienici.com/suggest.json"
ZONES_CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "zones_bienici.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.bienici.com/",
}
PAGE_SIZE = 50


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _norm(x):
    import unicodedata
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower()
    return " ".join(x.replace("-", " ").split())


def resoudre_zones(villes, departements, session=None, cps_attendus=None):
    """Nom de commune / d'arrondissement -> zoneIds Bien'ici (mis en cache dans data/).

    On garde la proposition dont le nom correspond, ou dont un code postal est celui
    attendu (« Paris 15e » -> 75015), quel que soit son type (ville, arrondissement…).
    """
    cps_attendus = cps_attendus or {}
    cache = {}
    if os.path.exists(ZONES_CACHE):
        with open(ZONES_CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    session = session or _session()
    modifie = False
    for ville in villes:
        if ville in cache:
            continue
        r = session.get(SUGGEST_URL, params={"q": ville}, timeout=20)
        r.raise_for_status()
        trouve, attendu, meilleur = None, cps_attendus.get(ville), 0
        for item in r.json():
            if not item.get("zoneIds"):
                continue
            cps = [str(c) for c in (item.get("postalCodes") or [])]
            bon_dept = any(c.startswith(tuple(departements)) for c in cps) or not cps
            # priorité : nom exact > code postal attendu (zone précise) > ville du bon département
            note = (3 if _norm(item.get("name", "")) == _norm(ville) and bon_dept
                    else 2 if attendu and cps == [attendu]
                    else 1 if item.get("type") == "city" and bon_dept and not attendu else 0)
            if note > meilleur:
                trouve, meilleur = item["zoneIds"], note
        if trouve:
            cache[ville] = trouve
            modifie = True
        else:
            print(f"[bienici] zone introuvable : {ville}")
    if modifie:
        os.makedirs(os.path.dirname(ZONES_CACHE), exist_ok=True)
        with open(ZONES_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1, ensure_ascii=False)
    return [z for v in villes for z in cache.get(v, [])]


def arrondissements(exclus):
    """« Paris 1er » … « Paris 20e » (sans les arrondissements exclus) et leurs codes postaux."""
    noms = {}
    for n in range(1, 21):
        if n in exclus:
            continue
        noms[f"Paris {n}{'er' if n == 1 else 'e'}"] = f"750{n:02d}"
    return noms


def construire_filtres(conf_r, zone_ids, page):
    return {
        "size": PAGE_SIZE,
        "from": (page - 1) * PAGE_SIZE,
        "page": page,
        "showAllModels": False,
        "filterType": "rent",
        "propertyType": conf_r.get("types_bien", ["flat"]),
        "minRooms": conf_r.get("pieces_min", 1),
        "maxRooms": conf_r.get("pieces_max", 2),
        "maxPrice": conf_r.get("loyer_max"),
        "minArea": conf_r.get("surface_min"),
        "sortBy": "publicationDate",
        "sortOrder": "desc",
        "onTheMarket": [True],
        "zoneIdsByTypes": {"zoneIds": zone_ids},
    }


def normaliser(ad):
    """Convertit une annonce Bien'ici brute au format commun."""
    blur = ad.get("blurInfo") or {}
    pos = blur.get("position") or blur.get("centroid") or {}
    rayon_m = blur.get("radius") or 0
    photos = []
    for p in (ad.get("photos") or [])[:4]:
        u = (p.get("url_photo") or p.get("url")) if isinstance(p, dict) else p
        if u:
            photos.append(u)
    return {
        "cle": f"bienici:{ad['id']}",
        "source": "Bien'ici",
        "url": f"https://www.bienici.com/annonce/{ad['id']}",
        "titre": ad.get("title") or f"T{ad.get('roomsQuantity', '?')} {ad.get('city', '')}",
        "description": ad.get("description") or "",
        "prix": ad.get("price"),
        "surface": ad.get("surfaceArea"),
        "pieces": ad.get("roomsQuantity"),
        "ville": ad.get("city"),
        "code_postal": str(ad.get("postalCode") or ""),
        "lat": pos.get("lat"),
        "lon": pos.get("lon"),
        "rayon_flou_km": rayon_m / 1000,
        "photo": photos[0] if photos else None,
        "photos": photos,
        "charges": ad.get("charges"),
        "meuble": ad.get("isFurnished"),
        "etage": ad.get("floor"),
        "annonceur": ("particulier" if ad.get("adCreatedByPro") is False or ad.get("accountType") in ("particulier", "private")
                      else "agence" if ad.get("adCreatedByPro") or ad.get("accountType") in ("agency", "agence") else None),
        "frais_agence": ad.get("agencyRentalFee"),
        "date": ad.get("publicationDate"),
    }


def recuperer(conf, session=None):
    """Retourne la liste des annonces normalisées, secteur par secteur
    (sinon Paris, très actif, noierait les annonces du 92 et du 94)."""
    session = session or _session()
    conf_r, conf_g = conf["recherche"], conf["geo"]
    pages = conf["sources"]["bienici"].get("pages", {})
    secteurs, cps = {}, {}
    for v in conf_g["villes"]:
        if v["insee"] == "75056":  # Paris : arrondissement par arrondissement (18e et 19e exclus)
            arr = arrondissements(conf_g.get("paris_arrondissements_exclus", []))
            cps.update(arr)
            secteurs.setdefault(v.get("secteur", "principal"), []).extend(arr)
        else:
            secteurs.setdefault(v.get("secteur", "principal"), []).append(v["nom"])
    annonces = []
    for secteur, noms in secteurs.items():
        zones = resoudre_zones(noms, conf_g["departements"], session, cps)
        if not zones:
            print(f"[bienici] {secteur} : aucune zone résolue")
            continue
        n_pages = pages.get(secteur, 2) if isinstance(pages, dict) else pages
        for page in range(1, n_pages + 1):
            filtres = construire_filtres(conf_r, zones, page)
            r = session.get(SEARCH_URL, params={"filters": json.dumps(filtres)}, timeout=30)
            if r.status_code != 200:
                print(f"[bienici] {secteur} HTTP {r.status_code} — {r.text[:150]}")
                break
            rep = r.json()
            ads = rep.get("realEstateAds") or []
            if page == 1:
                print(f"[bienici] {secteur} : {len(zones)} zones, {rep.get('total', '?')} annonces au total sur Bien'ici")
            annonces += [normaliser(a) for a in ads]
            if len(ads) < PAGE_SIZE:
                break
        print(f"[bienici] {secteur} : {len(annonces)} annonces cumulées")
    return annonces
