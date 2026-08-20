"""
Couche d'accès à la base de données SQLite.

Deux tables sont créées dès la Phase 1 :

- raw_images : une ligne par image Telegram capturée. C'est la table
  utilisée activement en Phase 1 (capture + anti-doublon).
- bets : le schéma complet décrit en section 10 du cahier des charges.
  Créée dès maintenant pour figer le schéma, mais elle ne sera
  réellement peuplée qu'à partir de la Phase 2/3 (analyse IA +
  classification). En Phase 1 elle reste vide.

Choix : SQLite pour la V1 (voir justification dans la réponse projet).
Le module est écrit de façon à pouvoir être remplacé par un adaptateur
Postgres plus tard sans changer l'API exposée aux autres modules
(get_connection, init_db, etc.).
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_message_id INTEGER NOT NULL UNIQUE,
    telegram_date TEXT,
    file_path TEXT NOT NULL,
    downloaded_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- CAPTURED -> pas encore analysé (Phase 1)
    -- ANALYZED -> passé par l'IA vision (Phase 2)
    status TEXT NOT NULL DEFAULT 'CAPTURED'
);

CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_message_id INTEGER,
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    original_image_id INTEGER REFERENCES raw_images(id),

    team_1 TEXT,
    team_2 TEXT,
    competition TEXT,
    event_date TEXT,
    event_time TEXT,

    market TEXT,
    selection TEXT,
    odds REAL,
    stake REAL,
    potential_return REAL,

    -- PENDING | WON | LOST | UNKNOWN | IGNORED | MANUAL_REVIEW
    status TEXT NOT NULL DEFAULT 'PENDING',
    confidence REAL,

    winning_image_id INTEGER REFERENCES raw_images(id),
    confirmed_payout REAL,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
CREATE INDEX IF NOT EXISTS idx_raw_images_status ON raw_images(status);

-- Phase 2 : résultat brut de l'analyse IA Vision pour chaque image.
-- Une ligne par image analysée. On garde le JSON complet retourné par le
-- modèle pour audit / réanalyse future (règle 8 du cahier des charges),
-- même si la décision finale de classification (Phase 3) n'est pas
-- encore appliquée ici.
CREATE TABLE IF NOT EXISTS image_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_image_id INTEGER NOT NULL REFERENCES raw_images(id),
    image_type TEXT,        -- new_bet | winning_bet | unknown | ignored (brut, avant classification finale)
    confidence REAL,
    extracted_json TEXT NOT NULL,  -- réponse structurée complète du modèle, en JSON
    model_used TEXT,
    analyzed_at TEXT NOT NULL DEFAULT (datetime('now')),
    error TEXT              -- rempli si l'analyse a échoué (permet de repérer les images à revoir)
);

CREATE INDEX IF NOT EXISTS idx_image_analysis_raw_image ON image_analysis(raw_image_id);
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_connection(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def is_message_processed(db_path: Path, telegram_message_id: int) -> bool:
    """Anti-doublon : un message Telegram ne doit être traité qu'une fois
    (section 11, point 1 et section 12)."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM raw_images WHERE telegram_message_id = ?",
            (telegram_message_id,),
        ).fetchone()
        return row is not None


def insert_raw_image(
    db_path: Path,
    telegram_message_id: int,
    telegram_date: str,
    file_path: str,
) -> int:
    """Enregistre une image brute capturée. Retourne l'id inséré.

    Peut lever sqlite3.IntegrityError si le message a déjà été inséré
    entre-temps (contrainte UNIQUE) — c'est volontaire, ça sert de
    filet de sécurité en plus du check is_message_processed().
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO raw_images (telegram_message_id, telegram_date, file_path)
            VALUES (?, ?, ?)
            """,
            (telegram_message_id, telegram_date, file_path),
        )
        conn.commit()
        return cur.lastrowid


def count_raw_images(db_path: Path) -> int:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM raw_images").fetchone()
        return row["c"]


# --- Phase 2 : images en attente d'analyse IA ---

def get_captured_images(db_path: Path, limit: int = 20):
    """Retourne les images pas encore analysées (status='CAPTURED'),
    les plus anciennes en premier."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, telegram_message_id, telegram_date, file_path
            FROM raw_images
            WHERE status = 'CAPTURED'
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def save_image_analysis(
    db_path: Path,
    raw_image_id: int,
    image_type: str | None,
    confidence: float | None,
    extracted_json: str,
    model_used: str,
    error: str | None = None,
) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO image_analysis
                (raw_image_id, image_type, confidence, extracted_json, model_used, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (raw_image_id, image_type, confidence, extracted_json, model_used, error),
        )
        # L'image est marquée ANALYZED qu'il y ait eu succès ou erreur :
        # en cas d'erreur, le champ `error` de image_analysis permet de la repérer
        # pour un nouveau traitement manuel, sans bloquer la boucle sur cette image.
        new_status = "ANALYSIS_FAILED" if error else "ANALYZED"
        conn.execute(
            "UPDATE raw_images SET status = ? WHERE id = ?",
            (new_status, raw_image_id),
        )
        conn.commit()
        return cur.lastrowid
