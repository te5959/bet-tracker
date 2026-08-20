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

### Phase 4 — Matching image gagnante ↔ pari (prête, à valider en conditions réelles)

- lit les analyses `winning_bet` déjà routées, dont l'image n'est reliée à
  aucun pari (`bets.winning_image_id`) ;
- pour chacune, calcule un **score de similarité** avec chaque pari `PENDING`
  ouvert (section 9) :
  - équipes (40%, gère aussi l'ordre inversé équipe1/équipe2) ;
  - marché/sélection (25%) ;
  - cote (20%, tolérance numérique) ;
  - mise (15%, tolérance numérique) ;
- si le meilleur score ≥ 60% (seuil configurable) → le pari passe en `WON`,
  avec `winning_image_id` et `confirmed_payout` renseignés ;
- si aucun candidat ou score insuffisant → rien n'est forcé, l'image sera
  retentée au prochain passage (utile si le bon pari `PENDING` apparaît
  plus tard) ;
- **cas du pari posté deux fois** (signalé lors des tests réels) : en cas
  d'égalité de score entre plusieurs paris `PENDING` quasi-identiques, le
  plus **ancien** est choisi — testé explicitement
  (`tests/test_bet_matcher.py::test_duplicate_bet_tiebreak_oldest_wins`).

### Phase 5 — Expiration des paris (prête, à valider en conditions réelles)

- passe automatiquement en `LOST` tout pari `PENDING` détecté depuis plus
  de **24h** (délai configurable) sans confirmation de gain associée
  (règle 6, section 13) ;
- basé sur `detected_at` (heure de détection par le système), pas sur
  l'heure de l'événement extraite par l'IA — plus robuste, cette dernière
  étant souvent absente ou peu fiable ;
- **ne touche jamais** les paris `MANUAL_REVIEW` (ils restent en attente
  d'un regard humain) ni les paris déjà `WON` ;
- vérification peu fréquente (toutes les heures) : pas besoin de plus,
  le délai lui-même est de 24h.

Ce que le code **ne fait pas encore** :

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

## Automatiser tout le pipeline en continu

Une fois les Phases 1 à 4 validées manuellement, on peut faire tourner tout
le pipeline en tâche de fond en permanence, avec redémarrage automatique en
cas de crash — comme le fait déjà le listener Phase 1 :

```bash
bash deploy/install_pipeline_services.sh
```

Cela installe et démarre 4 nouveaux services (ou utilisez
`deploy/install_expire_service.sh` seul si les 3 premiers tournent déjà) :

| Service | Rôle | Fréquence |
|---|---|---|
| `bet-tracker-analyze` | Phase 2 : analyse IA des nouvelles images | vérifie toutes les 30s |
| `bet-tracker-route` | Phase 3 : création des paris | vérifie toutes les 30s |
| `bet-tracker-match` | Phase 4 : matching des gains | vérifie toutes les 30s |
| `bet-tracker-expire` | Phase 5 : expiration des paris trop anciens | vérifie 1x/heure |

Avec `bet-tracker` (Phase 1, déjà actif), le pipeline complet tourne alors
de bout en bout automatiquement : une image publiée dans le groupe est
capturée, analysée, transformée en pari, matchée à sa confirmation de gain
si elle existe, ou marquée perdue après 24h sans confirmation — sans
aucune intervention manuelle.

Vérifier que tout tourne :

```bash
systemctl status bet-tracker bet-tracker-analyze bet-tracker-route bet-tracker-match bet-tracker-expire
tail -f logs/pipeline.log
```

## Lancer le matching des gains (Phase 4)

Une fois des paris `PENDING` en base et des images `winning_bet` détectées :

```bash
# Traite jusqu'à 50 images gagnantes en attente, puis quitte
python match_pending.py

# Seuil de score personnalisé (défaut 0.60)
python match_pending.py --threshold 0.7

# Tourne en continu, vérifie toutes les 30 secondes
python match_pending.py --loop 30
```

Vérifier le résultat :

```bash
sqlite3 storage/bets.db "SELECT status, COUNT(*) FROM bets GROUP BY status;"
sqlite3 storage/bets.db "SELECT id, team_1, team_2, status, confirmed_payout FROM bets WHERE status='WON';"
```

## Lancer l'expiration des paris (Phase 5)

```bash
# Délai par défaut (24h)
python expire_pending.py

# Délai personnalisé
python expire_pending.py --hours 12

# Tourne en continu (vérifie 1x/heure)
python expire_pending.py --loop 3600
```

Vérifier le résultat :

```bash
sqlite3 storage/bets.db "SELECT status, COUNT(*) FROM bets GROUP BY status;"
sqlite3 storage/bets.db "SELECT id, team_1, team_2, detected_at FROM bets WHERE status='LOST';"
```

## Tests

```bash
python tests/test_db.py
python tests/test_image_analysis.py
python tests/test_bet_router.py
python tests/test_bet_matcher.py
python tests/test_bet_expiry.py
```

## Prochaine étape (Phase 6 — à valider avant de commencer)

Calculer automatiquement les statistiques (section 14) : total de paris,
gagnants/perdants, taux de réussite, résultats financiers, statistiques par
période — puis les rendre accessibles via un bot Telegram qui t'envoie un
résumé à la demande ou automatiquement chaque jour.
