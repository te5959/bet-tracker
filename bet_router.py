"""
Phase 3 — Classification / routage métier

Rôle (section 8 et phase 3 de la roadmap, section 18) :

    À partir du résultat brut de l'analyse IA (table image_analysis), décider
    s'il faut créer un nouveau pari dans la table `bets`, et avec quel
    statut.

Règles de décision :

    image_type == "new_bet"
        confidence >= seuil  -> créer un pari, status = PENDING
        confidence <  seuil  -> créer un pari, status = MANUAL_REVIEW
                                 (on le garde visible plutôt que de le
                                 perdre silencieusement, cf. section 8)

    image_type == "winning_bet"
        -> ne crée PAS de nouveau pari ici. C'est le rôle de la Phase 4
           (matching) de relier cette image à un pari PENDING existant.
           On se contente de marquer l'analyse comme routée.

    image_type == "unknown"
        -> idem, pas de création automatique : ambiguïté volontairement
           non tranchée ici pour ne pas polluer les statistiques avec de
           faux paris.

    image_type == "ignored"
        -> rien à faire.

Ce module NE FAIT PAS de matching (Phase 4) et NE calcule PAS de
statistiques (Phase 6). Il se contente de la décision "faut-il créer un
pari, et avec quel statut initial".
"""

import json


DEFAULT_CONFIDENCE_THRESHOLD = 0.75


def route_analysis(db_path, analysis: dict, threshold: float, logger) -> str | None:
    """
    Traite une ligne image_analysis et applique la règle de décision.
    Retourne le statut de la décision prise ("created_pending",
    "created_manual_review", "skipped_winning_bet", "skipped_unknown",
    "skipped_ignored"), pour permettre au script appelant de compter les
    résultats. Marque toujours l'analyse comme routée à la fin.
    """
    from db import create_bet, mark_analysis_routed  # import local pour éviter un cycle

    analysis_id = analysis["id"]
    raw_image_id = analysis["raw_image_id"]
    image_type = analysis["image_type"]
    confidence = analysis["confidence"]

    try:
        extracted = json.loads(analysis["extracted_json"])
    except (json.JSONDecodeError, TypeError):
        extracted = {}

    outcome = None

    if image_type == "new_bet":
        status = "PENDING" if (confidence or 0) >= threshold else "MANUAL_REVIEW"

        bet_id = create_bet(
            db_path,
            telegram_message_id=None,  # rattaché via original_image_id, suffisant pour l'instant
            original_image_id=raw_image_id,
            team_1=extracted.get("team_1"),
            team_2=extracted.get("team_2"),
            competition=extracted.get("competition"),
            event_date=extracted.get("event_date"),
            event_time=extracted.get("event_time"),
            market=extracted.get("market"),
            selection=extracted.get("selection"),
            odds=extracted.get("odds"),
            stake=extracted.get("stake"),
            potential_return=extracted.get("potential_return"),
            status=status,
            confidence=confidence,
        )

        logger.info(
            "Pari #%s créé (status=%s, confidence=%s) depuis raw_image_id=%s",
            bet_id, status, confidence, raw_image_id,
        )
        outcome = "created_pending" if status == "PENDING" else "created_manual_review"

    elif image_type == "winning_bet":
        logger.info(
            "Image winning_bet (raw_image_id=%s) en attente de matching (Phase 4)",
            raw_image_id,
        )
        outcome = "skipped_winning_bet"

    elif image_type == "unknown":
        logger.info(
            "Image unknown (raw_image_id=%s) laissée de côté, pas de pari créé",
            raw_image_id,
        )
        outcome = "skipped_unknown"

    else:  # "ignored" ou valeur inattendue
        logger.info(
            "Image ignored (raw_image_id=%s), aucune action", raw_image_id
        )
        outcome = "skipped_ignored"

    mark_analysis_routed(db_path, analysis_id)
    return outcome
