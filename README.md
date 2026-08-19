# Telegram Bet Tracker — Phase 1

Système de suivi et d'analyse de paris publiés sous forme d'images dans un
groupe Telegram (voir cahier des charges complet : `knowledge.md` du projet).

## État actuel : Phase 1 uniquement

Ce que fait le code aujourd'hui :

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

Ce que le code **ne fait pas encore** (phases suivantes, non commencées) :

- aucune analyse IA / vision des images (Phase 2) ;
- aucune classification NEW_BET / WINNING_BET / IGNORED (Phase 3) ;
- aucun matching entre pari et confirmation de gain (Phase 4) ;
- aucune détection de perte par délai (Phase 5) ;
- aucune statistique (Phase 6) ;
- **aucune automatisation de paris** (hors scope V1, section 21).

La table `bets` existe déjà dans le schéma (pour figer la structure de
données dès maintenant), mais elle reste vide tant que la Phase 2 n'est pas
développée.

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
- Le reste peut rester par défaut.

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

## Tests

Un test indépendant de Telegram valide le schéma DB et l'anti-doublon :

```bash
python tests/test_db.py
```

## Prochaine étape (Phase 2 — à valider avant de commencer)

Envoyer chaque image `status='CAPTURED'` à un modèle de vision IA pour en
extraire les données structurées du ticket (équipes, cote, mise, gain
potentiel...), conformément à la section 7 du cahier des charges.

Point à trancher ensemble avant de coder :
- quel modèle/API de vision utiliser (ex: Claude API) et comment gérer la clé
  API de façon sécurisée dans ce projet.
