"""
Tests de la couche DB pour la Phase 2, indépendants du réseau et de l'API Claude.
Valide : création de la table image_analysis, insertion, mise à jour de statut.
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import (
    init_db,
    insert_raw_image,
    get_captured_images,
    save_image_analysis,
    get_connection,
)


def test_image_analysis_flow():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        # Simule 2 images capturées par la Phase 1
        insert_raw_image(db_path, telegram_message_id=1, telegram_date="2026-08-19T10:00:00", file_path="/tmp/1.jpg")
        insert_raw_image(db_path, telegram_message_id=2, telegram_date="2026-08-19T10:05:00", file_path="/tmp/2.jpg")

        pending = get_captured_images(db_path)
        assert len(pending) == 2, f"attendu 2 images en attente, trouvé {len(pending)}"

        # Simule une analyse réussie sur la première image
        fake_result = {"image_type": "new_bet", "confidence": 0.91, "team_1": "Team A"}
        save_image_analysis(
            db_path,
            raw_image_id=pending[0]["id"],
            image_type="new_bet",
            confidence=0.91,
            extracted_json=json.dumps(fake_result),
            model_used="claude-haiku-4-5-20251001",
        )

        # Simule un échec sur la deuxième image
        save_image_analysis(
            db_path,
            raw_image_id=pending[1]["id"],
            image_type=None,
            confidence=None,
            extracted_json="{}",
            model_used="claude-haiku-4-5-20251001",
            error="Timeout réseau simulé",
        )

        # Plus aucune image ne doit être encore CAPTURED
        remaining = get_captured_images(db_path)
        assert len(remaining) == 0, "les 2 images auraient dû changer de statut"

        with get_connection(db_path) as conn:
            row1 = conn.execute(
                "SELECT status FROM raw_images WHERE id = ?", (pending[0]["id"],)
            ).fetchone()
            row2 = conn.execute(
                "SELECT status FROM raw_images WHERE id = ?", (pending[1]["id"],)
            ).fetchone()
            assert row1["status"] == "ANALYZED"
            assert row2["status"] == "ANALYSIS_FAILED"

            analysis_count = conn.execute(
                "SELECT COUNT(*) AS c FROM image_analysis"
            ).fetchone()["c"]
            assert analysis_count == 2

    print("OK - test_image_analysis_flow")


if __name__ == "__main__":
    test_image_analysis_flow()
