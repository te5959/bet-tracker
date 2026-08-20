"""
Phase 4 — Script de matching par lot des images gagnantes.

Usage:
    python match_pending.py                # traite jusqu'à 50 images gagnantes
    python match_pending.py --limit 100
    python match_pending.py --loop 30       # tourne en continu
    python match_pending.py --threshold 0.7 # seuil de matching personnalisé
"""

import argparse
import time
from collections import Counter

from config import load_settings
from db import init_db, get_unmatched_winning_analyses, count_bets_by_status
from pipeline_logger import setup_logger
from bet_matcher import match_winning_analysis, MATCH_THRESHOLD


def process_batch(settings, logger, limit: int, threshold: float) -> int:
    analyses = get_unmatched_winning_analyses(settings.db_path, limit=limit)

    if not analyses:
        return 0

    logger.info("Matching de %s image(s) gagnante(s) en attente", len(analyses))

    outcomes = Counter()
    for analysis in analyses:
        outcome = match_winning_analysis(settings.db_path, analysis, logger, threshold)
        outcomes[outcome] += 1

    logger.info(
        "Matching terminé : %s pari(s) confirmé(s) WON, %s sans candidat, "
        "%s en correspondance insuffisante (à revoir)",
        outcomes.get("matched", 0),
        outcomes.get("no_candidates", 0),
        outcomes.get("low_confidence", 0),
    )

    return len(analyses)


def main():
    parser = argparse.ArgumentParser(description="Phase 4 - Matching image gagnante <-> pari")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--threshold",
        type=float,
        default=MATCH_THRESHOLD,
        help=f"Seuil de score pour valider un matching (défaut: {MATCH_THRESHOLD})",
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
            time.sleep(args.loop)  # on retente même si processed==0 : de nouveaux PENDING peuvent apparaître
    else:
        processed = process_batch(settings, logger, args.limit, args.threshold)
        if processed == 0:
            logger.info("Aucune image gagnante en attente de matching")

    logger.info("Répartition actuelle des paris : %s", count_bets_by_status(settings.db_path))


if __name__ == "__main__":
    main()
