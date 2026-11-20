"""Mémoire du robot (fichiers JSON dans data/, enregistrés dans Git).

- deja_vues.json : toutes les annonces croisées (clé -> date + dernier prix)
- annonces.json  : les annonces qui correspondent, affichées sur le site
"""
import json
import os
import time

ICI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ICI, "data")
RETENTION_VUES_JOURS = 60
RETENTION_ANNONCES_JOURS = 21


def _lire(path, defaut):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return defaut


def _ecrire(path, data, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, **kw)
    os.replace(tmp, path)


class Store:
    def __init__(self, dossier=DATA):
        self.p_vues = os.path.join(dossier, "deja_vues.json")
        self.p_annonces = os.path.join(dossier, "annonces.json")
        self.p_meta = os.path.join(dossier, "meta.json")
        self.premier_lancement = not os.path.exists(self.p_vues)
        brut = _lire(self.p_vues, {})
        # compatibilité v1 : {cle: timestamp}
        self.vues = {k: (v if isinstance(v, dict) else {"t": v, "p": None}) for k, v in brut.items()}
        self.annonces = {a["cle"]: a for a in _lire(self.p_annonces, {"annonces": []})["annonces"]}
        self.meta = _lire(self.p_meta, {})

    # -- annonces croisées --
    def get(self, cle):
        return self.vues.get(cle)

    def marquer(self, cle, prix=None):
        self.vues[cle] = {"t": int(time.time()), "p": prix}

    # -- annonces retenues --
    def retenir(self, a):
        ancien = self.annonces.get(a["cle"], {})
        a.setdefault("vu_le", ancien.get("vu_le") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if ancien.get("prix_initial"):
            a["prix_initial"] = ancien["prix_initial"]
        else:
            a.setdefault("prix_initial", a.get("prix"))
        self.annonces[a["cle"]] = a

    def sauver(self):
        maintenant = time.time()
        self.vues = {k: v for k, v in self.vues.items() if v["t"] >= maintenant - RETENTION_VUES_JOURS * 86400}
        limite = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(maintenant - RETENTION_ANNONCES_JOURS * 86400))
        gardees = sorted((a for a in self.annonces.values() if a.get("vu_le", "") >= limite),
                         key=lambda a: a.get("vu_le", ""), reverse=True)
        _ecrire(self.p_vues, self.vues, separators=(",", ":"), sort_keys=True)
        _ecrire(self.p_annonces, {"maj": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(maintenant)),
                                  "annonces": gardees}, indent=1)
        _ecrire(self.p_meta, self.meta, indent=1)
