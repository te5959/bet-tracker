"""
Point d'entrée — Phase 1 uniquement.

Usage:
    python main.py                # écoute en temps réel
    python main.py --backfill 50  # traite les 50 derniers messages puis quitte
"""

import argparse
import asyncio

from config import load_settings
from telegram_listener import run_listener, backfill_recent


def main():
    parser = argparse.ArgumentParser(description="Telegram Bet Tracker - Phase 1")
    parser.add_argument(
        "--backfill",
        type=int,
        default=0,
        help="Nombre de messages récents à traiter avant de quitter (0 = désactivé)",
    )
    args = parser.parse_args()

    settings = load_settings()

    if args.backfill > 0:
        asyncio.run(backfill_recent(settings, limit=args.backfill))
    else:
        asyncio.run(run_listener(settings))


if __name__ == "__main__":
    main()
