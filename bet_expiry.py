"""
Phase 5 — Détection des paris perdus (logique hybride)

Règle (règle 6 et section 13 du cahier des charges), affinée suite à
l'observation que les captures contiennent souvent la date/heure du match :

    PRIORITÉ 1 — basé sur l'heure du match (event_date + event_time) :
        Si ces deux champs sont présents ET exploitables, un pari PENDING
        est considéré perdu EVENT_EXPIRY_HOURS après le début du match
        (5h par défaut : ~2h de match + prolongations/tirs au but éventuels
        + le temps que le tipster prenne pour poster sa confirmation).

    PRIORITÉ 2 — filet de sécurité par délai de détection :
        Si event_date/event_time sont absents, illisibles, ou dans un
        format que l'on ne sait pas interpréter, on retombe sur l'ancienne
        règle : FALLBACK_EXPIRY_HOURS (24h) après `detected_at`.

Limites connues (transparence importante) :
    - L'heure du match sur le ticket peut être dans un fuseau horaire
      différent de celui du serveur. Le délai de 5h absorbe en partie ce
      risque, mais un décalage important (>2-3h) pourrait provoquer une
      expiration légèrement prématurée ou tardive.
    - Le parsing utilise `python-dateutil`, tolérant à beaucoup de formats,
      mais reste heuristique sur des données anciennes extraites avant le
      resserrement du format demandé à l'IA (voir ai_vision.py).

Comme pour la version précédente : seuls les paris `PENDING` sont
concernés. `MANUAL_REVIEW` n'est jamais auto-expiré.
"""

from datetime import datetime, timedelta

try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None


EVENT_EXPIRY_HOURS = 5
FALLBACK_EXPIRY_HOURS = 24


def parse_event_datetime(event_date: str | None, event_time: str | None) -> datetime | None:
    """Tente de reconstruire un datetime à partir des champs extraits par
    l'IA. Retourne None si l'un des deux manque, ou si le parsing échoue —
    dans les deux cas, l'appelant doit alors utiliser le filet de sécurité
    (delay depuis detected_at). On exige les DEUX champs : une date seule
    sans heure donnerait un horaire par défaut (minuit) trompeur."""
    if not event_date or not event_time or dateutil_parser is None:
        return None
    try:
        return dateutil_parser.parse(f"{event_date} {event_time}", fuzzy=True)
    except (ValueError, OverflowError):
        return None


def _parse_detected_at(detected_at: str) -> datetime:
    return datetime.strptime(detected_at, "%Y-%m-%d %H:%M:%S")


def compute_deadline(bet: dict, event_hours: int, fallback_hours: int) -> tuple[datetime, str]:
    """Retourne (deadline, méthode utilisée : 'event' ou 'fallback')."""
    event_dt = parse_event_datetime(bet.get("event_date"), bet.get("event_time"))
    if event_dt is not None:
        return event_dt + timedelta(hours=event_hours), "event"

    detected_dt = _parse_detected_at(bet["detected_at"])
    return detected_dt + timedelta(hours=fallback_hours), "fallback"


def expire_stale_bets(
    db_path,
    logger,
    event_hours: int = EVENT_EXPIRY_HOURS,
    fallback_hours: int = FALLBACK_EXPIRY_HOURS,
) -> int:
    """Passe en LOST tous les paris PENDING dont la deadline (calculée par
    compute_deadline) est dépassée. Retourne le nombre de paris expirés."""
    from db import get_pending_bets_for_expiry, mark_bet_lost  # import local pour éviter un cycle

    now = datetime.now()
    expired_count = 0

    for bet in get_pending_bets_for_expiry(db_path):
        deadline, method = compute_deadline(bet, event_hours, fallback_hours)
        if deadline <= now:
            mark_bet_lost(db_path, bet["id"])
            reason = (
                f"match commencé le {bet.get('event_date')} à {bet.get('event_time')}"
                if method == "event"
                else f"détecté le {bet['detected_at']}, aucune date de match exploitable"
            )
            logger.info(
                "Pari #%s (%s vs %s) → LOST (%s, délai dépassé)",
                bet["id"], bet["team_1"], bet["team_2"], reason,
            )
            expired_count += 1

    return expired_count
