"""Génère un site de démonstration (annonces inventées) : python demo.py [dossier]

Les niveaux de sécurité et les temps de trajet ne sont PAS inventés : ils restent
vides dans la démo et seront calculés sur les vraies données au premier passage.
"""
import random
import sys
import time

import main
from analyse import evaluer, references
from dashboard import construire

random.seed(11)
conf = main.charger_config()
# quelques stations de métro (approximatives) pour illustrer Paris et la proche couronne dans la démo
conf["stations"] = conf["stations"] + [
    {"nom": "Pont de Levallois", "lignes": ["M3"], "lat": 48.8973, "lon": 2.2802},
    {"nom": "Les Sablons", "lignes": ["M1"], "lat": 48.8812, "lon": 2.2718},
    {"nom": "Mairie de Clichy", "lignes": ["M13"], "lat": 48.9035, "lon": 2.3065},
    {"nom": "Commerce", "lignes": ["M8"], "lat": 48.8446, "lon": 2.2936},
    {"nom": "Parmentier", "lignes": ["M3"], "lat": 48.8652, "lon": 2.3747},
]
EX = [  # ville, cp, titre, pièces, m², loyer, gare proche, annonceur, frais
    ("Courbevoie", "92400", "Studio meublé lumineux, 5e étage avec ascenseur, digicode", 1, 24, 860, "Courbevoie", "agence", 290),
    ("Puteaux", "92800", "T2 meublé refait à neuf, balcon, proche commerces", 2, 34, 895, "Puteaux", "particulier", None),
    ("La Garenne-Colombes", "92250", "Studio meublé au calme sur cour, cuisine équipée", 1, 23, 780, "La Garenne-Colombes", "agence", 300),
    ("Colombes", "92700", "2 pièces meublé, résidence avec gardien, 3e étage", 2, 36, 870, "Colombes", "particulier", None),
    ("Suresnes", "92150", "Studio meublé vue dégagée, 10 min à pied des quais", 1, 21, 740, "Suresnes-Mont-Valérien", "agence", 270),
    ("Neuilly-sur-Seine", "92200", "Studio meublé haussmannien, 2e étage, gardien", 1, 19, 890, "Les Sablons", "agence", 250),
    ("Levallois-Perret", "92300", "Studio meublé rénové, interphone, 4e étage", 1, 22, 850, "Pont de Levallois", "particulier", None),
    ("Clichy", "92110", "T1 bis meublé, parquet, 1er étage", 1, 27, 820, "Mairie de Clichy", "agence", 340),
    ("Paris 15e", "75015", "Studio meublé 6e étage avec ascenseur, très calme", 1, 18, 880, "Commerce", "agence", 230),
    ("Paris 11e", "75011", "Studio meublé sur cour, idéal étudiant", 1, 20, 870, "Parmentier", "particulier", None),
    ("Bry-sur-Marne", "94360", "2 pièces meublé proche bords de Marne, 2e étage", 2, 38, 850, "Bry-sur-Marne", "particulier", None),
    ("Fontenay-sous-Bois", "94120", "Studio meublé à 5 min du RER Val de Fontenay", 1, 25, 760, "Val de Fontenay", "agence", 310),
    ("Eaubonne", "95600", "T2 meublé avec parking, résidence fermée", 2, 41, 820, "Eaubonne", "agence", 420),
    ("Nanterre", "92000", "Très beau T2 meublé 45 m², propriétaire actuellement à l'étranger", 2, 45, 520, "Nanterre-Préfecture", "particulier", None),
]
st = {s["nom"]: s for s in conf["stations"]}
annonces = []
for k, (ville, cp, titre, p, surf, prix, gare, ann, frais) in enumerate(EX):
    g = st[gare]
    a = {"cle": f"demo:{k}", "source": "pap.fr" if ann == "particulier" and k % 2 else ("leboncoin.fr" if ann == "particulier" else "Bien'ici"),
         "url": "https://www.bienici.com/", "titre": titre, "description": titre, "prix": prix, "surface": surf,
         "pieces": p, "ville": ville, "code_postal": cp, "lat": g["lat"] + random.uniform(-0.003, 0.003),
         "lon": g["lon"] + random.uniform(-0.004, 0.004), "rayon_flou_km": 0.4 if k % 6 == 0 else 0, "meuble": True,
         "etage": None, "annonceur": ann, "frais_agence": frais}
    if (ok := main.garder(a, conf)):
        ok["vu_le"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - k * 4700 - 500))
        annonces.append(ok)
    else:
        print("rejetée :", ville, titre)
annonces[1]["prix_initial"], annonces[1]["tags"] = 940, ["baisse"]
ref = references(annonces, conf["score"]["prix_m2_reference"])
for a in annonces:
    evaluer(a, conf, ref)
    main.nettoyer(a)
lieux = [{"nom": "SKEMA", "adresse": "5 Quai Marcel Dassault, 92150 Suresnes", "lat": 48.8655, "lon": 2.2290},
         {"nom": "Porte Maillot", "adresse": "Place de la Porte Maillot, 75017 Paris", "lat": 48.8780, "lon": 2.2845}]
construire(annonces, conf, sys.argv[1] if len(sys.argv) > 1 else "demo_site", demo=True, lieux=lieux)
print(len(annonces), "annonces de démo")
