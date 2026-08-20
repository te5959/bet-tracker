"""
Point d'entrée du bot Telegram (Phase 6).

Usage:
    python run_bot.py
"""

import asyncio

from config import load_settings
from telegram_bot import run_bot


def main():
    settings = load_settings()
    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
