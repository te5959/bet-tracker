"""
Phase 3 — Script de routage par lot des analyses IA vers la table `bets`.

Usage:
    python route_pending.py                # traite jusqu'à 50 analyses
    python route_pending.py --limit 200
    python route_pending.py --loop 30       # tourne en continu
    python route_pending.py --threshold 0.8 # seuil de confiance personnalisé

Séparé de analyze_pending.py (Phase 2) pour pouvoir valider chaque étape
indépendamment, comme demandé.
"""

import argparse
import time
from collections import Counter

from config import load_settings
from db import init_db, get_unrouted_analyses, count_bets_by_status
from pipeline_logger import setup_logger
from bet_router import route_analysis, DEFAULT_CONFIDENCE_THRESHOLD


def process_batch(settings, logger, limit: int, threshold: float) -> int:
    analyses = get_unrouted_analyses(settings.db_path, limit=limit)

    if not analyses:
        return 0

    logger.info("Routage de %s analyse(s) en attente", len(analyses))

    outcomes = Counter()
    for analysis in analyses:
        outcome = route_analysis(settings.db_path, analysis, threshold, logger)
        outcomes[outcome] += 1

    logger.info(
        "Routage terminé : %s pari(s) PENDING créé(s), %s en MANUAL_REVIEW, "
        "%s winning_bet en attente de matching, %s unknown, %s ignored",
        outcomes.get("created_pending", 0),
        outcomes.get("created_manual_review", 0),
        outcomes.get("skipped_winning_bet", 0),
        outcomes.get("skipped_unknown", 0),
        outcomes.get("skipped_ignored", 0),
    )

    return len(analyses)


def main():
    parser = argparse.ArgumentParser(description="Phase 3 - Routage des analyses vers bets")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_CONFIDENCE_THRESHOLD,
        help=f"Seuil de confiance pour PENDING vs MANUAL_REVIEW (défaut: {DEFAULT_CONFIDENCE_THRESHOLD})",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="Si > 0, tourne en continu avec ce nombre de secondes entre chaque vérification",
    )
    args = parser.parse_args()

    settings = load_settings()
    init_db(settings.db_path)
    logger = setup_logger(settings.log_file)

    if args.loop > 0:
        logger.info("Mode continu activé (vérification toutes les %ss)", args.loop)
        while True:
            processed = process_batch(settings, logger, args.limit, args.threshold)
            if processed == 0:
                time.sleep(args.loop)
    else:
        processed = process_batch(settings, logger, args.limit, args.threshold)
        if processed == 0:
            logger.info("Aucune analyse en attente de routage")

    logger.info("Répartition actuelle des paris : %s", count_bets_by_status(settings.db_path))


if __name__ == "__main__":
    main()
