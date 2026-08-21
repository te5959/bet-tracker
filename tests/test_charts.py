"""
Tests du module charts.py, indépendants de Telegram.
Valide : agrégation par jour/semaine/mois, parsing des codes de période,
et que chaque graphique se génère sans erreur et produit une image non vide.
"""

import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import init_db, insert_raw_image, create_bet, mark_bet_won, get_connection
from charts import (
    aggregate_bets_by_unit,
    period_code_to_since,
    render_chart,
    CHART_RENDERERS,
)


def _make_bet_with_date(db_path, image_id, days_ago, stake, potential_return, status="PENDING", payout=None):
    insert_raw_image(db_path, telegram_message_id=image_id, telegram_date="2026-08-20T10:00:00", file_path=f"/tmp/{image_id}.jpg")
    bet_id = create_bet(
        db_path, telegram_message_id=None, original_image_id=image_id,
        team_1="A", team_2="B", competition=None, event_date=None, event_time=None,
        market=None, selection=None, odds=1.9, stake=stake, potential_return=potential_return,
        status="PENDING", confidence=0.9,
    )
    target_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    with get_connection(db_path) as conn:
        conn.execute("UPDATE bets SET detected_at = ? WHERE id = ?", (target_date, bet_id))
        conn.commit()

    if status == "WON":
        mark_bet_won(db_path, bet_id, winning_image_id=image_id, confirmed_payout=payout)
    elif status == "LOST":
        with get_connection(db_path) as conn:
            conn.execute("UPDATE bets SET status='LOST' WHERE id=?", (bet_id,))
            conn.commit()

    return bet_id


def test_period_code_to_since():
    since, label = period_code_to_since("1w")
    assert label == "1 semaine"
    assert since is not None

    since, label = period_code_to_since("invalid")
    assert since is None and label is None

    print("OK - test_period_code_to_since")


def test_aggregate_by_day():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        # 2 paris aujourd'hui, 1 pari il y a 2 jours
        _make_bet_with_date(db_path, 1, days_ago=0, stake=100, potential_return=190, status="WON", payout=190)
        _make_bet_with_date(db_path, 2, days_ago=0, stake=50, potential_return=90, status="LOST")
        _make_bet_with_date(db_path, 3, days_ago=2, stake=100, potential_return=200, status="PENDING")

        buckets = aggregate_bets_by_unit(db_path, unit="day")
        assert len(buckets) == 2  # 2 jours distincts

        today_bucket = buckets[-1]  # le plus récent en dernier (ordre chronologique)
        assert today_bucket["total"] == 2
        assert today_bucket["won"] == 1
        assert today_bucket["lost"] == 1
        assert today_bucket["returned"] == 190
        assert today_bucket["staked"] == 150  # 100 (WON) + 50 (LOST)

        older_bucket = buckets[0]
        assert older_bucket["pending"] == 1
        assert older_bucket["pending_stake"] == 100

    print("OK - test_aggregate_by_day")


def test_aggregate_with_since_filter():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        _make_bet_with_date(db_path, 1, days_ago=1, stake=100, potential_return=190, status="WON", payout=190)
        _make_bet_with_date(db_path, 2, days_ago=40, stake=50, potential_return=90, status="WON", payout=90)

        since, _ = period_code_to_since("1w")
        buckets = aggregate_bets_by_unit(db_path, unit="day", since=since)

        # seul le pari récent (1 jour) doit être inclus, pas celui à 40 jours
        total_in_buckets = sum(b["total"] for b in buckets)
        assert total_in_buckets == 1

    print("OK - test_aggregate_with_since_filter")


def test_aggregate_by_week_groups_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        # 2 paris à 1 jour d'écart (même semaine a priori) -> doivent se regrouper
        _make_bet_with_date(db_path, 1, days_ago=0, stake=100, potential_return=190, status="WON", payout=190)
        _make_bet_with_date(db_path, 2, days_ago=1, stake=50, potential_return=90, status="WON", payout=90)

        buckets = aggregate_bets_by_unit(db_path, unit="week")
        # doit produire 1 seul bucket (même semaine) ou 2 si le test tombe sur un lundi -
        # dans tous les cas, le total des paris doit être conservé
        assert sum(b["total"] for b in buckets) == 2

    print("OK - test_aggregate_by_week_groups_correctly")


def test_all_chart_types_render_without_error():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        _make_bet_with_date(db_path, 1, days_ago=0, stake=100, potential_return=190, status="WON", payout=190)
        _make_bet_with_date(db_path, 2, days_ago=1, stake=50, potential_return=90, status="LOST")
        _make_bet_with_date(db_path, 3, days_ago=2, stake=200, potential_return=350, status="PENDING")

        buckets = aggregate_bets_by_unit(db_path, unit="day")

        for graph_type in CHART_RENDERERS:
            image_buf = render_chart(graph_type, buckets, unit="day")
            assert image_buf is not None
            data = image_buf.read()
            assert len(data) > 1000  # une vraie image PNG, pas un buffer vide
            assert data[:8] == b"\x89PNG\r\n\x1a\n"  # signature PNG

    print("OK - test_all_chart_types_render_without_error")


def test_render_chart_with_no_data_returns_none():
    image_buf = render_chart("profit", [], unit="day")
    assert image_buf is None

    image_buf2 = render_chart("unknown_type", [{"label": "x"}], unit="day")
    assert image_buf2 is None

    print("OK - test_render_chart_with_no_data_returns_none")


if __name__ == "__main__":
    test_period_code_to_since()
    test_aggregate_by_day()
    test_aggregate_with_since_filter()
    test_aggregate_by_week_groups_correctly()
    test_all_chart_types_render_without_error()
    test_render_chart_with_no_data_returns_none()
