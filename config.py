"""
Configuration centralisée du projet.

Toutes les valeurs sensibles (API_ID, API_HASH, ...) viennent des variables
d'environnement / d'un fichier .env (voir .env.example).
"""

import os
from pathlib import Path
from dataclasses import dataclass

# Charge un fichier .env s'il existe (optionnel, pas de dépendance obligatoire)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv non installé : on suppose que les variables d'env
    # sont déjà exportées dans l'environnement du process.
    pass


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Variable d'environnement manquante: {name}. "
            f"Copiez .env.example vers .env et remplissez les valeurs."
        )
    return value


@dataclass(frozen=True)
class Settings:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_session_name: str
    telegram_target_group: str

    db_path: Path
    images_dir: Path
    log_file: Path

    # Phase 2
    anthropic_api_key: str
    anthropic_model: str

    # Phase 6 : bot Telegram (optionnel — seul run_bot.py en a besoin)
    telegram_bot_token: str | None
    telegram_bot_owner_id: int | None
    telegram_bot_session_name: str
    daily_stats_hour: int


def load_settings() -> Settings:
    bot_owner_id_raw = os.environ.get("TELEGRAM_BOT_OWNER_ID")
    return Settings(
        telegram_api_id=int(_require("TELEGRAM_API_ID")),
        telegram_api_hash=_require("TELEGRAM_API_HASH"),
        telegram_session_name=os.environ.get(
            "TELEGRAM_SESSION_NAME", "bet_tracker_session"
        ),
        telegram_target_group=_require("TELEGRAM_TARGET_GROUP"),
        db_path=Path(os.environ.get("DB_PATH", "./storage/bets.db")),
        images_dir=Path(os.environ.get("IMAGES_DIR", "./storage/images")),
        log_file=Path(os.environ.get("LOG_FILE", "./logs/pipeline.log")),
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get(
            "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"
        ),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        telegram_bot_owner_id=int(bot_owner_id_raw) if bot_owner_id_raw else None,
        telegram_bot_session_name=os.environ.get(
            "TELEGRAM_BOT_SESSION_NAME", "bet_tracker_bot_session"
        ),
        daily_stats_hour=int(os.environ.get("DAILY_STATS_HOUR", "8")),
    )
