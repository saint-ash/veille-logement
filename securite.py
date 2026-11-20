"""Niveau de tranquillité par commune, à partir des statistiques officielles.

Source : « Bases statistiques communale, départementale et régionale de la
délinquance enregistrée par la police et la gendarmerie nationales » (SSMSI,
ministère de l'Intérieur), publiée en open data sur data.gouv.fr.

On additionne, pour la dernière année disponible, les taux pour 1 000 habitants
des faits qui touchent directement les personnes dans la rue ou les transports :
vols violents, violences physiques hors cadre familial, violences sexuelles. Chaque commune du 92 est ensuite
classée de 1 (taux le plus élevé) à 5 (taux le plus bas), par rapport à
Paris et à la petite couronne (75, 92, 93, 94).

Limite : c'est une moyenne sur toute la commune, pas rue par rue.
"""
import csv
import gzip
import io
import json
import os
import time
import unicodedata

import requests

ICI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ICI, "data", "securite.json")
URL_CSV_GZ = "https://www.data.gouv.fr/api/1/datasets/r/44ef4323-1097-48d5-8719-3c544b55d294"
RAFRAICHIR_JOURS = 30
# Violences seulement : les vols sans violence (vols à la tire) gonflent artificiellement
# les quartiers d'affaires et touristiques (La Défense, Paris) sans refléter le danger.
INDICATEURS = ("vols violents", "hors cadre familial", "coups et blessures", "violences sexuelles")
VERSION = 2


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace("'", " ").split())


def _col(entetes, *candidats):
    for c in candidats:
        for i, h in enumerate(entetes):
            if c in _norm(h).replace(" ", "_"):
                return i
    return None


def _nombre(x):
    try:
        return float(str(x).replace(" ", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


PETITE_COURONNE = ("75", "92", "93", "94")


def calculer(lignes_csv, departements=PETITE_COURONNE):
    """lignes_csv : itérable de lignes texte (en-tête compris). Renvoie {insee: infos}."""
    it = iter(lignes_csv)
    entete = next(it)
    sep = ";" if entete.count(";") >= entete.count(",") else ","
    lecteur = csv.reader(it, delimiter=sep)
    h = next(csv.reader([entete], delimiter=sep))
    i_code = _col(h, "codgeo", "code_commune", "insee")
    i_annee = _col(h, "annee")
    i_ind = _col(h, "indicateur", "classe")
    i_taux = _col(h, "taux_pour_mille", "tauxpourmille", "taux")
    i_unite = _col(h, "unite_de_compte", "unite")
    if None in (i_code, i_annee, i_ind, i_taux):
        raise ValueError(f"colonnes inattendues : {h}")

    par_commune = {}  # insee -> annee -> somme des taux
    for row in lecteur:
        if len(row) <= max(i_code, i_annee, i_ind, i_taux):
            continue
        code = row[i_code].strip().zfill(5)
        if not code.startswith(tuple(departements)):
            continue
        ind = _norm(row[i_ind])
        if "intrafamilial" in ind or not any(k in ind for k in INDICATEURS):
            continue
        if i_unite is not None and "logement" in _norm(row[i_unite]):
            continue
        taux = _nombre(row[i_taux])
        if taux is None:
            continue
        annee = row[i_annee].strip()
        par_commune.setdefault(code, {}).setdefault(annee, 0.0)
        par_commune[code][annee] += taux

    if not par_commune:
        raise ValueError("aucune donnée pour le département")
    derniere = max(a for v in par_commune.values() for a in v)
    taux = {c: v[derniere] for c, v in par_commune.items() if derniere in v}
    classes = sorted(taux, key=taux.get)  # du plus tranquille au moins tranquille
    n = len(classes)
    res = {}
    for rang, code in enumerate(classes):
        niveau = 5 - min(4, int(rang / n * 5))
        res[code] = {"niveau": niveau, "taux": round(taux[code], 1), "rang": rang + 1, "sur": n, "annee": derniere}
    return res


def charger(conf, forcer=False):
    """Renvoie {insee: infos}, en téléchargeant les stats au plus une fois par mois."""
    if not conf.get("securite", {}).get("actif", True):
        return {}
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    if (cache.get("communes") and not forcer and cache.get("v") == VERSION
            and time.time() - cache.get("t", 0) < RAFRAICHIR_JOURS * 86400):
        return cache["communes"]
    try:
        r = requests.get(URL_CSV_GZ, timeout=120)
        r.raise_for_status()
        brut = gzip.decompress(r.content) if r.content[:2] == b"\x1f\x8b" else r.content
        texte = io.TextIOWrapper(io.BytesIO(brut), encoding="utf-8-sig", errors="replace")
        communes = calculer(texte, tuple(sorted(set(PETITE_COURONNE) | set(conf["geo"].get("departements", [])))))
        cache = {"t": int(time.time()), "v": VERSION, "source": URL_CSV_GZ, "communes": communes}
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1)
        print(f"[sécurité] statistiques mises à jour ({len(communes)} communes)")
        return communes
    except Exception as ex:
        print(f"[sécurité] mise à jour impossible : {ex}")
        return cache.get("communes", {})


def commune_de(ville, code_postal, conf):
    """Retrouve l'entrée [[geo.villes]] d'une annonce (nom exact, puis début du nom)."""
    n = _norm(ville or "")
    villes = conf["geo"].get("villes", [])
    if not n:
        return None
    for v in villes:  # nom exact d'abord (« Colombes » ≠ « La Garenne-Colombes »)
        if _norm(v["nom"]) == n:
            return v
    for v in villes:  # puis « Rueil-Malmaison 92500 », « Paris 15e »…
        if n.startswith(_norm(v["nom"])):
            return v
    return None


def codes_securite(commune, code_postal):
    """Codes à chercher dans les stats : arrondissement de Paris d'abord, puis la commune."""
    codes = []
    cp = str(code_postal or "")
    if commune and commune["insee"] == "75056" and len(cp) == 5 and cp.startswith("750"):
        codes.append("751" + cp[-2:])
    if commune:
        codes.append(commune["insee"])
    return codes


def insee_de(ville, code_postal, conf):
    c = commune_de(ville, code_postal, conf)
    return c["insee"] if c else None
