"""
Graphiques — agrégation des paris par période + rendu matplotlib.

Rôle : transformer les paris bruts en graphiques exploitables par le bot
Telegram (menu /graph). Deux étapes séparées et testables indépendamment :

    1. aggregate_bets_by_unit() — regroupe les paris par jour, semaine ou
       mois, dans une plage de dates donnée (ou toute la base si None).
    2. render_*_chart() — transforme ces buckets en image PNG (en mémoire,
       pas de fichier sur disque).

Convention de bucket "semaine" : le LUNDI de la semaine (norme ISO
européenne), pas le dimanche.

Toutes les fonctions de rendu retournent un buffer BytesIO prêt à être
envoyé tel quel par Telethon (event.respond(file=buffer)).
"""

import io
from collections import OrderedDict
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")  # backend sans interface graphique, obligatoire sur serveur headless
import matplotlib.pyplot as plt

from db import get_connection


PERIOD_CHOICES = {
    "1d": ("1 jour", timedelta(days=1)),
    "1w": ("1 semaine", timedelta(weeks=1)),
    "2w": ("2 semaines", timedelta(weeks=2)),
    "1m": ("1 mois", timedelta(days=30)),
    "3m": ("3 mois", timedelta(days=90)),
    "1y": ("1 an", timedelta(days=365)),
}


def period_code_to_since(period_code: str) -> tuple[str | None, str | None]:
    """Retourne (since, label) pour un code de période (ex: '1w'), ou
    (None, None) si le code n'est pas reconnu."""
    choice = PERIOD_CHOICES.get(period_code)
    if not choice:
        return None, None
    label, delta = choice
    since = (datetime.now() - delta).strftime("%Y-%m-%d %H:%M:%S")
    return since, label


def _bucket_key_and_label(detected_at_str: str, unit: str) -> tuple[str, str]:
    d = datetime.strptime(detected_at_str, "%Y-%m-%d %H:%M:%S")
    if unit == "day":
        key = d.date().isoformat()
        return key, key
    if unit == "week":
        monday = d.date() - timedelta(days=d.weekday())
        key = monday.isoformat()
        return key, key
    if unit == "month":
        key = d.strftime("%Y-%m")
        return key, key
    raise ValueError(f"unité inconnue : {unit}")


def aggregate_bets_by_unit(db_path, unit: str, since: str | None = None) -> list:
    """Regroupe les paris par jour/semaine/mois. Retourne une liste
    chronologique de dicts : label, total, won, lost, pending, staked
    (mise des paris résolus), returned (gains des WON), pending_stake."""
    query = "SELECT status, stake, potential_return, confirmed_payout, detected_at FROM bets"
    params = ()
    if since:
        query += " WHERE detected_at >= ?"
        params = (since,)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    buckets = OrderedDict()
    for row in rows:
        key, label = _bucket_key_and_label(row["detected_at"], unit)
        bucket = buckets.setdefault(key, {
            "label": label, "total": 0, "won": 0, "lost": 0, "pending": 0,
            "staked": 0.0, "returned": 0.0, "pending_stake": 0.0,
        })
        bucket["total"] += 1
        if row["status"] == "WON":
            bucket["won"] += 1
            bucket["staked"] += row["stake"] or 0
            bucket["returned"] += (row["confirmed_payout"] or row["potential_return"] or 0)
        elif row["status"] == "LOST":
            bucket["lost"] += 1
            bucket["staked"] += row["stake"] or 0
        elif row["status"] == "PENDING":
            bucket["pending"] += 1
            bucket["pending_stake"] += row["stake"] or 0

    return [buckets[k] for k in sorted(buckets.keys())]


def _new_figure():
    fig, ax = plt.subplots(figsize=(8, 4.5))
    return fig, ax


def _finalize(fig, ax, title: str, labels: list) -> io.BytesIO:
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    if len(labels) > 8:
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    fig.tight_layout()

    buf = io.BytesIO()
    buf.name = "chart.png"
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    buf.seek(0)
    return buf


def render_cumulative_profit_chart(buckets: list, unit_label: str) -> io.BytesIO:
    labels = [b["label"] for b in buckets]
    profits = [b["returned"] - b["staked"] for b in buckets]
    cumulative = []
    running = 0.0
    for p in profits:
        running += p
        cumulative.append(running)

    fig, ax = _new_figure()
    ax.plot(labels, cumulative, marker="o", color="#2563eb")
    ax.axhline(0, color="gray", linewidth=1, linestyle="--")
    ax.set_ylabel("Bénéfice cumulé")
    return _finalize(fig, ax, f"Bénéfice cumulé — par {unit_label}", labels)


def render_win_rate_chart(buckets: list, unit_label: str) -> io.BytesIO:
    filtered = [b for b in buckets if (b["won"] + b["lost"]) > 0]
    labels = [b["label"] for b in filtered]
    rates = [round(b["won"] / (b["won"] + b["lost"]) * 100, 1) for b in filtered]

    fig, ax = _new_figure()
    ax.bar(labels, rates, color="#16a34a")
    ax.set_ylabel("Taux de réussite (%)")
    ax.set_ylim(0, 100)
    return _finalize(fig, ax, f"Taux de réussite — par {unit_label}", labels)


def render_volume_chart(buckets: list, unit_label: str) -> io.BytesIO:
    labels = [b["label"] for b in buckets]
    won = [b["won"] for b in buckets]
    lost = [b["lost"] for b in buckets]
    pending = [b["pending"] for b in buckets]

    fig, ax = _new_figure()
    ax.bar(labels, won, label="Gagnés", color="#16a34a")
    ax.bar(labels, lost, bottom=won, label="Perdus", color="#dc2626")
    bottom_pending = [w + l for w, l in zip(won, lost)]
    ax.bar(labels, pending, bottom=bottom_pending, label="En attente", color="#9ca3af")
    ax.set_ylabel("Nombre de paris")
    ax.legend()
    return _finalize(fig, ax, f"Volume de paris — par {unit_label}", labels)


def render_stake_vs_returns_chart(buckets: list, unit_label: str) -> io.BytesIO:
    import numpy as np

    labels = [b["label"] for b in buckets]
    staked = [b["staked"] for b in buckets]
    returned = [b["returned"] for b in buckets]

    x = np.arange(len(labels))
    width = 0.35

    fig, ax = _new_figure()
    ax.bar(x - width / 2, staked, width, label="Misé", color="#f59e0b")
    ax.bar(x + width / 2, returned, width, label="Encaissé", color="#2563eb")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Montant")
    ax.legend()
    return _finalize(fig, ax, f"Mise vs Gains — par {unit_label}", labels)


CHART_RENDERERS = {
    "profit": (render_cumulative_profit_chart, "💰 Bénéfice cumulé"),
    "winrate": (render_win_rate_chart, "✅ Taux de réussite"),
    "volume": (render_volume_chart, "📊 Volume de paris"),
    "stakes": (render_stake_vs_returns_chart, "⚖️ Mise vs Gains"),
}

UNIT_LABELS = {"day": "jour", "week": "semaine", "month": "mois"}


def render_chart(graph_type: str, buckets: list, unit: str) -> io.BytesIO | None:
    """Point d'entrée unique utilisé par le bot : type + buckets déjà
    agrégés -> image. Retourne None si le type est inconnu ou s'il n'y a
    aucune donnée à tracer."""
    renderer_entry = CHART_RENDERERS.get(graph_type)
    if renderer_entry is None or not buckets:
        return None
    renderer, _ = renderer_entry
    return renderer(buckets, UNIT_LABELS.get(unit, unit))
