"""
Phase 5 — Script d'expiration des paris perdus (logique hybride).

Usage:
    python expire_pending.py                          # 5h après le match, sinon 24h après détection
    python expire_pending.py --event-hours 6 --fallback-hours 24
    python expire_pending.py --loop 1800               # tourne en continu (vérifie toutes les 30 min)
"""

import argparse
import time

from config import load_settings
from db import init_db, count_bets_by_status
from pipeline_logger import setup_logger
from bet_expiry import expire_stale_bets, EVENT_EXPIRY_HOURS, FALLBACK_EXPIRY_HOURS


def main():
    parser = argparse.ArgumentParser(description="Phase 5 - Expiration des paris PENDING (hybride)")
    parser.add_argument(
        "--event-hours",
        type=int,
        default=EVENT_EXPIRY_HOURS,
        help=f"Heures après le début du match avant de considérer un pari perdu (défaut: {EVENT_EXPIRY_HOURS})",
    )
    parser.add_argument(
        "--fallback-hours",
        type=int,
        default=FALLBACK_EXPIRY_HOURS,
        help=f"Heures après détection si l'heure du match est inexploitable (défaut: {FALLBACK_EXPIRY_HOURS})",
    )
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="Si > 0, tourne en continu avec ce nombre de secondes entre chaque vérification. "
             "Avec un délai basé sur l'heure du match (quelques heures), une vérification "
             "toutes les 15-30 minutes a plus de sens que l'ancien intervalle d'1h.",
    )
    args = parser.parse_args()

    settings = load_settings()
    init_db(settings.db_path)
    logger = setup_logger(settings.log_file)

    if args.loop > 0:
        logger.info("Mode continu activé (vérification toutes les %ss)", args.loop)
        while True:
            count = expire_stale_bets(settings.db_path, logger, args.event_hours, args.fallback_hours)
            if count:
                logger.info("%s pari(s) expiré(s) en LOST", count)
            time.sleep(args.loop)
    else:
        count = expire_stale_bets(settings.db_path, logger, args.event_hours, args.fallback_hours)
        if count:
            logger.info("%s pari(s) expiré(s) en LOST", count)
        else:
            logger.info("Aucun pari à expirer pour le moment")

    logger.info("Répartition actuelle des paris : %s", count_bets_by_status(settings.db_path))


if __name__ == "__main__":
    main()
