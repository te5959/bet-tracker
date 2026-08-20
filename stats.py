"""
Phase 6 — Statistics Engine

Calcule les statistiques décrites en section 14 du cahier des charges, à
partir de la table `bets`.

Choix de calcul (documentés car ambigus dans la spec brute) :

- "Total misé" / "Total encaissé" / "Bénéfice" ne portent que sur les paris
  RÉSOLUS (WON ou LOST). Un pari encore PENDING a bien une mise engagée,
  mais son issue est inconnue — l'inclure fausserait le bénéfice affiché.
  Les stats de comptage (total, gagnants, perdants...) portent elles sur
  TOUS les paris, PENDING et MANUAL_REVIEW inclus, pour donner une vue
  complète de l'activité.

- Le gain encaissé sur un pari WON = confirmed_payout si disponible
  (valeur confirmée sur l'image de gain), sinon on retombe sur
  potential_return (valeur du ticket initial) en dernier recours.

- Le taux de réussite (win rate) ne mélange jamais PENDING/MANUAL_REVIEW
  avec les résultats définitifs (règle explicite section 14).

Ce module est pur calcul, sans aucune dépendance à Telegram : testable
indépendamment.
"""

from db import get_connection


def compute_statistics(db_path) -> dict:
    with get_connection(db_path) as conn:
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM bets GROUP BY status"
        ).fetchall()
        by_status = {row["status"]: row["c"] for row in status_rows}

        total = sum(by_status.values())
        won = by_status.get("WON", 0)
        lost = by_status.get("LOST", 0)
        pending = by_status.get("PENDING", 0)
        manual_review = by_status.get("MANUAL_REVIEW", 0)

        win_rate = round(won / (won + lost) * 100, 2) if (won + lost) > 0 else None

        financial_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status IN ('WON','LOST') THEN stake END), 0) AS total_staked,
                COALESCE(SUM(CASE WHEN status = 'WON'
                                   THEN COALESCE(confirmed_payout, potential_return) END), 0) AS total_returned
            FROM bets
            """
        ).fetchone()
        total_staked = round(financial_row["total_staked"] or 0, 2)
        total_returned = round(financial_row["total_returned"] or 0, 2)
        profit = round(total_returned - total_staked, 2)

        periods = {}
        for label, sql_modifier in (
            ("today", "start of day"),
            ("last_7_days", "-7 days"),
            ("this_month", "start of month"),
        ):
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) AS won,
                    SUM(CASE WHEN status = 'LOST' THEN 1 ELSE 0 END) AS lost
                FROM bets
                WHERE detected_at >= datetime('now', ?)
                """,
                (sql_modifier,),
            ).fetchone()
            periods[label] = {
                "total": row["total"] or 0,
                "won": row["won"] or 0,
                "lost": row["lost"] or 0,
            }

        return {
            "total": total,
            "won": won,
            "lost": lost,
            "pending": pending,
            "manual_review": manual_review,
            "win_rate": win_rate,
            "total_staked": total_staked,
            "total_returned": total_returned,
            "profit": profit,
            "periods": periods,
        }


def format_stats_message(stats: dict) -> str:
    """Formate les statistiques en message texte lisible pour Telegram."""
    win_rate_str = f"{stats['win_rate']}%" if stats["win_rate"] is not None else "N/A (pas encore de résultat)"

    lines = [
        "📊 STATISTIQUES DU TIPSTER",
        "",
        f"Total des paris : {stats['total']}",
        f"✅ Gagnés : {stats['won']}",
        f"❌ Perdus : {stats['lost']}",
        f"⏳ En attente : {stats['pending']}",
        f"🔎 À vérifier : {stats['manual_review']}",
        "",
        f"Taux de réussite : {win_rate_str}",
        "",
        "💰 Finances (paris résolus uniquement)",
        f"Total misé : {stats['total_staked']}",
        f"Total encaissé : {stats['total_returned']}",
        f"Bénéfice : {stats['profit']}",
        "",
        "📅 Par période",
        f"Aujourd'hui : {stats['periods']['today']['total']} paris "
        f"({stats['periods']['today']['won']} gagnés, {stats['periods']['today']['lost']} perdus)",
        f"7 derniers jours : {stats['periods']['last_7_days']['total']} paris "
        f"({stats['periods']['last_7_days']['won']} gagnés, {stats['periods']['last_7_days']['lost']} perdus)",
        f"Ce mois-ci : {stats['periods']['this_month']['total']} paris "
        f"({stats['periods']['this_month']['won']} gagnés, {stats['periods']['this_month']['lost']} perdus)",
    ]
    return "\n".join(lines)
