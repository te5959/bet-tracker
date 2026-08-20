# Telegram Bet Tracker — Phase 1 + Phase 2

Système de suivi et d'analyse de paris publiés sous forme d'images dans un
groupe Telegram (voir cahier des charges complet : `knowledge.md` du projet).

## État actuel

### Phase 1 — Capture (validée en production)

- se connecte à **un seul** groupe/canal Telegram (avec un compte utilisateur,
  pas un bot) ;
- détecte chaque nouveau message contenant une **image** (photo ou document
  image/*) ;
- ignore totalement le texte des messages (règle 2) ;
- télécharge l'image dans `storage/images/<message_id>.jpg` ;
- empêche tout traitement en double d'un même message (anti-doublon) ;
- enregistre chaque image dans `storage/bets.db` (table `raw_images`,
  statut `CAPTURED`) ;
- journalise chaque étape dans `logs/pipeline.log` (et console).

### Phase 2 — Analyse IA Vision (prête, à valider en conditions réelles)

- lit les images `status='CAPTURED'` non encore analysées ;
- envoie chaque image à **Claude Haiku 4.5** (API vision, `tool use` pour
  forcer une réponse structurée conforme au schéma de la section 7) ;
- extrait : type d'image (`new_bet` / `winning_bet` / `unknown` / `ignored`),
  niveau de confiance, équipes, compétition, marché, cote, mise, gain
  potentiel, statut visible sur le ticket ;
- enregistre le résultat brut (JSON complet) dans la table `image_analysis`,
  pour audit et réanalyse future (règle 8) ;
- marque l'image `ANALYZED` (succès) ou `ANALYSIS_FAILED` (erreur réseau/API —
  l'image reste visible pour un nouveau traitement, elle n'est jamais perdue) ;
- script séparé du listener temps réel (`analyze_pending.py`), pour pouvoir
  être testé et validé indépendamment.

**Important** : la Phase 2 s'arrête à l'extraction + classification brute. La
**décision métier** (créer un pari en base `bets`, matcher une confirmation de
gain à un pari existant) est la Phase 3/4 — pas encore développée, pour valider
d'abord la fiabilité de l'extraction sur des images réelles du groupe.

### Phase 3 — Routage / création des paris (prête, à valider en conditions réelles)

- lit les analyses IA réussies pas encore routées (`image_analysis.routed_at IS NULL`) ;
- applique la règle de décision (section 8) :
  - `new_bet` + confiance ≥ seuil (0.75 par défaut) → crée un pari dans `bets`, statut `PENDING` ;
  - `new_bet` + confiance < seuil → crée un pari, statut `MANUAL_REVIEW` (visible, pas perdu) ;
  - `winning_bet` → **aucune création** : laissé pour la Phase 4 (matching avec un pari existant) ;
  - `unknown` / `ignored` → aucune création ;
- marque chaque analyse comme routée (`routed_at`), pour ne jamais la retraiter deux fois ;
- script séparé (`route_pending.py`), indépendant de l'analyse IA et du listener.

Ce que le code **ne fait pas encore** :

- aucun matching entre un `winning_bet` et un pari `PENDING` existant (Phase 4) ;
- aucune détection de perte par délai (Phase 5) ;
- aucune statistique (Phase 6) ;
- **aucune automatisation de paris** (hors scope V1, section 21).

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Remplir `.env` :

- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` : à créer sur
  https://my.telegram.org/apps
- `TELEGRAM_TARGET_GROUP` : username du groupe (sans @) ou son ID numérique
- `ANTHROPIC_API_KEY` : à créer sur https://console.anthropic.com (API Keys)
- `ANTHROPIC_MODEL` : peut rester à `claude-haiku-4-5-20251001` (par défaut)

## Premier lancement

```bash
python main.py
```

Lors du tout premier lancement, Telethon vous demandera de vous
authentifier (numéro de téléphone + code reçu par Telegram). Une session
est ensuite sauvegardée localement (`<TELEGRAM_SESSION_NAME>.session`), pas
besoin de se reconnecter à chaque fois.

Pour traiter aussi l'historique récent au démarrage (par exemple après un
redémarrage) :

```bash
python main.py --backfill 50
```

## Lancer l'analyse IA (Phase 2)

Une fois des images capturées (Phase 1 en marche depuis un moment) :

```bash
# Traite jusqu'à 20 images en attente, puis quitte
python analyze_pending.py

# Traite jusqu'à 100 images
python analyze_pending.py --limit 100

# Tourne en continu, vérifie toutes les 30 secondes s'il y a de nouvelles images
python analyze_pending.py --loop 30
```

Pour l'usage courant sur le serveur, `--loop 30` est recommandé, en plus du
listener Phase 1 déjà actif — ce sont deux process indépendants.

## Coût estimé (Phase 2)

Avec Claude Haiku 4.5 (~$1/$5 par million de tokens) et environ 40 images/jour,
le coût est de l'ordre de quelques euros par mois. À surveiller sur
https://console.anthropic.com une fois en production.

## Lancer le routage vers les paris (Phase 3)

Une fois des images analysées (Phase 2) :

```bash
# Traite jusqu'à 50 analyses en attente, puis quitte
python route_pending.py

# Seuil de confiance personnalisé (défaut 0.75)
python route_pending.py --threshold 0.8

# Tourne en continu, vérifie toutes les 30 secondes
python route_pending.py --loop 30
```

Vérifier le résultat :

```bash
sqlite3 storage/bets.db "SELECT status, COUNT(*) FROM bets GROUP BY status;"
sqlite3 storage/bets.db "SELECT * FROM bets WHERE status='MANUAL_REVIEW';"
```

## Tests

```bash
python tests/test_db.py
python tests/test_image_analysis.py
python tests/test_bet_router.py
```

## Prochaine étape (Phase 4 — à valider avant de commencer)

Relier chaque image `winning_bet` (actuellement laissée de côté par la
Phase 3) à un pari `PENDING` existant dans `bets`, via un score de
correspondance (équipes, marché, cote, montant...), conformément à la
section 9 du cahier des charges. Cas particulier à bien gérer : le même
pari peut être placé deux fois par le tipster (mentionné par l'utilisateur),
donc plusieurs paris `PENDING` peuvent être candidats pour une même image
gagnante — il faudra une règle de départage claire.
