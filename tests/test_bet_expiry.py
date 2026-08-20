"""
Tests de l'expiration Phase 5, indépendants de Telegram et du réseau.
Valide : un pari PENDING trop ancien passe en LOST, un pari récent ne
bouge pas, et les paris WON/MANUAL_REVIEW ne sont jamais touchés.
"""

import sys
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import init_db, insert_raw_image, create_bet, get_connection
from bet_expiry import expire_stale_bets


def _silent_logger():
    logger = logging.getLogger("test_bet_expiry")
    logger.addHandler(logging.NullHandler())
    return logger


def _set_detected_at(db_path, bet_id, hours_ago):
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE bets SET detected_at = datetime('now', ?) WHERE id = ?",
            (f"-{hours_ago} hours", bet_id),
        )
        conn.commit()


def test_expiry_rules():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        logger = _silent_logger()

        insert_raw_image(db_path, telegram_message_id=1, telegram_date="2026-08-19T10:00:00", file_path="/tmp/1.jpg")
        insert_raw_image(db_path, telegram_message_id=2, telegram_date="2026-08-19T10:00:00", file_path="/tmp/2.jpg")
        insert_raw_image(db_path, telegram_message_id=3, telegram_date="2026-08-19T10:00:00", file_path="/tmp/3.jpg")
        insert_raw_image(db_path, telegram_message_id=4, telegram_date="2026-08-19T10:00:00", file_path="/tmp/4.jpg")

        # Pari PENDING vieux de 25h -> doit expirer en LOST
        old_pending = create_bet(
            db_path, telegram_message_id=None, original_image_id=1,
            team_1="A", team_2="B", competition=None, event_date=None, event_time=None,
            market=None, selection=None, odds=1.9, stake=100, potential_return=190,
            status="PENDING", confidence=0.9,
        )
        _set_detected_at(db_path, old_pending, 25)

        # Pari PENDING vieux de 2h seulement -> doit rester PENDING
        recent_pending = create_bet(
            db_path, telegram_message_id=None, original_image_id=2,
            team_1="C", team_2="D", competition=None, event_date=None, event_time=None,
            market=None, selection=None, odds=1.9, stake=100, potential_return=190,
            status="PENDING", confidence=0.9,
        )
        _set_detected_at(db_path, recent_pending, 2)

        # Pari MANUAL_REVIEW vieux de 48h -> ne doit JAMAIS être auto-expiré
        old_manual_review = create_bet(
            db_path, telegram_message_id=None, original_image_id=3,
            team_1="E", team_2="F", competition=None, event_date=None, event_time=None,
            market=None, selection=None, odds=1.9, stake=100, potential_return=190,
            status="MANUAL_REVIEW", confidence=0.5,
        )
        _set_detected_at(db_path, old_manual_review, 48)

        # Pari déjà WON, vieux de 48h -> ne doit jamais être touché
        old_won = create_bet(
            db_path, telegram_message_id=None, original_image_id=4,
            team_1="G", team_2="H", competition=None, event_date=None, event_time=None,
            market=None, selection=None, odds=1.9, stake=100, potential_return=190,
            status="WON", confidence=0.9,
        )
        _set_detected_at(db_path, old_won, 48)

        expired_count = expire_stale_bets(db_path, delay_hours=24, logger=logger)
        assert expired_count == 1

        with get_connection(db_path) as conn:
            def status_of(bet_id):
                return conn.execute("SELECT status FROM bets WHERE id = ?", (bet_id,)).fetchone()["status"]

            assert status_of(old_pending) == "LOST"
            assert status_of(recent_pending) == "PENDING"
            assert status_of(old_manual_review) == "MANUAL_REVIEW"
            assert status_of(old_won) == "WON"

        # Un 2e passage ne doit plus rien trouver à expirer
        assert expire_stale_bets(db_path, delay_hours=24, logger=logger) == 0

    print("OK - test_expiry_rules")


if __name__ == "__main__":
    test_expiry_rules()
