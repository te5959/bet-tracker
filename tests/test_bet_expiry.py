"""
Tests de l'expiration Phase 5 (logique hybride), indépendants du réseau.
Valide : parsing event_date/event_time, priorité event > fallback,
non-expiration des paris récents/valides, MANUAL_REVIEW/WON jamais touchés.
"""

import sys
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import init_db, insert_raw_image, create_bet, get_connection
from bet_expiry import expire_stale_bets, parse_event_datetime, compute_deadline


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


def _set_event_datetime(db_path, bet_id, event_date, event_time):
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE bets SET event_date = ?, event_time = ? WHERE id = ?",
            (event_date, event_time, bet_id),
        )
        conn.commit()


def _make_bet(db_path, image_id, status="PENDING"):
    return create_bet(
        db_path, telegram_message_id=None, original_image_id=image_id,
        team_1="A", team_2="B", competition=None, event_date=None, event_time=None,
        market=None, selection=None, odds=1.9, stake=100, potential_return=190,
        status=status, confidence=0.9,
    )


def test_parse_event_datetime():
    # cas nominal : format demandé à l'IA
    dt = parse_event_datetime("2026-08-19", "21:45")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 8 and dt.day == 19
    assert dt.hour == 21 and dt.minute == 45

    # format libre, dateutil doit s'en sortir (tolérance sur données anciennes)
    dt2 = parse_event_datetime("19 Aug 2026", "9:45 PM")
    assert dt2 is not None
    assert dt2.hour == 21

    # un des deux champs manquant -> None (pas de valeur par défaut trompeuse)
    assert parse_event_datetime("2026-08-19", None) is None
    assert parse_event_datetime(None, "21:45") is None
    assert parse_event_datetime(None, None) is None

    # texte imparsable -> None, pas de crash
    assert parse_event_datetime("n'importe quoi", "aussi") is None

    print("OK - test_parse_event_datetime")


def test_compute_deadline_priority():
    """Si event_date/event_time sont exploitables, ils priment sur detected_at."""
    past_event = (datetime.now() - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M")
    event_date, event_time = past_event.split(" ")

    bet = {
        "event_date": event_date,
        "event_time": event_time,
        "detected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # détecté à l'instant
    }
    deadline, method = compute_deadline(bet, event_hours=5, fallback_hours=24)
    assert method == "event"
    # deadline = event + 5h, doit être dans le passé (match il y a 10h + 5h < maintenant)
    assert deadline < datetime.now()

    # sans event_date/event_time -> fallback sur detected_at
    bet_no_event = {
        "event_date": None,
        "event_time": None,
        "detected_at": (datetime.now() - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S"),
    }
    deadline2, method2 = compute_deadline(bet_no_event, event_hours=5, fallback_hours=24)
    assert method2 == "fallback"
    assert deadline2 < datetime.now()

    print("OK - test_compute_deadline_priority")


def test_expire_stale_bets_event_based():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        logger = _silent_logger()

        for i in range(1, 6):
            insert_raw_image(db_path, telegram_message_id=i, telegram_date="2026-08-19T10:00:00", file_path=f"/tmp/{i}.jpg")

        # 1) match commencé il y a 10h, avec event_date/time -> expire (10h > 5h)
        bet_old_match = _make_bet(db_path, 1)
        old_match_dt = datetime.now() - timedelta(hours=10)
        _set_event_datetime(db_path, bet_old_match, old_match_dt.strftime("%Y-%m-%d"), old_match_dt.strftime("%H:%M"))
        _set_detected_at(db_path, bet_old_match, 10)  # détecté au même moment que le match, peu importe ici

        # 2) match commencé il y a 1h seulement -> ne doit PAS expirer (1h < 5h)
        bet_recent_match = _make_bet(db_path, 2)
        recent_match_dt = datetime.now() - timedelta(hours=1)
        _set_event_datetime(db_path, bet_recent_match, recent_match_dt.strftime("%Y-%m-%d"), recent_match_dt.strftime("%H:%M"))

        # 3) pas d'event_date/time, détecté il y a 25h -> expire via fallback (25h > 24h)
        bet_fallback_expired = _make_bet(db_path, 3)
        _set_detected_at(db_path, bet_fallback_expired, 25)

        # 4) pas d'event_date/time, détecté il y a 2h -> ne doit PAS expirer
        bet_fallback_recent = _make_bet(db_path, 4)
        _set_detected_at(db_path, bet_fallback_recent, 2)

        # 5) MANUAL_REVIEW très ancien -> jamais touché
        bet_manual = _make_bet(db_path, 5, status="MANUAL_REVIEW")
        _set_detected_at(db_path, bet_manual, 100)

        expired_count = expire_stale_bets(db_path, logger)
        assert expired_count == 2

        with get_connection(db_path) as conn:
            def status_of(bet_id):
                return conn.execute("SELECT status FROM bets WHERE id = ?", (bet_id,)).fetchone()["status"]

            assert status_of(bet_old_match) == "LOST"
            assert status_of(bet_recent_match) == "PENDING"
            assert status_of(bet_fallback_expired) == "LOST"
            assert status_of(bet_fallback_recent) == "PENDING"
            assert status_of(bet_manual) == "MANUAL_REVIEW"

        # 2e passage : plus rien à expirer
        assert expire_stale_bets(db_path, logger) == 0

    print("OK - test_expire_stale_bets_event_based")


if __name__ == "__main__":
    test_parse_event_datetime()
    test_compute_deadline_priority()
    test_expire_stale_bets_event_based()
