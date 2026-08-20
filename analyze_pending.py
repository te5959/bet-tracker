"""
Phase 2 — Script de traitement par lot des images en attente d'analyse.

Usage:
    python analyze_pending.py                # traite jusqu'à 20 images
    python analyze_pending.py --limit 100
    python analyze_pending.py --loop 30       # tourne en continu, vérifie
                                               # toutes les 30 secondes

Ce script est volontairement séparé du listener Telegram (Phase 1) pour
pouvoir être testé et validé indépendamment, conformément à la consigne
de valider chaque étape avant de l'intégrer au pipeline continu.
"""

import argparse
import json
import time

from config import load_settings
from db import init_db, get_captured_images, save_image_analysis
from pipeline_logger import setup_logger
from ai_vision import analyze_image


def process_batch(settings, logger, limit: int) -> int:
    """Traite jusqu'à `limit` images CAPTURED. Retourne le nombre traité."""
    images = get_captured_images(settings.db_path, limit=limit)

    if not images:
        return 0

    logger.info("Analyse IA lancée sur %s image(s) en attente", len(images))

    for image in images:
        raw_image_id = image["id"]
        file_path = image["file_path"]

        logger.info(
            "Analyse de l'image raw_image_id=%s (%s)", raw_image_id, file_path
        )

        try:
            result = analyze_image(
                image_path=__import__("pathlib").Path(file_path),
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )
        except Exception as exc:
            logger.info(
                "Échec de l'analyse pour raw_image_id=%s : %s", raw_image_id, exc
            )
            save_image_analysis(
                settings.db_path,
                raw_image_id=raw_image_id,
                image_type=None,
                confidence=None,
                extracted_json="{}",
                model_used=settings.anthropic_model,
                error=str(exc),
            )
            continue

        image_type = result.get("image_type")
        confidence = result.get("confidence")

        save_image_analysis(
            settings.db_path,
            raw_image_id=raw_image_id,
            image_type=image_type,
            confidence=confidence,
            extracted_json=json.dumps(result, ensure_ascii=False),
            model_used=settings.anthropic_model,
        )

        confidence_pct = f"{confidence * 100:.0f}%" if confidence is not None else "?"
        logger.info(
            "Classification : %s | Confidence : %s", image_type, confidence_pct
        )

    return len(images)


def main():
    parser = argparse.ArgumentParser(description="Phase 2 - Analyse IA des captures")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        help="Si > 0, tourne en continu avec ce nombre de secondes entre chaque vérification",
    )
    args = parser.parse_args()

    settings = load_settings()
    init_db(settings.db_path)
    logger = setup_logger(settings.log_file)

    if args.loop > 0:
        logger.info(
            "Mode continu activé (vérification toutes les %ss)", args.loop
        )
        while True:
            processed = process_batch(settings, logger, args.limit)
            if processed == 0:
                time.sleep(args.loop)
    else:
        processed = process_batch(settings, logger, args.limit)
        if processed == 0:
            logger.info("Aucune image en attente d'analyse")


if __name__ == "__main__":
    main()
