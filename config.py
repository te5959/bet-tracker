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


def load_settings() -> Settings:
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
    )
