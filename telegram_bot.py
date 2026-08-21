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

from telethon import TelegramClient, events, Button

from config import Settings
from db import init_db
from stats import (
    compute_statistics,
    format_stats_message,
    compute_bets_period_summary,
    format_period_summary_message,
    resolve_period,
)
from charts import (
    aggregate_bets_by_unit,
    period_code_to_since,
    render_chart,
    CHART_RENDERERS,
    PERIOD_CHOICES,
    UNIT_LABELS,
)
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

    def _main_menu_buttons():
        return [
            [Button.inline("📊 Statistiques", b"menu:stats")],
            [Button.inline("📋 Paris", b"menu:bets")],
            [Button.inline("📈 Graphiques", b"menu:graph")],
        ]

    def _back_to_menu_row():
        return [Button.inline("🏠 Menu", b"menu:root")]

    @client.on(events.NewMessage(pattern="/start"))
    async def start_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            return  # ignore silencieusement tout autre utilisateur
        await event.respond(
            "👋 Bot Bet Tracker connecté !\n\nQue veux-tu voir ?\n\n"
            "(Astuce : /stats, /bets et /graph fonctionnent aussi directement "
            "si tu préfères taper.)",
            buttons=_main_menu_buttons(),
        )

    @client.on(events.NewMessage(pattern="/stats"))
    async def stats_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            return
        stats = compute_statistics(settings.db_path)
        await event.respond(format_stats_message(stats), buttons=[_back_to_menu_row()])
        logger.info("Statistiques envoyées à la demande")

    @client.on(events.NewMessage(pattern=r"/bets(?:\s+(.+))?"))
    async def bets_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            return

        arg = event.pattern_match.group(1)
        since, until, label = resolve_period(arg)

        if arg and label is None:
            await event.respond(
                "Argument non reconnu. Utilise /bets, /bets today, /bets week, "
                "/bets month, ou /bets AAAA-MM-JJ (ex: /bets 2026-08-19)."
            )
            return

        limit = 30 if not arg else 200  # période précise : on ne limite pas artificiellement
        summary = compute_bets_period_summary(settings.db_path, since=since, until=until, limit=limit)
        message = format_period_summary_message(summary, label)
        await event.respond(message, parse_mode="markdown", buttons=[_back_to_menu_row()])
        logger.info("Tableau des paris envoyé à la demande (période: %s)", label)

    # État de navigation du menu /graph, en mémoire (un seul utilisateur autorisé).
    graph_navigation_state: dict[int, dict] = {}

    def _graph_type_buttons():
        return [
            [Button.inline(label, f"graph_type:{code}".encode())]
            for code, (_, label) in CHART_RENDERERS.items()
        ] + [_back_to_menu_row()]

    def _unit_buttons():
        return [
            [Button.inline("Jour", b"unit:day"), Button.inline("Semaine", b"unit:week"), Button.inline("Mois", b"unit:month")],
            [Button.inline("◀️ Retour", b"back:type"), *_back_to_menu_row()],
        ]

    def _period_buttons():
        row1 = [Button.inline(label, f"period:{code}".encode()) for code, (label, _) in list(PERIOD_CHOICES.items())[:3]]
        row2 = [Button.inline(label, f"period:{code}".encode()) for code, (label, _) in list(PERIOD_CHOICES.items())[3:]]
        return [row1, row2, [Button.inline("◀️ Retour", b"back:unit"), *_back_to_menu_row()]]

    def _bets_period_buttons():
        return [
            [Button.inline("Aujourd'hui", b"bets_period:today"), Button.inline("Semaine", b"bets_period:week")],
            [Button.inline("Mois", b"bets_period:month"), Button.inline("Tout", b"bets_period:all")],
            _back_to_menu_row(),
        ]

    @client.on(events.NewMessage(pattern="/graph"))
    async def graph_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            return
        graph_navigation_state[event.sender_id] = {}
        await event.respond("📈 Choisis un type de graphique :", buttons=_graph_type_buttons())

    @client.on(events.CallbackQuery)
    async def callback_handler(event):
        if event.sender_id != settings.telegram_bot_owner_id:
            await event.answer()
            return

        data = event.data.decode()

        if data in ("cancel", "menu:root"):
            graph_navigation_state.pop(event.sender_id, None)
            await event.edit("🏠 Menu principal — que veux-tu voir ?", buttons=_main_menu_buttons())
            await event.answer()
            return

        if data == "menu:stats":
            stats = compute_statistics(settings.db_path)
            await event.edit(format_stats_message(stats), buttons=[_back_to_menu_row()])
            await event.answer()
            logger.info("Statistiques envoyées via le menu")
            return

        if data == "menu:bets":
            await event.edit("📋 Choisis une période :", buttons=_bets_period_buttons())
            await event.answer()
            return

        if data.startswith("bets_period:"):
            code = data.split(":", 1)[1]
            if code == "all":
                since, until, label = None, None, "Tous les paris"
                limit = 30
            else:
                since, until, label = resolve_period(code)
                limit = 200
            summary = compute_bets_period_summary(settings.db_path, since=since, until=until, limit=limit)
            message = format_period_summary_message(summary, label)
            await event.edit(message, parse_mode="markdown", buttons=[_back_to_menu_row()])
            await event.answer()
            logger.info("Tableau des paris envoyé via le menu (période: %s)", label)
            return

        if data == "menu:graph":
            graph_navigation_state[event.sender_id] = {}
            await event.edit("📈 Choisis un type de graphique :", buttons=_graph_type_buttons())
            await event.answer()
            return

        if data.startswith("graph_type:"):
            graph_type = data.split(":", 1)[1]
            graph_navigation_state[event.sender_id] = {"type": graph_type}
            await event.edit("Choisis l'unité d'agrégation :", buttons=_unit_buttons())
            await event.answer()
            return

        if data.startswith("unit:"):
            unit = data.split(":", 1)[1]
            state = graph_navigation_state.setdefault(event.sender_id, {})
            state["unit"] = unit
            await event.edit("Choisis la période :", buttons=_period_buttons())
            await event.answer()
            return

        if data.startswith("period:"):
            period_code = data.split(":", 1)[1]
            state = graph_navigation_state.get(event.sender_id)

            if not state or "type" not in state or "unit" not in state:
                await event.answer("Session expirée, relance /graph ou le menu", alert=True)
                return

            since, period_label = period_code_to_since(period_code)
            buckets = aggregate_bets_by_unit(settings.db_path, state["unit"], since=since)
            image_buf = render_chart(state["type"], buckets, state["unit"])

            if image_buf is None:
                await event.answer("Aucune donnée pour cette période.", alert=True)
                return

            await event.answer()
            _, type_label = CHART_RENDERERS[state["type"]]
            caption = f"{type_label} — {UNIT_LABELS[state['unit']]} — {period_label}"
            await event.respond(file=image_buf, message=caption)
            await event.edit("✅ Graphique envoyé ci-dessus.", buttons=[_back_to_menu_row()])
            graph_navigation_state.pop(event.sender_id, None)
            logger.info("Graphique envoyé : %s", caption)
            return

        if data == "back:type":
            graph_navigation_state[event.sender_id] = {}
            await event.edit("📈 Choisis un type de graphique :", buttons=_graph_type_buttons())
            await event.answer()
            return

        if data == "back:unit":
            state = graph_navigation_state.get(event.sender_id, {})
            state.pop("unit", None)
            await event.edit("Choisis l'unité d'agrégation :", buttons=_unit_buttons())
            await event.answer()
            return

        await event.answer()

    asyncio.create_task(_daily_stats_loop(client, settings, logger))

    logger.info("Bot en écoute (/stats à la demande, résumé quotidien automatique)...")
    await client.run_until_disconnected()
