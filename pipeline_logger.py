"""
Journal des traitements, au format décrit en section 16 :

    [14:01] Nouvelle image détectée
    [14:01] Analyse IA lancée
    ...

Écrit à la fois sur la console et dans un fichier log (append), pour
pouvoir être relu et corriger les erreurs plus tard (objectif explicite
de la section 16).
"""

import logging
from pathlib import Path


def setup_logger(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("bet_tracker")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        # déjà configuré (évite les doublons de handlers si appelé 2x)
        return logger

    formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
