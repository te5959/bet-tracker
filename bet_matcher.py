"""
Phase 4 — Bet Matching Engine

Rôle (section 9 du cahier des charges) :

    Quand une image classée `winning_bet` est détectée, retrouver à quel
    pari `PENDING` (ou MANUAL_REVIEW) existant elle correspond, à partir
    d'un score de similarité entre les données extraites des deux images.

Critères de score (pondérés) :
    - équipes (40%)         : comparaison texte, y compris ordre inversé
    - marché / sélection (25%)
    - cote (20%)             : comparaison numérique avec tolérance
    - mise (15%)              : comparaison numérique avec tolérance

    Si une donnée manque des deux côtés, le critère est exclu du calcul et
    le poids restant est redistribué (renormalisation).

Règle de départage en cas d'égalité (cas explicitement signalé : le même
pari peut être posté deux fois par le tipster) : on choisit le pari
`PENDING` le plus ANCIEN parmi les meilleurs candidats à égalité — on
suppose que les confirmations de gain arrivent dans le même ordre que les
paris ont été placés.

Seuil de décision : en dessous de MATCH_THRESHOLD, on ne force aucun
matching automatique — l'image reste "non matchée" et sera retentée au
prochain passage (utile si le bon pari PENDING correspondant n'existe pas
encore en base au moment du test).
"""

import json
from difflib import SequenceMatcher


MATCH_THRESHOLD = 0.60

WEIGHT_TEAMS = 0.40
WEIGHT_MARKET = 0.25
WEIGHT_ODDS = 0.20
WEIGHT_STAKE = 0.15


def _text_similarity(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _number_similarity(a: float | None, b: float | None, tolerance: float = 0.02) -> float | None:
    """1.0 si quasi identiques, dégradé linéairement, 0 si très éloignés.
    tolerance = fraction de différence relative tolérée avant score 0."""
    if a is None or b is None:
        return None
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if a == 0 and b == 0:
        return 1.0
    diff_ratio = abs(a - b) / max(abs(a), abs(b), 0.01)
    if diff_ratio <= tolerance:
        return 1.0
    score = 1.0 - (diff_ratio - tolerance) * 3  # dégradation progressive
    return max(0.0, min(1.0, score))


def _teams_similarity(winning: dict, candidate: dict) -> float | None:
    w1, w2 = winning.get("team_1"), winning.get("team_2")
    c1, c2 = candidate.get("team_1"), candidate.get("team_2")

    if not (w1 or w2) or not (c1 or c2):
        return None

    straight_scores = [s for s in (_text_similarity(w1, c1), _text_similarity(w2, c2)) if s is not None]
    swapped_scores = [s for s in (_text_similarity(w1, c2), _text_similarity(w2, c1)) if s is not None]

    straight = sum(straight_scores) / len(straight_scores) if straight_scores else 0.0
    swapped = sum(swapped_scores) / len(swapped_scores) if swapped_scores else 0.0

    return max(straight, swapped)


def score_match(winning: dict, candidate: dict) -> float:
    """Retourne un score de correspondance entre 0 et 1."""
    components = []

    teams_score = _teams_similarity(winning, candidate)
    if teams_score is not None:
        components.append((WEIGHT_TEAMS, teams_score))

    market_text_winning = " ".join(filter(None, [winning.get("market"), winning.get("selection")]))
    market_text_candidate = " ".join(filter(None, [candidate.get("market"), candidate.get("selection")]))
    market_score = _text_similarity(market_text_winning or None, market_text_candidate or None)
    if market_score is not None:
        components.append((WEIGHT_MARKET, market_score))

    odds_score = _number_similarity(winning.get("odds"), candidate.get("odds"))
    if odds_score is not None:
        components.append((WEIGHT_ODDS, odds_score))

    stake_score = _number_similarity(winning.get("stake"), candidate.get("stake"))
    if stake_score is not None:
        components.append((WEIGHT_STAKE, stake_score))

    if not components:
        return 0.0

    total_weight = sum(w for w, _ in components)
    return sum(w * s for w, s in components) / total_weight


def find_best_match(winning: dict, candidates: list[dict]) -> tuple[dict | None, float]:
    """Retourne (meilleur_candidat, score). En cas d'égalité stricte, garde
    le premier rencontré — les candidats doivent être fournis triés du plus
    ancien au plus récent (cf. get_open_bets), pour que le départage
    favorise le pari le plus ancien."""
    best_candidate = None
    best_score = 0.0
    for candidate in candidates:
        score = score_match(winning, candidate)
        if score > best_score:
            best_score = score
            best_candidate = candidate
    return best_candidate, best_score


def match_winning_analysis(db_path, analysis: dict, logger, threshold: float = MATCH_THRESHOLD) -> str:
    """
    Traite une analyse winning_bet et tente de la relier à un pari PENDING.
    Retourne "matched", "no_candidates" ou "low_confidence".
    Ne marque JAMAIS l'analyse comme "traitée définitivement" en cas
    d'échec : elle sera retentée au prochain passage (get_unmatched_winning_analyses
    l'exclut seulement une fois qu'un bet.winning_image_id la référence).
    """
    from db import get_open_bets, mark_bet_won  # import local pour éviter un cycle

    raw_image_id = analysis["raw_image_id"]

    try:
        winning = json.loads(analysis["extracted_json"])
    except (json.JSONDecodeError, TypeError):
        winning = {}

    candidates = get_open_bets(db_path, statuses=("PENDING",))

    if not candidates:
        logger.info(
            "Aucun pari PENDING candidat pour l'image gagnante raw_image_id=%s",
            raw_image_id,
        )
        return "no_candidates"

    best_candidate, best_score = find_best_match(winning, candidates)

    if best_candidate is not None and best_score >= threshold:
        mark_bet_won(
            db_path,
            bet_id=best_candidate["id"],
            winning_image_id=raw_image_id,
            confirmed_payout=winning.get("confirmed_payout") or winning.get("payout"),
        )
        logger.info(
            "Pari #%s → WON (correspondance %.0f%% avec raw_image_id=%s)",
            best_candidate["id"], best_score * 100, raw_image_id,
        )
        return "matched"

    logger.info(
        "Meilleure correspondance insuffisante (%.0f%%) pour raw_image_id=%s, "
        "laissé pour un nouveau passage",
        best_score * 100, raw_image_id,
    )
    return "low_confidence"
