"""Note /100, bonnes affaires, sécurité et détection d'annonces suspectes.

Note = prix au m² (30) + sécurité de la commune (20) + trajets vers tes lieux (20)
       + proximité de la gare (20) + surface (10).
Une donnée manquante compte pour la moitié de ses points.
"""
from statistics import median

# Un studio se loue toujours plus cher au m² qu'un T2 : on compare chaque
# annonce aux annonces du même type (T1 avec T1, T2 avec T2).
CORRECTION_TYPE = {1: 1.15, 2: 1.0}


def prix_m2(a):
    if a.get("prix") and a.get("surface"):
        return a["prix"] / a["surface"]
    return None


def references(annonces, defaut):
    """€/m² de référence pour (commune, type) : médiane commune+type (≥ 5 annonces),
    sinon médiane du type (≥ 5), sinon valeur par défaut corrigée du type."""
    groupes = {}
    for a in annonces:
        p = prix_m2(a)
        if p:
            t = a.get("pieces")
            groupes.setdefault(((a.get("ville") or "").lower(), t), []).append(p)
            groupes.setdefault((None, t), []).append(p)
    refs = {k: median(v) for k, v in groupes.items() if len(v) >= 5}

    def ref(ville, pieces=None):
        return (refs.get(((ville or "").lower(), pieces)) or refs.get((None, pieces))
                or defaut * CORRECTION_TYPE.get(pieces, 1.0))
    return ref


def _borne(x):
    return max(0.0, min(1.0, x))


def evaluer(a, conf, ref_de):
    """Ajoute score, détail de la note, prix_m2, ratio et tags à l'annonce (en place)."""
    s, r, g = conf["score"], conf["recherche"], conf["geo"]
    pm2 = prix_m2(a)
    ref = ref_de(a.get("ville"), a.get("pieces"))
    tags = set(a.get("tags", [])) - {"bonne_affaire", "suspect", "securise"}
    texte = f"{a.get('titre', '')} {a.get('description', '')} {a.get('extrait', '')}".lower()

    d = {}
    d["prix"] = 15.0
    if pm2:
        ratio = pm2 / ref
        a["ratio_marche"] = round(ratio, 3)
        d["prix"] = 30 * _borne((1.25 - ratio) / 0.5)
        if ratio <= s["seuil_suspect"]:
            tags.add("suspect")
        elif ratio <= s["seuil_bonne_affaire"]:
            tags.add("bonne_affaire")

    niv = (a.get("securite") or {}).get("niveau")
    d["securite"] = 10.0 if niv is None else 20 * (niv - 1) / 4
    if any(m in texte for m in conf.get("securite", {}).get("mots_rassurants", [])):
        tags.add("securise")
        d["securite"] = min(20.0, d["securite"] + 3)

    trajets = [m for m in (a.get("trajets") or {}).values() if m is not None]
    dists = [k for k in (a.get("distances") or {}).values() if k is not None]
    if trajets:  # temps réels (clé PRIM) : 20 min ou moins = plein, 50 min = 0
        d["trajets"] = 20 * _borne((50 - sum(trajets) / len(trajets)) / 30)
    elif dists:  # sinon distance à vol d'oiseau : 2 km ou moins = plein, 12 km = 0
        d["trajets"] = 20 * _borne((12 - sum(dists) / len(dists)) / 10)
    else:
        d["trajets"] = 10.0

    dist = a.get("distance_km")
    d["gare"] = 10.0 if dist is None else 20 * _borne(1 - (dist / max(g["distance_max_km"], 0.1)) ** 2)
    if dist is None and (a.get("code_postal") or "").startswith("750"):
        d["gare"] = 16.0  # Paris : métro partout

    bas, ampleur = {1: (18, 14), 2: (28, 20)}.get(a.get("pieces"), (r.get("surface_min", 18), 25))
    d["surface"] = 5.0 if not a.get("surface") else 10 * _borne((a["surface"] - bas) / ampleur)

    d["bonus"] = (4 if a.get("coup_de_coeur") else 0) + (3 if a.get("annonceur") == "particulier" else 0)

    if any(m in texte for m in s.get("mots_suspects", [])):
        tags.add("suspect")
    if "suspect" in tags:
        tags.discard("bonne_affaire")

    a["prix_m2"] = round(pm2, 1) if pm2 else None
    a["note_detail"] = {k: round(v) for k, v in d.items()}
    a["score"] = min(100, round(sum(d.values())))
    if "suspect" in tags:
        a["score"] = min(a["score"], 15)  # jamais en tête de liste
    a["tags"] = sorted(tags)
    return a
