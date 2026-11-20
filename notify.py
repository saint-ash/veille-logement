"""Notifications : Telegram (photo + boutons) et/ou ntfy."""
import html
import json
import os

import requests

from geo import lien_trajet

NOMS_PIECES = {1: "T1", 2: "T2", 3: "T3"}


def e(x):
    return html.escape(str(x), quote=False)


def euros(x):
    return f"{x:,.0f}".replace(",", " ") + " €"


def entete(a):
    morceaux = [NOMS_PIECES.get(a.get("pieces"), "Logement")]
    if a.get("surface"):
        morceaux.append(f"{a['surface']:.0f} m²")
    if a.get("prix"):
        morceaux.append(euros(a["prix"]))
    return " · ".join(morceaux)


def formater(a, baisse_depuis=None):
    tags = a.get("tags", [])
    if "suspect" in tags:
        pastille = "⚠️"
    elif "bonne_affaire" in tags:
        pastille = "🔥"
    else:
        pastille = "🏠"
    lignes = []
    if baisse_depuis:
        lignes.append(f"📉 <b>Baisse de prix</b> : {euros(baisse_depuis)} → <b>{euros(a['prix'])}</b>")
    note = f"  <i>{a['score']}/100</i>" if a.get("score") is not None else ""
    lignes.append(f"{pastille} <b>{e(entete(a))}</b>{note}")
    lieu = " ".join(x for x in (a.get("ville"), a.get("code_postal")) if x)
    if a.get("gare"):
        approx = "≈" if a.get("position_approx") else ""
        ligs = "/".join(a.get("lignes", []))
        lignes.append(f"🚆 {approx}{a['minutes']} min à pied de <b>{e(a['gare'])}</b>{f' ({ligs})' if ligs else ''} · {e(lieu)}")
    elif lieu:
        lignes.append(f"📍 {e(lieu)}")
    if a.get("prix_m2"):
        txt = f"💶 {a['prix_m2']:.1f} €/m²".replace(".", ",")
        if a.get("ratio_marche"):
            ecart = round((a["ratio_marche"] - 1) * 100)
            txt += f" · {abs(ecart)} % {'sous le' if ecart < 0 else 'au-dessus du'} prix du coin" if ecart else " · dans le prix du coin"
        lignes.append(txt)
    trajets = {k: v for k, v in (a.get("trajets") or {}).items() if v is not None}
    if trajets:
        lignes.append("🕒 " + " · ".join(f"{e(k)} {v} min" for k, v in trajets.items()))
    sec = a.get("securite")
    if sec:
        lignes.append(f"🛡️ Sécurité {'●' * sec['niveau']}{'○' * (5 - sec['niveau'])} "
                      f"({'Paris, moyenne de la ville' if sec.get('code') == '75056' else e(a.get('ville') or '')} · "
                      f"{sec['rang']}ᵉ sur {sec['sur']} communes de Paris et petite couronne)")
    if a.get("annonceur") == "particulier":
        lignes.append("👤 Particulier · pas de frais d'agence")
    elif a.get("annonceur") == "agence":
        frais = a.get("frais_agence") or (15 * a["surface"] if a.get("surface") else None)
        lignes.append(f"🏢 Agence · frais {'≈ ' + euros(frais) if a.get('frais_agence') else '≤ ' + euros(frais) + ' (plafond légal)' if frais else 'à vérifier'}")
    if a.get("coup_de_coeur"):
        lignes.append(f"💛 Coup de cœur : {e(a.get('ville') or '')}")
    if "securise" in tags:
        lignes.append("🔐 Résidence sécurisée (gardien, digicode…)")
    if "suspect" in tags:
        lignes.append("⚠️ <b>Prudence</b> : prix anormalement bas ou formulation typique d'arnaque. "
                      "Ne paie jamais rien avant d'avoir visité.")
    lignes.append(f"<i>{e(a.get('titre', ''))[:140]}</i>")
    lignes.append(f"via {e(a['source'])}")
    return "\n".join(lignes)


def boutons(a, lieux, url_site):
    ligne1 = [{"text": "📄 Voir l'annonce", "url": a["url"]}]
    if a.get("lat") and a.get("gare_lat"):
        ligne1.append({"text": "🚶 Trajet gare", "url": lien_trajet((a["lat"], a["lon"]), (a["gare_lat"], a["gare_lon"]))})
    ligne2 = []
    if a.get("lat"):
        for l in lieux[:2]:
            ligne2.append({"text": f"🕒 {l['nom']}", "url": lien_trajet((a["lat"], a["lon"]), l["adresse"], "transit")})
    ligne3 = []
    if url_site:
        ligne3.append({"text": "📋 Mon tableau de bord", "url": url_site})
    return {"inline_keyboard": [l for l in (ligne1, ligne2, ligne3) if l]}


class Notifier:
    def __init__(self, conf, dry_run=False):
        self.conf = conf
        self.dry_run = dry_run
        self.tg = conf.get("telegram", True)
        self.ntfy = conf.get("ntfy", False)
        self.token = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.topic = os.environ.get("NTFY_TOPIC", "")
        self.url_site = os.environ.get("DASHBOARD_URL", "")
        self.lieux = []
        if not dry_run and self.tg and not (self.token and self.chat):
            raise SystemExit("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID manquants (voir README, étape 1).")

    def envoyer_annonce(self, a, baisse_depuis=None):
        texte = formater(a, baisse_depuis)
        clavier = boutons(a, self.lieux, self.url_site)
        if self.dry_run:
            print("---- [DRY-RUN] notification ----\n" + texte)
            print("   boutons :", " | ".join(b["text"] for l in clavier["inline_keyboard"] for b in l), "\n")
            return
        if self.tg:
            payload = {"chat_id": self.chat, "parse_mode": "HTML", "reply_markup": json.dumps(clavier)}
            envoye = False
            if a.get("photo") and len(texte) <= 1024:
                envoye = self._tg("sendPhoto", {**payload, "photo": a["photo"], "caption": texte})
            if not envoye:
                self._tg("sendMessage", {**payload, "text": texte, "disable_web_page_preview": "true"})
        if self.ntfy and self.topic:
            requests.post("https://ntfy.sh/", timeout=15, json={
                "topic": self.topic, "title": entete(a) + (f" – {a['ville']}" if a.get("ville") else ""),
                "message": f"{a.get('score', '?')}/100 · {a.get('gare') or a['source']}",
                "click": a["url"], "tags": ["house"]})

    def envoyer_texte(self, texte, url_bouton=None):
        if self.dry_run:
            print("---- [DRY-RUN] message ----\n" + texte + "\n")
            return
        if self.tg:
            payload = {"chat_id": self.chat, "text": texte, "parse_mode": "HTML", "disable_web_page_preview": "true"}
            if url_bouton:
                payload["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": "📋 Ouvrir le tableau de bord", "url": url_bouton}]]})
            self._tg("sendMessage", payload)
        if self.ntfy and self.topic:
            requests.post("https://ntfy.sh/", json={"topic": self.topic, "message": html.unescape(texte)}, timeout=15)

    def _tg(self, methode, payload):
        try:
            r = requests.post(f"https://api.telegram.org/bot{self.token}/{methode}", data=payload, timeout=20)
        except requests.RequestException as ex:
            print(f"[telegram] {methode} : {ex}")
            return False
        if not r.ok:
            print(f"[telegram] {methode} -> {r.status_code} {r.text[:200]}")
        return r.ok
