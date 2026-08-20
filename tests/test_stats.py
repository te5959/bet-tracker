"""
Tests du moteur de statistiques Phase 6, indépendants de Telegram.
Valide : comptages par statut, taux de réussite, calculs financiers.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import init_db, insert_raw_image, create_bet, mark_bet_won, get_connection
from stats import compute_statistics, format_stats_message


def _make_pending(db_path, image_id, stake, potential_return, odds=1.9):
    return create_bet(
        db_path, telegram_message_id=None, original_image_id=image_id,
        team_1="A", team_2="B", competition=None, event_date=None, event_time=None,
        market=None, selection=None, odds=odds, stake=stake, potential_return=potential_return,
        status="PENDING", confidence=0.9,
    )


def test_compute_statistics():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        for i in range(1, 6):
            insert_raw_image(db_path, telegram_message_id=i, telegram_date="2026-08-20T10:00:00", file_path=f"/tmp/{i}.jpg")

        # 2 paris gagnants (100 misé chacun, 190 encaissé chacun)
        bet1 = _make_pending(db_path, 1, stake=100, potential_return=190)
        mark_bet_won(db_path, bet1, winning_image_id=1, confirmed_payout=190)
        bet2 = _make_pending(db_path, 2, stake=50, potential_return=95)
        mark_bet_won(db_path, bet2, winning_image_id=2, confirmed_payout=95)

        # 1 pari perdant (100 misé, rien encaissé)
        bet3 = _make_pending(db_path, 3, stake=100, potential_return=180)
        with get_connection(db_path) as conn:
            conn.execute("UPDATE bets SET status='LOST' WHERE id=?", (bet3,))
            conn.commit()

        # 1 pari encore en attente (ne doit PAS compter dans le win rate ni les finances)
        _make_pending(db_path, 4, stake=1000, potential_return=2000)

        # 1 pari en révision manuelle
        create_bet(
            db_path, telegram_message_id=None, original_image_id=5,
            team_1="C", team_2="D", competition=None, event_date=None, event_time=None,
            market=None, selection=None, odds=1.5, stake=20, potential_return=30,
            status="MANUAL_REVIEW", confidence=0.4,
        )

        stats = compute_statistics(db_path)

        assert stats["total"] == 5
        assert stats["won"] == 2
        assert stats["lost"] == 1
        assert stats["pending"] == 1
        assert stats["manual_review"] == 1

        # win rate = 2 / (2+1) = 66.67%
        assert stats["win_rate"] == 66.67

        # finances : staked sur WON+LOST seulement = 100+50+100 = 250
        assert stats["total_staked"] == 250
        # returned : 190+95 (les 2 WON) = 285
        assert stats["total_returned"] == 285
        # profit = 285 - 250 = 35
        assert stats["profit"] == 35

        # le message se formate sans erreur et contient les infos clés
        message = format_stats_message(stats)
        assert "66.67%" in message
        assert "Total des paris : 5" in message

    print("OK - test_compute_statistics")


def test_no_resolved_bets_yet():
    """Aucun pari résolu -> win_rate=None, finances à 0, pas de crash."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        insert_raw_image(db_path, telegram_message_id=1, telegram_date="2026-08-20T10:00:00", file_path="/tmp/1.jpg")
        _make_pending(db_path, 1, stake=100, potential_return=190)

        stats = compute_statistics(db_path)
        assert stats["win_rate"] is None
        assert stats["total_staked"] == 0
        assert stats["total_returned"] == 0

        message = format_stats_message(stats)
        assert "N/A" in message

    print("OK - test_no_resolved_bets_yet")


if __name__ == "__main__":
    test_compute_statistics()
    test_no_resolved_bets_yet()
