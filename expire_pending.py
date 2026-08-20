"""
Phase 5 — Script d'expiration des paris perdus par délai.

Usage:
    python expire_pending.py                  # délai par défaut (24h)
    python expire_pending.py --hours 12
    python expire_pending.py --loop 3600       # tourne en continu (vérifie 1x/heure)
"""

import argparse
import time

from config import load_settings
from db import init_db, count_bets_by_status
from pipeline_logger import setup_logger
from bet_expiry import expire_stale_bets, DEFAULT_EXPIRY_HOURS


def main():
    parser = argparse.ArgumentParser(description="Phase 5 - Expiration des paris PENDING trop anciens")
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_EXPIRY_HOURS,
        help=f"Délai en heures avant de considérer un pari PENDING comme perdu (défaut: {DEFAULT_EXPIRY_HOURS})",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="Si > 0, tourne en continu avec ce nombre de secondes entre chaque vérification "
             "(pas besoin d'un intervalle court : une vérification par heure suffit largement)",
    )
    args = parser.parse_args()

    settings = load_settings()
    init_db(settings.db_path)
    logger = setup_logger(settings.log_file)

    if args.loop > 0:
        logger.info("Mode continu activé (vérification toutes les %ss)", args.loop)
        while True:
            count = expire_stale_bets(settings.db_path, args.hours, logger)
            if count:
                logger.info("%s pari(s) expiré(s) en LOST", count)
            time.sleep(args.loop)
    else:
        count = expire_stale_bets(settings.db_path, args.hours, logger)
        if count:
            logger.info("%s pari(s) expiré(s) en LOST", count)
        else:
            logger.info("Aucun pari à expirer pour le moment")

    logger.info("Répartition actuelle des paris : %s", count_bets_by_status(settings.db_path))


if __name__ == "__main__":
    main()
