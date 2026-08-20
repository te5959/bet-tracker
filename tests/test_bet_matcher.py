"""
Tests du matching Phase 4, indépendants de Telegram et du réseau.
Valide : matching correct, absence de candidat, score insuffisant, et
le départage en cas de paris quasi-identiques (même pari posté 2 fois).
"""

import sys
import json
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import (
    init_db,
    insert_raw_image,
    save_image_analysis,
    create_bet,
    get_unmatched_winning_analyses,
    get_connection,
)
from bet_matcher import score_match, find_best_match, match_winning_analysis


def _silent_logger():
    logger = logging.getLogger("test_bet_matcher")
    logger.addHandler(logging.NullHandler())
    return logger


def test_score_match_basic():
    winning = {"team_1": "PSG", "team_2": "Lyon", "market": "Over 0.5", "odds": 1.85, "stake": 100}
    good_candidate = {"team_1": "PSG", "team_2": "Lyon", "market": "Over 0.5", "odds": 1.85, "stake": 100}
    bad_candidate = {"team_1": "Real Madrid", "team_2": "Barcelona", "market": "BTTS", "odds": 3.2, "stake": 20}

    good_score = score_match(winning, good_candidate)
    bad_score = score_match(winning, bad_candidate)

    assert good_score > 0.9, f"score attendu élevé, obtenu {good_score}"
    assert bad_score < 0.3, f"score attendu faible, obtenu {bad_score}"
    print("OK - test_score_match_basic")


def test_score_match_swapped_teams():
    """Les équipes peuvent être dans un ordre différent entre les 2 captures."""
    winning = {"team_1": "Lyon", "team_2": "PSG", "market": "Over 0.5", "odds": 1.85}
    candidate = {"team_1": "PSG", "team_2": "Lyon", "market": "Over 0.5", "odds": 1.85}

    score = score_match(winning, candidate)
    assert score > 0.9, f"le score doit rester élevé malgré l'inversion, obtenu {score}"
    print("OK - test_score_match_swapped_teams")


def test_full_matching_flow():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        logger = _silent_logger()

        insert_raw_image(db_path, telegram_message_id=1, telegram_date="2026-08-20T10:00:00", file_path="/tmp/1.jpg")
        insert_raw_image(db_path, telegram_message_id=2, telegram_date="2026-08-20T12:00:00", file_path="/tmp/2.jpg")

        bet_id = create_bet(
            db_path, telegram_message_id=None, original_image_id=1,
            team_1="PSG", team_2="Lyon", competition="Ligue 1",
            event_date=None, event_time=None,
            market="Over 0.5 Goals", selection="Over 0.5", odds=1.85, stake=100,
            potential_return=185, status="PENDING", confidence=0.9,
        )

        save_image_analysis(
            db_path, raw_image_id=2, image_type="winning_bet", confidence=0.95,
            extracted_json=json.dumps({
                "team_1": "PSG", "team_2": "Lyon", "market": "Over 0.5 Goals",
                "odds": 1.85, "confirmed_payout": 185,
            }),
            model_used="test",
        )
        with get_connection(db_path) as conn:
            conn.execute("UPDATE image_analysis SET routed_at = datetime('now')")
            conn.commit()

        pending = get_unmatched_winning_analyses(db_path)
        assert len(pending) == 1

        outcome = match_winning_analysis(db_path, pending[0], logger)
        assert outcome == "matched"

        with get_connection(db_path) as conn:
            bet = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
            assert bet["status"] == "WON"
            assert bet["winning_image_id"] == 2
            assert bet["confirmed_payout"] == 185

        # Un 2e passage ne doit plus trouver cette image (déjà matchée)
        assert get_unmatched_winning_analyses(db_path) == []

    print("OK - test_full_matching_flow")


def test_duplicate_bet_tiebreak_oldest_wins():
    """Cas signalé par l'utilisateur : le même pari posté 2 fois. Les 2
    paris PENDING sont quasi-identiques -> le plus ANCIEN doit être choisi."""
    older = {"id": 1, "team_1": "PSG", "team_2": "Lyon", "market": "Over 0.5", "selection": "Over 0.5", "odds": 1.85, "stake": 100}
    newer = {"id": 2, "team_1": "PSG", "team_2": "Lyon", "market": "Over 0.5", "selection": "Over 0.5", "odds": 1.85, "stake": 100}
    winning = {"team_1": "PSG", "team_2": "Lyon", "market": "Over 0.5", "selection": "Over 0.5", "odds": 1.85}

    # candidates fournis triés du plus ancien au plus récent, comme le fait get_open_bets
    best, score = find_best_match(winning, [older, newer])

    assert best["id"] == 1, "le pari le plus ancien doit être choisi en cas d'égalité"
    print("OK - test_duplicate_bet_tiebreak_oldest_wins")


def test_no_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        logger = _silent_logger()

        insert_raw_image(db_path, telegram_message_id=1, telegram_date="2026-08-20T10:00:00", file_path="/tmp/1.jpg")
        save_image_analysis(
            db_path, raw_image_id=1, image_type="winning_bet", confidence=0.9,
            extracted_json=json.dumps({"team_1": "PSG", "team_2": "Lyon"}),
            model_used="test",
        )
        with get_connection(db_path) as conn:
            conn.execute("UPDATE image_analysis SET routed_at = datetime('now')")
            conn.commit()

        pending = get_unmatched_winning_analyses(db_path)
        outcome = match_winning_analysis(db_path, pending[0], logger)
        assert outcome == "no_candidates"

    print("OK - test_no_candidates")


if __name__ == "__main__":
    test_score_match_basic()
    test_score_match_swapped_teams()
    test_full_matching_flow()
    test_duplicate_bet_tiebreak_oldest_wins()
    test_no_candidates()
