"""
Phase 6 — Bot Telegram

Deux fonctionnalités, dans un seul process :

    1. À la demande : le propriétaire envoie /stats au bot, il répond
       immédiatement avec le résumé des statistiques actuelles.
    2. Automatique : une fois par jour, à l'heure configurée
       (DAILY_STATS_HOUR, 8h par défaut), le bot envoie le résumé sans
       qu'on ait à le demander.

Sécurité : le bot ignore tout message venant d'un utilisateur autre que
TELEGRAM_BOT_OWNER_ID. Ce n'est pas un bot public, personne d'autre ne
doit pouvoir consulter tes statistiques ou même savoir qu'il existe.

Ce bot est un client Telegram SÉPARÉ du compte utilisateur qui lit le
groupe (Phase 1) — un vrai bot Telegram (token via @BotFather), pas le
même compte. Nécessite que le propriétaire ait déjà envoyé /start au bot
au moins une fois (règle Telegram : un bot ne peut pas initier une
conversation).
"""

import asyncio
from datetime import datetime, timedelta

from telethon import TelegramClient, events

from config import Settings
from db import init_db, get_recent_bets
from stats import compute_statistics, format_stats_message, format_bets_table
from pipeline_logger import setup_logger


def _seconds_until_next_run(hour: int) -> float:
    now = datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _daily_stats_loop(client: TelegramClient, settings: Settings, logger) -> None:
    while True:
        wait_seconds = _seconds_until_next_run(settings.daily_stats_hour)
        logger.info(
            "Prochain envoi automatique des stats dans %.0f minutes (%sh, heure serveur)",
            wait_seconds / 60, settings.daily_stats_hour,
        )
        await asyncio.sleep(wait_seconds)

        try:
            stats = compute_statistics(settings.db_path)
            message = format_stats_message(stats)
            await client.send_message(settings.telegram_bot_owner_id, message)
            logger.info("Résumé quotidien des statistiques envoyé")
        except Exception as exc:
            logger.info("Échec de l'envoi du résumé quotidien : %s", exc)

        # petite marge pour ne pas redéclencher immédiatement si l'horloge
        # système bouge légèrement
        await asyncio.sleep(5)


async def run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN manquant dans .env. Créez un bot via @BotFather "
            "et ajoutez le token dans .env avant de lancer run_bot.py."
        )
    if not settings.telegram_bot_owner_id:
        raise RuntimeError(
            "TELEGRAM_BOT_OWNER_ID manquant dans .env. Récupérez votre ID Telegram "
            "(ex: via @userinfobot) et ajoutez-le dans .env."
        )

    init_db(settings.db_path)
    logger = setup_logger(settings.log_file)

    client = TelegramClient(
        settings.telegram_bot_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.start(bot_token=settings.telegram_bot_token)
    logger.info("Bot Telegram démarré")

    @client.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            return  # ignore silencieusement tout autre utilisateur
        await event.respond(
            "👋 Bot Bet Tracker connecté !\n\n"
            "/stats — résumé complet des statistiques\n"
            "/bets — tableau détaillé des derniers paris\n\n"
            f"Un résumé automatique t'est aussi envoyé chaque jour à {settings.daily_stats_hour}h."
        )

    @client.on(events.NewMessage(pattern="/stats"))
    async def stats_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            return
        stats = compute_statistics(settings.db_path)
        await event.respond(format_stats_message(stats))
        logger.info("Statistiques envoyées à la demande")

    @client.on(events.NewMessage(pattern="/bets"))
    async def bets_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            return
        recent_bets = get_recent_bets(settings.db_path, limit=30)
        table = format_bets_table(recent_bets)
        await event.respond(table, parse_mode="markdown")
        logger.info("Tableau des paris envoyé à la demande")

    asyncio.create_task(_daily_stats_loop(client, settings, logger))

    logger.info("Bot en écoute (/stats à la demande, résumé quotidien automatique)...")
    await client.run_until_disconnected()
