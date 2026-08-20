"""
Phase 5 — Détection des paris perdus par délai

Rôle (règle 6 et section 13 du cahier des charges) :

    Un pari ne peut pas rester indéfiniment PENDING. Comme le tipster ne
    republie généralement pas ses paris perdants (règle 5/6), l'ABSENCE de
    confirmation de gain après un délai de sécurité est traitée comme une
    perte probable.

Choix du délai : basé sur `detected_at` (heure de détection du pari par le
système), et non sur l'heure de l'événement extraite par l'IA — cette
dernière est souvent absente ou peu fiable (formats libres, fuseaux
horaires). Un délai fixe après détection est plus simple et robuste.

Délai retenu : 24h (configurable), suffisamment long pour couvrir un match
+ prolongations + le temps que le tipster prenne pour poster sa
confirmation de gain, mais assez court pour ne pas fausser les
statistiques trop longtemps.

Important : seuls les paris `PENDING` sont concernés. Les paris
`MANUAL_REVIEW` ne sont PAS auto-expirés : ils nécessitent un regard
humain avant toute décision, puisque l'extraction initiale était déjà
incertaine.
"""

DEFAULT_EXPIRY_HOURS = 24


def expire_stale_bets(db_path, delay_hours: int, logger) -> int:
    """Passe en LOST tous les paris PENDING détectés il y a plus de
    delay_hours heures. Retourne le nombre de paris expirés."""
    from db import get_expirable_bets, mark_bet_lost  # import local pour éviter un cycle

    expirable = get_expirable_bets(db_path, delay_hours)

    for bet in expirable:
        mark_bet_lost(db_path, bet["id"])
        logger.info(
            "Pari #%s (%s vs %s, détecté le %s) → LOST (délai de %sh dépassé sans confirmation)",
            bet["id"], bet["team_1"], bet["team_2"], bet["detected_at"], delay_hours,
        )

    return len(expirable)
