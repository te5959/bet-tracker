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

### Phase 5 — Expiration des paris (logique hybride, prête, à valider en conditions réelles)

- **Priorité 1** : si `event_date`/`event_time` (extraits par l'IA depuis le
  ticket) sont présents et exploitables, un pari `PENDING` est considéré
  perdu **5h après le début du match** (bien plus précis que l'ancien délai
  fixe) ;
- **Priorité 2 (filet de sécurité)** : si la date/heure du match est
  absente ou imparsable, on retombe sur l'ancienne règle — **24h après
  `detected_at`** ;
- le parsing des dates est tolérant (`python-dateutil`) pour gérer les
  formats hétérogènes présents dans les données déjà extraites avant le
  resserrement du format demandé à l'IA ;
- **limite connue et assumée** : l'heure du ticket peut être dans un
  fuseau horaire différent du serveur ; le délai de 5h absorbe en partie ce
  risque mais un décalage important pourrait provoquer une expiration
  légèrement prématurée ou tardive ;
- **ne touche jamais** les paris `MANUAL_REVIEW` ni les paris déjà `WON` ;
- vérification toutes les 15 minutes (plus fréquente qu'avant, cohérent
  avec un délai principal de quelques heures).

### Phase 6 — Statistiques + Bot Telegram (prête, à valider en conditions réelles)

- calcule les statistiques de la section 14, enrichies :
  - comptages (total, gagnés, perdus, en attente, à vérifier), taux de réussite ;
  - **deux calculs de bénéfice** : normal (paris résolus uniquement) et
    **conservateur** (les paris encore `PENDING` sont en plus comptés comme
    entièrement perdus — scénario prudent) ;
  - ROI (%) pour les deux scénarios ;
  - cote moyenne, mise moyenne, meilleur gain, plus grosse perte ;
  - répartition par période (jour / 7 jours / mois) ;
- un **bot Telegram séparé** (via @BotFather, pas le compte utilisateur de
  la Phase 1) répond à :
  - `/stats` — résumé complet ci-dessus, à la demande ;
  - `/bets` — tableau détaillé des paris avec totaux (gains encaissés,
    bénéfice normal et conservateur), filtrable par période :
    - `/bets` — derniers paris (30 max) ;
    - `/bets today` — paris d'aujourd'hui ;
    - `/bets week` — 7 derniers jours ;
    - `/bets month` — ce mois-ci ;
    - `/bets 2026-08-19` — un jour précis ;
  - `/graph` — menu interactif à boutons (aucune commande à taper) :
    1. choix du type de graphique (Bénéfice cumulé / Taux de réussite /
       Volume de paris / Mise vs Gains) ;
    2. choix de l'unité (Jour / Semaine / Mois) ;
    3. choix de la période (1 jour → 1 an) ;
    → génère et envoie un graphique PNG (matplotlib) ;
  - envoi **automatique quotidien** du résumé `/stats` à une heure
    configurable (`DAILY_STATS_HOUR`, 8h par défaut) ;
- le bot **ignore tout message** venant d'un autre utilisateur que
  `TELEGRAM_BOT_OWNER_ID` — usage strictement personnel.

C'est la dernière brique de la V1 (section 22-23 du cahier des charges) :
observer → comprendre → mesurer → analyser, sans aucune automatisation de
paris (hors scope, section 21).

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
| `bet-tracker-expire` | Phase 5 : expiration des paris (5h après match, 24h fallback) | vérifie toutes les 15 min |

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
# Délais par défaut (5h après le match, 24h après détection en filet de sécurité)
python expire_pending.py

# Délais personnalisés
python expire_pending.py --event-hours 6 --fallback-hours 24

# Tourne en continu (vérifie toutes les 15 min)
python expire_pending.py --loop 900
```

Vérifier le résultat :

```bash
sqlite3 storage/bets.db "SELECT status, COUNT(*) FROM bets GROUP BY status;"
sqlite3 storage/bets.db "SELECT id, team_1, team_2, detected_at FROM bets WHERE status='LOST';"
```

## Configurer et lancer le bot Telegram (Phase 6)

1. Créer un bot via `@BotFather` sur Telegram (`/newbot`), récupérer le token.
2. Récupérer ton ID Telegram numérique personnel (ex: via `@userinfobot`).
3. Envoyer `/start` à ton nouveau bot (obligatoire — un bot ne peut pas
   initier une conversation sur Telegram).
4. Remplir dans `.env` : `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_OWNER_ID`,
   `DAILY_STATS_HOUR` (optionnel, 8 par défaut).
5. Lancer :

```bash
python run_bot.py
```

Puis, sur Telegram, envoie `/stats` à ton bot pour tester, `/bets`,
`/bets today`, `/bets week`, `/bets month` ou `/bets AAAA-MM-JJ` pour le
détail par période, et `/graph` pour le menu interactif de graphiques.

## Tests

```bash
python tests/test_db.py
python tests/test_image_analysis.py
python tests/test_bet_router.py
python tests/test_bet_matcher.py
python tests/test_bet_expiry.py
python tests/test_stats.py
python tests/test_charts.py
```

## Automatiser le bot en continu

```bash
bash deploy/install_bot_service.sh
```

Avec ça, les **6 services** (Phase 1 à 6) tournent en continu :

```bash
systemctl status bet-tracker bet-tracker-analyze bet-tracker-route bet-tracker-match bet-tracker-expire bet-tracker-bot
```

## V1 complète

Toutes les phases du cahier des charges sont maintenant en place (sections
18 et 22-23) : capture, lecture, classification, matching, expiration, et
statistiques accessibles via Telegram. Comme précisé section 24, la
priorité a été la fiabilité de la lecture et du suivi — toute évolution
future (analyse historique avancée, automatisation des mises) reste
volontairement hors de cette V1 et ne doit être envisagée qu'après une
période de validation en conditions réelles sur des données propres.
