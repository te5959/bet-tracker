"""
Phase 1 — Telegram Listener

Rôle (et UNIQUEMENT ce rôle en Phase 1, cf. section 18 du cahier des
charges) :

    1. Se connecter à l'unique groupe/canal Telegram configuré.
    2. Détecter chaque nouveau message contenant une image.
    3. Vérifier qu'il n'a pas déjà été traité (anti-doublon).
    4. Télécharger l'image dans storage/images/.
    5. Enregistrer une ligne dans raw_images (statut CAPTURED).
    6. Logger chaque étape.

Pas d'analyse IA, pas de classification, pas de matching ici : ça viendra
dans les modules des phases suivantes, qui liront simplement les lignes
`raw_images` avec status='CAPTURED'.

Le texte du message n'est jamais lu ni stocké (règle 2 du cahier des
charges) — seule l'image est utilisée.
"""

import asyncio
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import Message

from config import Settings
from db import init_db, is_message_processed, insert_raw_image, count_raw_images
from pipeline_logger import setup_logger


def _message_has_image(message: Message) -> bool:
    """Détecte une image au sens large : photo, ou document image/*.
    On ignore volontairement les vidéos, GIFs, stickers, fichiers autres."""
    if message.photo:
        return True
    if message.document and message.document.mime_type:
        return message.document.mime_type.startswith("image/")
    return False


async def _handle_new_image_message(
    message: Message,
    settings: Settings,
    logger,
) -> None:
    message_id = message.id

    logger.info("Nouvelle image détectée (message_id=%s)", message_id)

    # --- Anti-doublon (section 11 étape 1, section 12) ---
    if is_message_processed(settings.db_path, message_id):
        logger.info("Message %s déjà traité, ignoré", message_id)
        return

    # --- Téléchargement (section 11 étapes 2-4) ---
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    file_path = settings.images_dir / f"{message_id}.jpg"

    try:
        await message.download_media(file=str(file_path))
    except Exception as exc:
        logger.info(
            "Échec du téléchargement pour le message %s : %s", message_id, exc
        )
        return

    logger.info("Image téléchargée : %s", file_path)

    # --- Enregistrement en base (statut CAPTURED, en attente d'analyse) ---
    telegram_date = message.date.isoformat() if message.date else None
    try:
        raw_image_id = insert_raw_image(
            settings.db_path,
            telegram_message_id=message_id,
            telegram_date=telegram_date,
            file_path=str(file_path),
        )
    except Exception as exc:
        # Race condition possible (contrainte UNIQUE) : on log et on continue
        logger.info(
            "Message %s déjà enregistré entre-temps (%s)", message_id, exc
        )
        return

    logger.info(
        "Image enregistrée en base (raw_image_id=%s, status=CAPTURED)",
        raw_image_id,
    )


async def run_listener(settings: Settings) -> None:
    init_db(settings.db_path)
    logger = setup_logger(settings.log_file)

    logger.info(
        "Démarrage du listener sur le groupe : %s", settings.telegram_target_group
    )
    logger.info("Images déjà en base : %s", count_raw_images(settings.db_path))

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    target_entity = await _resolve_target(client, settings)

    @client.on(events.NewMessage(chats=target_entity))
    async def handler(event: events.NewMessage.Event):
        message: Message = event.message
        if not _message_has_image(message):
            return
        await _handle_new_image_message(message, settings, logger)

    logger.info("Listener actif, en attente de nouvelles publications...")
    await client.run_until_disconnected()


async def _resolve_target(client: TelegramClient, settings: Settings):
    """Résout le groupe cible (username ou id numérique) en entité Telethon."""
    await client.start()

    target = settings.telegram_target_group
    try:
        # Autorise un id numérique (ex: -100123456789)
        target = int(target)
    except ValueError:
        pass

    entity = await client.get_entity(target)
    return entity


async def backfill_recent(settings: Settings, limit: int = 50) -> None:
    """
    Utilitaire optionnel : traite les `limit` derniers messages du groupe
    au lancement, pour ne pas dépendre uniquement des événements temps
    réel (utile après un redémarrage). N'écrase jamais un message déjà
    traité grâce à l'anti-doublon.
    """
    init_db(settings.db_path)
    logger = setup_logger(settings.log_file)

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    target_entity = await _resolve_target(client, settings)

    logger.info("Backfill des %s derniers messages...", limit)
    async for message in client.iter_messages(target_entity, limit=limit):
        if _message_has_image(message):
            await _handle_new_image_message(message, settings, logger)

    await client.disconnect()
