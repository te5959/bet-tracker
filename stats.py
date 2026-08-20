"""
Phase 6 — Statistics Engine

Calcule les statistiques décrites en section 14 du cahier des charges, à
partir de la table `bets`, avec quelques enrichissements utiles à l'analyse.

Choix de calcul (documentés car ambigus dans la spec brute) :

- Les stats de comptage (total, gagnants, perdants...) portent sur TOUS
  les paris, PENDING et MANUAL_REVIEW inclus, pour donner une vue complète
  de l'activité.

- Le taux de réussite (win rate) ne mélange jamais PENDING/MANUAL_REVIEW
  avec les résultats définitifs (règle explicite section 14).

- Le gain encaissé sur un pari WON = confirmed_payout si disponible
  (valeur confirmée sur l'image de gain), sinon on retombe sur
  potential_return (valeur du ticket initial) en dernier recours.

- DEUX calculs de bénéfice sont fournis :
    * "normal"       : ne porte que sur les paris déjà RÉSOLUS (WON/LOST).
                        Les paris PENDING ne sont pas comptés, ni en misé
                        ni en perdu — leur issue est encore inconnue.
    * "conservateur" : identique, mais traite en plus la mise de TOUS les
                        paris encore PENDING comme une perte totale
                        (scénario prudent : "et si aucun d'eux ne gagnait ?").
  Le ROI (%) est fourni pour les deux, rapporté au total misé correspondant.

- MANUAL_REVIEW n'est inclus dans AUCUN calcul financier : ces paris ne
  sont pas encore confirmés comme valides.

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
                                   THEN COALESCE(confirmed_payout, potential_return) END), 0) AS total_returned,
                COALESCE(SUM(CASE WHEN status = 'PENDING' THEN stake END), 0) AS pending_stake,
                AVG(CASE WHEN status IN ('WON','LOST') THEN odds END) AS avg_odds,
                AVG(CASE WHEN status IN ('WON','LOST') THEN stake END) AS avg_stake
            FROM bets
            """
        ).fetchone()

        total_staked = round(financial_row["total_staked"] or 0, 2)
        total_returned = round(financial_row["total_returned"] or 0, 2)
        pending_stake = round(financial_row["pending_stake"] or 0, 2)
        avg_odds = round(financial_row["avg_odds"], 2) if financial_row["avg_odds"] is not None else None
        avg_stake = round(financial_row["avg_stake"], 2) if financial_row["avg_stake"] is not None else None

        profit_normal = round(total_returned - total_staked, 2)
        profit_conservative = round(profit_normal - pending_stake, 2)

        roi_normal = round(profit_normal / total_staked * 100, 2) if total_staked > 0 else None
        conservative_denom = total_staked + pending_stake
        roi_conservative = (
            round(profit_conservative / conservative_denom * 100, 2) if conservative_denom > 0 else None
        )

        biggest_win_row = conn.execute(
            """
            SELECT team_1, team_2, (COALESCE(confirmed_payout, potential_return) - stake) AS net
            FROM bets WHERE status = 'WON'
            ORDER BY net DESC LIMIT 1
            """
        ).fetchone()
        biggest_win = (
            {"team_1": biggest_win_row["team_1"], "team_2": biggest_win_row["team_2"], "net": round(biggest_win_row["net"], 2)}
            if biggest_win_row else None
        )

        biggest_loss_row = conn.execute(
            """
            SELECT team_1, team_2, stake FROM bets WHERE status = 'LOST'
            ORDER BY stake DESC LIMIT 1
            """
        ).fetchone()
        biggest_loss = (
            {"team_1": biggest_loss_row["team_1"], "team_2": biggest_loss_row["team_2"], "stake": round(biggest_loss_row["stake"], 2)}
            if biggest_loss_row else None
        )

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
            "pending_stake": pending_stake,
            "profit_normal": profit_normal,
            "profit_conservative": profit_conservative,
            "roi_normal": roi_normal,
            "roi_conservative": roi_conservative,
            "avg_odds": avg_odds,
            "avg_stake": avg_stake,
            "biggest_win": biggest_win,
            "biggest_loss": biggest_loss,
            "periods": periods,
        }


def format_stats_message(stats: dict) -> str:
    """Formate les statistiques en message texte lisible pour Telegram."""
    win_rate_str = f"{stats['win_rate']}%" if stats["win_rate"] is not None else "N/A (pas encore de résultat)"
    roi_normal_str = f"{stats['roi_normal']}%" if stats["roi_normal"] is not None else "N/A"
    roi_cons_str = f"{stats['roi_conservative']}%" if stats["roi_conservative"] is not None else "N/A"

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
        "💰 Bénéfice — scénario normal (paris résolus uniquement)",
        f"Total misé : {stats['total_staked']}",
        f"Total encaissé : {stats['total_returned']}",
        f"Bénéfice : {stats['profit_normal']}",
        f"ROI : {roi_normal_str}",
        "",
        "🛡️ Bénéfice — scénario conservateur (les paris en attente comptés comme perdus)",
        f"Mise en attente incluse : {stats['pending_stake']}",
        f"Bénéfice : {stats['profit_conservative']}",
        f"ROI : {roi_cons_str}",
        "",
        "📈 Autres indicateurs",
        f"Cote moyenne : {stats['avg_odds'] if stats['avg_odds'] is not None else 'N/A'}",
        f"Mise moyenne : {stats['avg_stake'] if stats['avg_stake'] is not None else 'N/A'}",
    ]

    if stats["biggest_win"]:
        bw = stats["biggest_win"]
        lines.append(f"Meilleur gain : {bw['team_1']} vs {bw['team_2']} (+{bw['net']})")
    if stats["biggest_loss"]:
        bl = stats["biggest_loss"]
        lines.append(f"Plus grosse perte : {bl['team_1']} vs {bl['team_2']} (-{bl['stake']})")

    lines += [
        "",
        "📅 Par période",
        f"Aujourd'hui : {stats['periods']['today']['total']} paris "
        f"({stats['periods']['today']['won']} gagnés, {stats['periods']['today']['lost']} perdus)",
        f"7 derniers jours : {stats['periods']['last_7_days']['total']} paris "
        f"({stats['periods']['last_7_days']['won']} gagnés, {stats['periods']['last_7_days']['lost']} perdus)",
        f"Ce mois-ci : {stats['periods']['this_month']['total']} paris "
        f"({stats['periods']['this_month']['won']} gagnés, {stats['periods']['this_month']['lost']} perdus)",
        "",
        "Envoie /bets pour le détail de chaque pari.",
    ]
    return "\n".join(lines)


def format_bets_table(bets: list, max_chars: int = 3500) -> str:
    """Formate une liste de paris en tableau texte (bloc monospace Telegram).
    Tronque si nécessaire pour respecter la limite de taille des messages
    Telegram (~4096 caractères), en indiquant combien de paris ne sont pas
    affichés."""
    if not bets:
        return "Aucun pari en base pour le moment."

    header = f"{'#':<5}{'Match':<22}{'Cote':<7}{'Mise':<8}{'Statut':<10}{'Gain':<8}\n"
    separator = "-" * len(header.rstrip("\n")) + "\n"

    rows = []
    for bet in bets:
        match = f"{bet['team_1'] or '?'} vs {bet['team_2'] or '?'}"
        match = (match[:20] + "…") if len(match) > 21 else match
        odds = f"{bet['odds']:.2f}" if bet["odds"] is not None else "-"
        stake = f"{bet['stake']:.0f}" if bet["stake"] is not None else "-"
        gain = bet.get("confirmed_payout") or bet.get("potential_return")
        gain_str = f"{gain:.0f}" if gain is not None else "-"
        rows.append(f"{bet['id']:<5}{match:<22}{odds:<7}{stake:<8}{bet['status']:<10}{gain_str:<8}")

    body = header + separator
    included = 0
    for row in rows:
        if len(body) + len(row) + 1 > max_chars:
            break
        body += row + "\n"
        included += 1

    result = "```\n" + body + "```"
    if included < len(rows):
        result += f"\n({len(rows) - included} pari(s) plus ancien(s) non affiché(s))"
    return result
