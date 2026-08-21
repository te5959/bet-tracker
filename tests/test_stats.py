"""
Tests du moteur de statistiques Phase 6, indépendants de Telegram.
Valide : comptages par statut, taux de réussite, les 2 calculs de bénéfice
(normal et conservateur), ROI, moyennes, extrêmes, et le tableau détaillé.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import init_db, insert_raw_image, create_bet, mark_bet_won, get_recent_bets, get_connection
from stats import (
    compute_statistics,
    format_stats_message,
    format_bets_table,
    resolve_period,
    compute_bets_period_summary,
    format_period_summary_message,
)


def _make_pending(db_path, image_id, stake, potential_return, odds=1.9, team_1="A", team_2="B"):
    return create_bet(
        db_path, telegram_message_id=None, original_image_id=image_id,
        team_1=team_1, team_2=team_2, competition=None, event_date=None, event_time=None,
        market=None, selection=None, odds=odds, stake=stake, potential_return=potential_return,
        status="PENDING", confidence=0.9,
    )


def test_compute_statistics_full():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        for i in range(1, 7):
            insert_raw_image(db_path, telegram_message_id=i, telegram_date="2026-08-20T10:00:00", file_path=f"/tmp/{i}.jpg")

        # 2 paris gagnants
        bet1 = _make_pending(db_path, 1, stake=100, potential_return=190, odds=1.9, team_1="PSG", team_2="Lyon")
        mark_bet_won(db_path, bet1, winning_image_id=1, confirmed_payout=190)  # net +90
        bet2 = _make_pending(db_path, 2, stake=50, potential_return=95, odds=1.9, team_1="Real", team_2="Barca")
        mark_bet_won(db_path, bet2, winning_image_id=2, confirmed_payout=95)   # net +45

        # 1 pari perdant
        bet3 = _make_pending(db_path, 3, stake=100, potential_return=180, team_1="Bayern", team_2="Dortmund")
        with get_connection(db_path) as conn:
            conn.execute("UPDATE bets SET status='LOST' WHERE id=?", (bet3,))
            conn.commit()

        # 2 paris encore en attente (mises 1000 et 200 -> pending_stake=1200)
        _make_pending(db_path, 4, stake=1000, potential_return=2000)
        _make_pending(db_path, 5, stake=200, potential_return=380)

        # 1 pari en révision manuelle (ne doit compter dans aucun calcul financier)
        create_bet(
            db_path, telegram_message_id=None, original_image_id=6,
            team_1="C", team_2="D", competition=None, event_date=None, event_time=None,
            market=None, selection=None, odds=1.5, stake=20, potential_return=30,
            status="MANUAL_REVIEW", confidence=0.4,
        )

        stats = compute_statistics(db_path)

        assert stats["total"] == 6
        assert stats["won"] == 2
        assert stats["lost"] == 1
        assert stats["pending"] == 2
        assert stats["manual_review"] == 1
        assert stats["win_rate"] == 66.67

        # Scénario normal : staked=100+50+100=250, returned=190+95=285, profit=35
        assert stats["total_staked"] == 250
        assert stats["total_returned"] == 285
        assert stats["profit_normal"] == 35
        assert stats["roi_normal"] == round(35 / 250 * 100, 2)

        # Scénario conservateur : pending_stake=1200, profit = 35 - 1200 = -1165
        assert stats["pending_stake"] == 1200
        assert stats["profit_conservative"] == -1165
        expected_roi_cons = round(-1165 / (250 + 1200) * 100, 2)
        assert stats["roi_conservative"] == expected_roi_cons

        # Moyennes sur les 3 paris résolus (odds 1.9, 1.9, 1.9 -> avg 1.9 ; stakes 100,50,100 -> avg 83.33)
        assert stats["avg_odds"] == 1.9
        assert stats["avg_stake"] == round((100 + 50 + 100) / 3, 2)

        # Meilleur gain = PSG vs Lyon (+90), plus grosse perte = Bayern vs Dortmund (-100)
        assert stats["biggest_win"]["net"] == 90
        assert stats["biggest_loss"]["stake"] == 100

        message = format_stats_message(stats)
        assert "scénario conservateur" in message
        assert "-1165" in message

    print("OK - test_compute_statistics_full")


def test_no_resolved_bets_yet():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        insert_raw_image(db_path, telegram_message_id=1, telegram_date="2026-08-20T10:00:00", file_path="/tmp/1.jpg")
        _make_pending(db_path, 1, stake=100, potential_return=190)

        stats = compute_statistics(db_path)
        assert stats["win_rate"] is None
        assert stats["roi_normal"] is None
        assert stats["biggest_win"] is None
        assert stats["biggest_loss"] is None
        # conservateur : profit = 0 - 100 (pending_stake) = -100, ROI = -100/(0+100)*100 = -100%
        assert stats["profit_conservative"] == -100
        assert stats["roi_conservative"] == -100.0

        message = format_stats_message(stats)
        assert "N/A" in message

    print("OK - test_no_resolved_bets_yet")


def test_bets_table_and_recent_bets():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)
        insert_raw_image(db_path, telegram_message_id=1, telegram_date="2026-08-20T10:00:00", file_path="/tmp/1.jpg")
        insert_raw_image(db_path, telegram_message_id=2, telegram_date="2026-08-20T10:00:00", file_path="/tmp/2.jpg")

        bet1 = _make_pending(db_path, 1, stake=100, potential_return=190, team_1="PSG", team_2="Lyon")
        bet2 = _make_pending(db_path, 2, stake=50, potential_return=95, team_1="Real", team_2="Barca")

        recent = get_recent_bets(db_path, limit=10)
        # le plus récent en premier
        assert recent[0]["id"] == bet2
        assert recent[1]["id"] == bet1

        table = format_bets_table(recent)
        assert "PSG" in table
        assert "Real" in table
        assert "```" in table

        # cas vide
        assert "Aucun pari" in format_bets_table([])

    print("OK - test_bets_table_and_recent_bets")


def test_resolve_period():
    # aucun argument -> pas de filtre
    since, until, label = resolve_period(None)
    assert since is None and until is None and label == "Derniers paris"

    # today -> since = minuit aujourd'hui, until=None
    since, until, label = resolve_period("today")
    assert since is not None and until is None and label == "Aujourd'hui"
    assert since.endswith("00:00:00")

    # week
    since, until, label = resolve_period("week")
    assert since is not None and label == "7 derniers jours"

    # month
    since, until, label = resolve_period("month")
    assert since is not None and label == "Ce mois-ci"

    # date précise
    since, until, label = resolve_period("2026-08-19")
    assert since == "2026-08-19 00:00:00"
    assert until == "2026-08-20 00:00:00"
    assert label == "Le 2026-08-19"

    # argument invalide -> label None (signal d'erreur pour le bot)
    since, until, label = resolve_period("blabla")
    assert label is None

    print("OK - test_resolve_period")


def test_compute_bets_period_summary():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        init_db(db_path)

        for i in range(1, 4):
            insert_raw_image(db_path, telegram_message_id=i, telegram_date="2026-08-20T10:00:00", file_path=f"/tmp/{i}.jpg")

        bet1 = _make_pending(db_path, 1, stake=100, potential_return=190, team_1="PSG", team_2="Lyon")
        mark_bet_won(db_path, bet1, winning_image_id=1, confirmed_payout=190)

        bet2 = _make_pending(db_path, 2, stake=50, potential_return=95, team_1="Real", team_2="Barca")
        with get_connection(db_path) as conn:
            conn.execute("UPDATE bets SET status='LOST' WHERE id=?", (bet2,))
            conn.commit()

        _make_pending(db_path, 3, stake=200, potential_return=400, team_1="Bayern", team_2="PSV")

        # Sans filtre de date : les 3 paris
        summary = compute_bets_period_summary(db_path)
        assert summary["total"] == 3
        assert summary["won"] == 1
        assert summary["lost"] == 1
        assert summary["pending"] == 1
        assert summary["total_returned"] == 190
        assert summary["profit_normal"] == 190 - (100 + 50)  # = 40
        assert summary["profit_conservative"] == 40 - 200  # pending stake soustrait = -160

        # Filtre sur une période future (aucun pari ne doit matcher)
        future_summary = compute_bets_period_summary(db_path, since="2099-01-01 00:00:00")
        assert future_summary["total"] == 0
        assert future_summary["bets"] == []

        message = format_period_summary_message(summary, "Test")
        assert "PSG" in message
        assert "Total gains" in message
        assert "-160" in message

    print("OK - test_compute_bets_period_summary")


if __name__ == "__main__":
    test_compute_statistics_full()
    test_no_resolved_bets_yet()
    test_bets_table_and_recent_bets()
    test_resolve_period()
    test_compute_bets_period_summary()
