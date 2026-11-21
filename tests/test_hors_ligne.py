"""Tests hors-ligne :  python -m unittest discover tests"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))

import main  # noqa: E402
import securite  # noqa: E402
from analyse import evaluer, references  # noqa: E402
from geo import haversine_km  # noqa: E402
from sources import bienici, emails  # noqa: E402


def lancer(*args):
    out = io.StringIO()
    with redirect_stdout(out):
        main.main(list(args))
    return out.getvalue()


class Tests(unittest.TestCase):
    def setUp(self):
        self.conf = main.charger_config()
        with open(os.path.join(ICI, "fixtures", "ssmsi.csv"), encoding="utf-8") as f:
            self.conf["_securite"] = securite.calculer(f)

    def test_distance(self):
        self.assertAlmostEqual(haversine_km(48.8918, 2.2378, 48.8957, 2.2136), 1.8, delta=0.2)

    def test_filtre_bienici(self):
        with open(os.path.join(ICI, "fixtures", "bienici.json"), encoding="utf-8") as f:
            ads = [bienici.normaliser(a) for a in json.load(f)["realEstateAds"]]
        gardees = {a["cle"] for a in ads if main.garder(dict(a), self.conf)}
        # 002 trop loin d'une gare (Rueil = zone « gare ») · 004 trop cher · 005 coloc · 006 Paris 18e exclu
        # 007 trop petit · 008 non meublé · 009 rez-de-chaussée · 011 meublé non précisé
        # 012 Paris 15e et 015 Bry-sur-Marne : communes entières acceptées
        self.assertEqual(gardees, {"bienici:ag1-001", "bienici:ag1-003", "bienici:ag1-010", "bienici:ag1-012", "bienici:ag1-015"})

    def test_particulier_paris(self):
        with open(os.path.join(ICI, "fixtures", "bienici.json"), encoding="utf-8") as f:
            ads = {a["id"]: bienici.normaliser(a) for a in json.load(f)["realEstateAds"]}
        coloc = main.garder(ads["ag1-010"], self.conf)
        self.assertEqual(coloc["annonceur"], "particulier")
        paris = main.garder(ads["ag1-012"], self.conf)
        self.assertEqual((paris["annonceur"], paris["frais_agence"]), ("agence", 330))
        self.assertEqual(paris["securite"]["code"], "75056")  # pas de stats par arrondissement -> Paris entier
        self.assertNotIn("gare", paris)  # aucune gare de la liste à moins de 1,5 km
        bry = main.garder(ads["ag1-015"], self.conf)
        self.assertEqual(bry["gare"], "Bry-sur-Marne")
        courbevoie = main.garder(ads["ag1-003"], self.conf)
        self.assertTrue(courbevoie["coup_de_coeur"])

    def test_gares_idfm(self):
        import gares
        brut = [{"nom_long": "La Défense", "mode": "RER", "indice_lig": "A", "geo_point_2d": {"lon": 2.2385, "lat": 48.8919}},
                {"nom_long": "La Défense", "mode": "METRO", "indice_lig": "1", "geo_point_2d": {"lon": 2.2386, "lat": 48.8920}},
                {"nom_long": "Puteaux", "mode": "TRAMWAY", "indice_lig": "T2", "geo_point_2d": {"lon": 2.23, "lat": 48.88}},
                {"fields": {"NOM_GARES": "Porte Maillot", "MODE": "METRO", "INDICE_LIG": "1", "geo_point_2d": [48.878, 2.2826]}}]
        g = gares.normaliser(brut)
        self.assertEqual([(x["nom"], x["lignes"]) for x in g], [("La Défense", ["A", "M1"]), ("Porte Maillot", ["M1"])])

    def test_filtres_bienici_requete(self):
        f = bienici.construire_filtres(self.conf["recherche"], ["-123"], 2)
        self.assertEqual((f["from"], f["maxRooms"], f["filterType"], f["maxPrice"]), (50, 2, "rent", 900))

    def test_emails(self):
        with open(os.path.join(ICI, "fixtures", "leboncoin.fr_alerte.html"), encoding="utf-8") as f:
            ann = emails.extraire_annonces(f.read(), "leboncoin.fr")
        self.assertEqual(len(ann), 5)
        self.assertEqual((ann[0]["prix"], ann[3]["prix"]), (880, 1600))
        gardees = [g for g in (main.garder(dict(a), self.conf) for a in ann) if g]
        self.assertEqual([a["prix"] for a in gardees], [880, 690])  # parking, 1600 €, « studio vide » rejetés
        self.assertEqual(gardees[0]["ville"], "Nanterre")  # commune retrouvée dans le titre
        self.assertIn("securite", gardees[0])

    def test_vraies_alertes(self):
        """Formats réels (anonymisés) des alertes Studapart et PAP."""
        with open(os.path.join(ICI, "fixtures", "studapart.com_alerte.html"), encoding="utf-8") as f:
            stud = emails.extraire_annonces(f.read(), "studapart.com", 15)
        self.assertEqual(len(stud), 6)
        self.assertTrue(all(a["url"].startswith("https://www.studapart.com/fr/") and "utm_" not in a["url"] for a in stud))
        self.assertEqual([a["prix"] for a in stud], [737, 690, 450, 1379, 1250, 880])
        self.assertEqual((stud[5]["surface"], stud[5]["pieces"]), (20, 1))
        # colocations, Bezons (hors zone) et studio de Puteaux à 1 379 € : rien ne passe
        self.assertEqual([a for a in stud if main.garder(dict(a), self.conf)], [])
        with open(os.path.join(ICI, "fixtures", "pap.fr_alerte.html"), encoding="utf-8") as f:
            pap = emails.extraire_annonces(f.read(), "pap.fr")
        self.assertEqual(len(pap), 1)  # pas le « Pass Prioritaire à 39 € » ni le webinaire
        self.assertEqual((pap[0]["prix"], pap[0]["surface"], pap[0]["pieces"], pap[0]["code_postal"]), (1160, 35, 2, "93360"))
        self.assertTrue(pap[0]["photo"].startswith("https://cdn.pap.fr/"))
        self.assertEqual(emails.cle_url(pap[0]["url"]), "pap.fr/annonces/-r465301608")
        self.assertNotIn("email", pap[0]["url"])  # ton adresse ne doit jamais finir sur le site

    def test_paris_arrondissements(self):
        self.conf["_securite"] = {}
        def essai(titre, cp):
            return main.garder({"cle": "mail:x", "titre": titre, "prix": 800, "surface": 20, "pieces": 1, "code_postal": cp}, self.conf)
        self.assertTrue(essai("Studio meublé Paris 17", "75017")["coup_de_coeur"])   # très bon
        self.assertTrue(essai("Studio meublé Paris 16", "75116")["coup_de_coeur"])   # 75116 = 16e
        self.assertIsNotNone(essai("Studio meublé Paris 5e", "75005"))                # bon
        self.assertIsNone(essai("Studio meublé Paris 13ème", "75013"))                # hors sélection
        self.assertIsNone(essai("Studio meublé Paris 18e", "75018"))
        self.assertEqual(main.arrondissement_de({"ville": "Paris 15e"}), 15)

    def test_note_distance_sans_cle(self):
        ref = references([], 30)
        proche = evaluer({"pieces": 1, "prix": 800, "surface": 22, "distances": {"SKEMA": 2.0, "Porte Maillot": 2.5}}, self.conf, ref)
        loin = evaluer({"pieces": 1, "prix": 800, "surface": 22, "distances": {"SKEMA": 11.0, "Porte Maillot": 12.0}}, self.conf, ref)
        self.assertGreater(proche["note_detail"]["trajets"], loin["note_detail"]["trajets"] + 15)

    def test_prix_et_doublons(self):
        from sources.emails import _lire_carte
        for texte, prix in [("1,020€ /mois", 1020), ("Loyer 899,50 € CC", 899.5), ("1 450 € par mois", 1450),
                            ("810 € · 41 €/m²/mois", 810), ("Loyer : 1.195 € CC", 1195)]:
            self.assertEqual(_lire_carte({"cle": "x", "titre": texte}, texte)["prix"], prix, texte)
        a = {"source": "LocService", "prix": 859, "surface": 20, "code_postal": "92600"}
        self.assertIsNotNone(main.doublon(a, [{"source": "Lesiteimmo", "prix": 859, "surface": 20.4, "code_postal": "92600"}]))
        self.assertIsNone(main.doublon(a, [{"source": "Lesiteimmo", "prix": 859, "surface": 20, "code_postal": "92400"}]))

    def test_score(self):
        base = [{"ville": "Nanterre", "pieces": 2, "prix": 1000, "surface": 40, "distance_km": 0.3}] * 5
        ref = references(base, 30)
        normal = evaluer(dict(base[0]), self.conf, ref)
        affaire = evaluer({**base[0], "prix": 850}, self.conf, ref)
        arnaque = evaluer({**base[0], "prix": 500, "titre": "je suis à l'étranger"}, self.conf, ref)
        self.assertGreater(affaire["score"], normal["score"])
        self.assertIn("bonne_affaire", affaire["tags"])
        self.assertIn("suspect", arnaque["tags"])
        self.assertLessEqual(arnaque["score"], 15)
        # un studio n'est pas pénalisé par son €/m² plus élevé
        studio = evaluer({"ville": "Rueil", "pieces": 1, "prix": 30 * 1.15 * 25, "surface": 25, "distance_km": 0.3}, self.conf, ref)
        self.assertAlmostEqual(studio["ratio_marche"], 1.0, places=2)
        # commune plus tranquille et trajets plus courts => meilleure note
        calme = evaluer({**base[0], "securite": {"niveau": 5}, "trajets": {"SKEMA": 15}}, self.conf, ref)
        agite = evaluer({**base[0], "securite": {"niveau": 1}, "trajets": {"SKEMA": 45}}, self.conf, ref)
        self.assertGreater(calme["score"], agite["score"] + 30)
        securise = evaluer({**base[0], "titre": "résidence avec gardien"}, self.conf, ref)
        self.assertIn("securise", securise["tags"])

    def test_securite(self):
        s = self.conf["_securite"]
        self.assertEqual(len(s), 16)  # 15 communes du 92 + Paris
        self.assertEqual((s["92064"]["niveau"], s["92036"]["niveau"]), (5, 1))
        self.assertEqual(s["92064"]["annee"], "2025")
        # intrafamilial et cambriolages exclus
        self.assertAlmostEqual(s["92064"]["taux"], 2.2, places=1)  # violences seulement (0,3 + 0,4 du taux fictif)
        self.assertEqual(securite.insee_de("La Garenne-Colombes", "", self.conf), "92035")
        self.assertEqual(securite.insee_de("Colombes", "", self.conf), "92025")
        self.assertEqual(securite.insee_de("Rueil-Malmaison 92500", "", self.conf), "92063")

    def test_meuble_rdc(self):
        self.assertIs(main.est_meuble({"titre": "Studio meublé"}), True)
        self.assertIs(main.est_meuble({"titre": "T2 non meublé"}), False)
        self.assertIs(main.est_meuble({"titre": "Studio vide 20 m²", "meuble": True}), False)
        self.assertIsNone(main.est_meuble({"titre": "Studio", "description": "avec vide-ordures"}))
        self.assertTrue(main.est_rdc({"etage": 0}))
        self.assertTrue(main.est_rdc({"titre": "Studio en RDC"}))
        self.assertFalse(main.est_rdc({"titre": "rez-de-chaussée surélevé"}))

    def test_bout_en_bout(self):
        with tempfile.TemporaryDirectory() as d:
            data, site = os.path.join(d, "data"), os.path.join(d, "site")
            out = lancer("--dry-run", "--fixtures", "--data", data, "--site", site)
            self.assertIn("Veille logement démarrée", out)
            self.assertTrue(os.path.exists(os.path.join(site, "index.html")))
            with open(os.path.join(data, "annonces.json"), encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)["annonces"]), 8)

            # 2e passage : mémoire quasi vide -> 5 nouvelles + 1 baisse de prix
            with open(os.path.join(data, "deja_vues.json"), "w") as f:
                json.dump({"bienici:ag1-001": {"t": 9999999999, "p": 900}}, f)
            out = lancer("--dry-run", "--fixtures", "--data", data, "--site", site, "--maintenant", "2026-11-20T09:00")
            self.assertEqual(out.count("[DRY-RUN] notification"), 8)  # 7 nouvelles + 1 baisse
            self.assertIn("Baisse de prix", out)
            self.assertIn("900 € → <b>850 €</b>", out)
            self.assertIn("Sécurité", out)

            # 3e passage : rien de neuf ; à 20h05 -> bilan du jour, une seule fois
            out = lancer("--dry-run", "--fixtures", "--data", data, "--site", site, "--maintenant", "2026-11-20T20:05")
            self.assertNotIn("[DRY-RUN] notification", out)
            self.assertIn("Bilan du jour", out)
            out = lancer("--dry-run", "--fixtures", "--data", data, "--site", site, "--maintenant", "2026-11-20T20:25")
            self.assertNotIn("Bilan du jour", out)

            with open(os.path.join(site, "index.html"), encoding="utf-8") as f:
                html = f.read()
            self.assertNotIn("__DONNEES__", html)
            self.assertIn('"demo": false', html)
            self.assertIn('"lignes": ["J"]', html)


if __name__ == "__main__":
    unittest.main()
