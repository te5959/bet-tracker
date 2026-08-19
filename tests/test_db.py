"""
Tests de la couche DB, indépendants de Telegram.
Valide : création du schéma, insertion, anti-doublon (section 12).
"""

import sys
import sqlite3
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import init_db, is_message_processed, insert_raw_image, count_raw_images


def test_schema_and_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        assert count_raw_images(db_path) == 0
        assert is_message_processed(db_path, 111) is False

        insert_raw_image(db_path, telegram_message_id=111, telegram_date="2026-08-19T10:00:00", file_path="/tmp/111.jpg")

        assert is_message_processed(db_path, 111) is True
        assert count_raw_images(db_path) == 1

        # Un deuxième insert du même message_id doit échouer (contrainte UNIQUE)
        try:
            insert_raw_image(db_path, telegram_message_id=111, telegram_date="2026-08-19T10:05:00", file_path="/tmp/111b.jpg")
            raised = False
        except sqlite3.IntegrityError:
            raised = True
        assert raised, "L'insertion d'un message_id dupliqué aurait dû lever IntegrityError"

        # Un nouveau message différent doit s'insérer normalement
        insert_raw_image(db_path, telegram_message_id=222, telegram_date="2026-08-19T11:00:00", file_path="/tmp/222.jpg")
        assert count_raw_images(db_path) == 2

    print("OK - test_schema_and_dedup")


if __name__ == "__main__":
    test_schema_and_dedup()
