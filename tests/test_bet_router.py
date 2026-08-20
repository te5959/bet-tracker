"""
Tests du routage Phase 3, indépendants de Telegram et de l'API Claude.
Valide : création de pari PENDING, MANUAL_REVIEW selon seuil, non-création
pour winning_bet/unknown/ignored, et marquage routed_at.
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
    get_unrouted_analyses,
    count_bets_by_status,
    get_connection,
)
from bet_router import route_analysis


def _silent_logger():
    logger = logging.getLogger("test_bet_router")
    logger.addHandler(logging.NullHandler())
    return logger


def test_routing_rules():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        logger = _silent_logger()

        # 4 images capturées, une par cas de figure
        for i in range(1, 5):
            insert_raw_image(db_path, telegram_message_id=i, telegram_date="2026-08-20T10:00:00", file_path=f"/tmp/{i}.jpg")

        # 1: new_bet confiance haute -> PENDING
        save_image_analysis(db_path, raw_image_id=1, image_type="new_bet", confidence=0.9,
                             extracted_json=json.dumps({"team_1": "A", "team_2": "B", "odds": 1.85}),
                             model_used="test")
        # 2: new_bet confiance basse -> MANUAL_REVIEW
        save_image_analysis(db_path, raw_image_id=2, image_type="new_bet", confidence=0.5,
                             extracted_json=json.dumps({"team_1": "C", "team_2": "D"}),
                             model_used="test")
        # 3: winning_bet -> pas de création
        save_image_analysis(db_path, raw_image_id=3, image_type="winning_bet", confidence=0.95,
                             extracted_json=json.dumps({"team_1": "A", "team_2": "B"}),
                             model_used="test")
        # 4: ignored -> pas de création
        save_image_analysis(db_path, raw_image_id=4, image_type="ignored", confidence=0.95,
                             extracted_json=json.dumps({}),
                             model_used="test")

        pending_analyses = get_unrouted_analyses(db_path, limit=10)
        assert len(pending_analyses) == 4

        outcomes = []
        for analysis in pending_analyses:
            outcomes.append(route_analysis(db_path, analysis, threshold=0.75, logger=logger))

        assert outcomes == [
            "created_pending",
            "created_manual_review",
            "skipped_winning_bet",
            "skipped_ignored",
        ]

        # Plus rien à router
        assert get_unrouted_analyses(db_path, limit=10) == []

        status_counts = count_bets_by_status(db_path)
        assert status_counts.get("PENDING") == 1
        assert status_counts.get("MANUAL_REVIEW") == 1
        assert sum(status_counts.values()) == 2  # winning_bet et ignored n'ont rien créé

        with get_connection(db_path) as conn:
            bet = conn.execute("SELECT * FROM bets WHERE status='PENDING'").fetchone()
            assert bet["team_1"] == "A"
            assert bet["team_2"] == "B"
            assert bet["odds"] == 1.85

    print("OK - test_routing_rules")


if __name__ == "__main__":
    test_routing_rules()
