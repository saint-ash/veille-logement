# Ma recherche d'appart : le robot et le tableau de bord

T1/T2 **meublés**, **900 € max** charges comprises, **près d'une gare**, à :
Courbevoie · Puteaux · La Garenne-Colombes · Colombes · Suresnes · Neuilly-sur-Seine · Neuilly-Plaisance · Levallois · Clichy · Paris (sauf 18e et 19e) · Bry-sur-Marne · Val de Fontenay · Eaubonne · Nanterre, Rueil, Asnières, Bois-Colombes, Saint-Cloud (seulement près d'une gare).
**Particuliers et agences** : toutes les annonces arrivent au même endroit.

## Ce que ça fait

Toutes les 10 minutes, de 6 h à minuit, le robot :

1. récupère les nouvelles annonces sur **Bien'ici** (des milliers d'agences), secteur par secteur ;
2. lit tes **alertes mail** de PAP, Leboncoin, SeLoger, LocService, Studapart, Lodgis, etc. (particuliers et agences) ;
3. garde uniquement les **meublés**, sans **rez-de-chaussée**, sans colocation, dans ton budget et tes villes ;
4. calcule pour chacune :
   - la **station la plus proche** (toutes les gares d'Île-de-France : métro, RER, Transilien) et le temps à pied,
   - le **temps de trajet en transports vers SKEMA et Porte Maillot** (calculateur officiel IDFM),
   - un **niveau de sécurité de la commune** (statistiques officielles de la délinquance),
   - une **note sur 100** = prix (30) + sécurité (20) + trajets (20) + gare (20) + surface (10) + bonus coup de cœur / particulier,
   - des badges : bonne affaire, baisse de prix, particulier sans frais ou frais d'agence, résidence sécurisée, **arnaque probable** ;
5. t'envoie chaque nouvelle annonce sur **Telegram** (photo et boutons *Voir l'annonce*, *Trajet gare*, *Trajet SKEMA*, *Trajet Porte Maillot*), plus un **bilan à 20 h** ;
6. met à jour **ton site**, qui s'installe comme une appli sur ton téléphone :
   - **Annonces** : filtres (T1/T2, particuliers ou agences, budget, ville, recherche), carrousel de photos, « Pourquoi cette note ? » ;
   - **Carte** : toutes les annonces, avec SKEMA et Porte Maillot ;
   - **Tri rapide** : une annonce à la fois (← pas pour moi · ↑ favori · → à contacter) ;
   - **Candidatures** : tableau À contacter → Contactée → Visite → Dossier envoyé, avec une note perso par annonce ;
   - **Message type** : copié en un clic avec le titre, la ville, le prix et le lien vers ton dossier.

---

## Installation (environ 25 min, une seule fois)

### 1. Le bot Telegram (5 min)
1. Dans Telegram, cherche **BotFather** (badge bleu) → *Démarrer* → `/newbot`.
2. Nom : `Veille Logement`. Identifiant : un nom qui finit par `bot`, par exemple `douaa_logement_bot`.
3. Copie le **token** qu'il te donne (`7123456789:AAH…`).
4. Ouvre ton bot → *Démarrer* → envoie « salut ».
5. Dans un navigateur, ouvre `https://api.telegram.org/botTON_TOKEN/getUpdates`. Le nombre après `"chat":{"id":` est ton **chat id**.

### 2. Le compte GitHub et le dépôt (5 min)
1. Crée un compte sur **github.com**.
2. **+ → New repository** · nom `veille-logement`.
   - **Public** : le plus simple et entièrement gratuit. Tes codes restent secrets, mais ta config (villes, budget, noms de tes lieux) est visible.
   - **Privé** : ta config reste cachée. Il faut alors GitHub Pro, gratuit pour les étudiants via le *GitHub Student Developer Pack* (à demander avec ton adresse SKEMA), et passer le robot à toutes les 15 min.
3. Clique **uploading an existing file**, puis glisse tout le contenu du dossier dézippé (y compris les dossiers `sources`, `dashboard`, `tests` et `data`) → *Commit changes*.

### 3. Les codes secrets (3 min)
*Settings → Secrets and variables → Actions → New repository secret* :

| Nom | Valeur | |
|---|---|---|
| `TELEGRAM_TOKEN` | le token de BotFather | obligatoire |
| `TELEGRAM_CHAT_ID` | ton chat id | obligatoire |
| `PRIM_API_KEY` | clé gratuite Île-de-France Mobilités (voir étape 7) | pour les temps de trajet |
| `IMAP_USER` / `IMAP_PASSWORD` | Gmail dédiée + mot de passe d'application (voir étape 6) | pour les particuliers |

### 4. Le robot (2 min)
1. Onglet **Actions** → *set up a workflow yourself*.
2. Efface tout, colle le contenu de `WORKFLOW-a-coller.yml` → *Commit changes*.
3. **Actions → Veille logement → Run workflow**. Une minute plus tard, tu reçois « Veille logement démarrée » sur Telegram.

### 5. Le site (2 min)
1. *Settings → Pages* → **Deploy from a branch** → **main** / **/docs** → *Save*.
2. Une à deux minutes plus tard, ton site est en ligne : `https://TON-PSEUDO.github.io/veille-logement/`.
3. Sur ton téléphone, ouvre le lien → *Partager* → **Sur l'écran d'accueil**.

### Fréquence garantie avec cron-job.org (conseillé)
Les lancements programmés de GitHub sont parfois retardés de plusieurs heures. Pour un passage vraiment toutes les 10 minutes :
1. GitHub → photo de profil → *Settings* → *Developer settings* → *Personal access tokens* → **Fine-grained tokens** → *Generate new token*. Nom `veille cron`, expiration 90 jours, *Only select repositories* → `veille-logement`, permission **Actions : Read and write** → *Generate*. Copie le jeton.
2. Sur **cron-job.org** (gratuit), crée un compte → *Create cronjob* :
   - URL : `https://api.github.com/repos/saint-ash/veille-logement/actions/workflows/veille.yml/dispatches`
   - Planification : toutes les 10 minutes (de 6 h à 23 h 59).
   - Onglet *Advanced* : méthode **POST** ; en-têtes `Authorization: Bearer TON_JETON`, `Accept: application/vnd.github+json` ; corps `{"ref":"main"}`.
3. *Test run* : la réponse doit être **204**. C'est tout.

### 6. Les particuliers : centraliser toutes tes alertes (10 min, conseillé)
Leboncoin, SeLoger et PAP bloquent les robots. On passe donc par leurs propres alertes mail, qui sont faites pour ça.
1. Crée une Gmail dédiée (exemple : `douaa.appart@gmail.com`), active la validation en 2 étapes, puis crée un **mot de passe d'application** (Compte Google → Sécurité).
2. Sur chaque site, fais ta recherche (location, meublé, T1-T2, 900 €, tes villes) → **Créer une alerte** vers cette adresse, fréquence « immédiate » si proposée :
   - **Particuliers** : PAP, Leboncoin, LocService
   - **Étudiants** : Studapart (partenaire de SKEMA), ImmoJeune, Lokaviz (Crous)
   - **Meublés Paris** : Lodgis, Paris Attitude
   - **Agences** : SeLoger, Logic-Immo
3. Ajoute les secrets `IMAP_USER` et `IMAP_PASSWORD`, puis dans `config.toml` → `[sources.emails]` → `actif = true`.

### 7. Les temps de trajet réels (5 min, conseillé)
1. Crée un compte gratuit sur **prim.iledefrance-mobilites.fr**.
2. Dans ton espace, génère une **clé API** pour le « Calculateur Île-de-France Mobilités ».
3. Ajoute-la dans le secret `PRIM_API_KEY`.

Sans cette clé, chaque annonce a quand même un bouton « Trajet » vers Google Maps.

---

## Réglages (`config.toml`)

| Paramètre | Effet |
|---|---|
| `loyer_max`, `surface_min`, `meuble`, `exclure_rdc` | budget charges comprises, surface, meublé obligatoire, pas de rez-de-chaussée |
| `distance_max_km` | 0,6 ≈ 10 min à pied · 0,8 ≈ 13 min · 1,0 ≈ 16 min |
| `[[geo.villes]]` | une ville par bloc : `zone = "commune"` (toute la ville) ou `"gare"` (seulement près d'une gare), `coup_de_coeur = true` |
| `paris_arrondissements_exclus` | `[18, 19]` |
| `modes` | `METRO`, `RER`, `TRAIN` (+ `TRAMWAY` si tu veux) |
| `[[lieux]]` | SKEMA et Porte Maillot : tu peux en ajouter (salle de sport, famille…) |
| `[securite] niveau_min` | 3 pour ignorer les communes les moins tranquilles |
| `[[securite.zones_a_eviter]]` | une rue ou un quartier précis à exclure (lat, lon, rayon) |
| `score_min` | ne recevoir que les annonces au-dessus d'une note |

**Sécurité** : statistiques officielles de la délinquance enregistrée (SSMSI, ministère de l'Intérieur) : vols violents, violences physiques hors famille, violences sexuelles et vols contre les personnes, pour 1 000 habitants. Chaque commune est classée de 1 à 5 par rapport aux communes de Paris et de la petite couronne. C'est une moyenne sur toute la commune, pas rue par rue : ajoute tes propres zones à éviter.

## Dépannage

| Symptôme | Solution |
|---|---|
| Rien sur Telegram | *Actions* → dernier passage → lis le journal. « TELEGRAM_TOKEN manquants » = secret mal nommé. |
| `[bienici] HTTP 403` | Bien'ici bloque parfois les serveurs de GitHub : lance le robot depuis ton PC (`pip install -r requirements.txt`, copie `secrets.env.exemple` en `secrets.env`, puis `python main.py` toutes les 15 min dans le Planificateur de tâches). |
| `[gares] … indisponibles` | Les gares de secours de la config prennent le relais. |
| Pas de temps de trajet | Vérifie le secret `PRIM_API_KEY`. |
| Trop de notifs | Monte `score_min` (exemple : 55) ou baisse `distance_max_km`. |
| Le site ne s'affiche pas | Il n'existe qu'après le premier passage : relance *Run workflow*, puis refais l'étape 5. |

Tests sans réseau : `python -m unittest discover tests` · site de démo : `python demo.py`.

## Bon usage
Pour ta recherche perso uniquement : quelques requêtes toutes les 10 min, comme si tu rafraîchissais la page. Ne republie pas les annonces. **Ne paie jamais rien avant d'avoir visité.**
