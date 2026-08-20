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
        # Migration douce : ajoute la colonne routed_at si elle n'existe pas
        # encore (bases créées avant la Phase 3). SQLite ne supporte pas
        # "ADD COLUMN IF NOT EXISTS", d'où le try/except.
        try:
            conn.execute("ALTER TABLE image_analysis ADD COLUMN routed_at TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # colonne déjà présente


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


# --- Phase 3 : routage des analyses vers la création de paris ---

def get_unrouted_analyses(db_path: Path, limit: int = 20):
    """Retourne les analyses réussies (error IS NULL) pas encore routées
    (routed_at IS NULL), les plus anciennes en premier. Une analyse en échec
    n'a rien à router : elle doit d'abord être réanalysée (cf. Phase 2)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, raw_image_id, image_type, confidence, extracted_json
            FROM image_analysis
            WHERE routed_at IS NULL AND error IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_analysis_routed(db_path: Path, analysis_id: int) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE image_analysis SET routed_at = datetime('now') WHERE id = ?",
            (analysis_id,),
        )
        conn.commit()


def create_bet(
    db_path: Path,
    telegram_message_id: int | None,
    original_image_id: int,
    team_1: str | None,
    team_2: str | None,
    competition: str | None,
    event_date: str | None,
    event_time: str | None,
    market: str | None,
    selection: str | None,
    odds: float | None,
    stake: float | None,
    potential_return: float | None,
    status: str,
    confidence: float | None,
) -> int:
    """Crée un nouveau pari (section 10 du cahier des charges).
    Statut attendu ici : PENDING ou MANUAL_REVIEW (jamais WON/LOST, qui
    relèvent des Phases 4 et 5)."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO bets (
                telegram_message_id, original_image_id,
                team_1, team_2, competition, event_date, event_time,
                market, selection, odds, stake, potential_return,
                status, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_message_id, original_image_id,
                team_1, team_2, competition, event_date, event_time,
                market, selection, odds, stake, potential_return,
                status, confidence,
            ),
        )
        conn.commit()
        return cur.lastrowid


def get_raw_image(db_path: Path, raw_image_id: int) -> dict | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM raw_images WHERE id = ?", (raw_image_id,)
        ).fetchone()
        return dict(row) if row else None


def count_bets_by_status(db_path: Path) -> dict:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM bets GROUP BY status"
        ).fetchall()
        return {row["status"]: row["c"] for row in rows}


# --- Phase 4 : matching image gagnante <-> pari existant ---

def get_open_bets(db_path: Path, statuses=("PENDING",)):
    """Retourne les paris encore ouverts (candidats au matching), les plus
    anciens en premier — utile pour le départage en cas d'égalité de score
    (section 9 : privilégier le pari le plus ancien)."""
    placeholders = ",".join("?" for _ in statuses)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT id, team_1, team_2, competition, market, selection,
                   odds, stake, potential_return, detected_at, status
            FROM bets
            WHERE status IN ({placeholders})
            ORDER BY id ASC
            """,
            tuple(statuses),
        ).fetchall()
        return [dict(row) for row in rows]


def get_unmatched_winning_analyses(db_path: Path, limit: int = 20):
    """Retourne les analyses classées winning_bet, déjà routées par la
    Phase 3, dont l'image n'est encore reliée à aucun pari (bets.winning_image_id).
    Le fait de ne pas persister un statut "échec de matching" est volontaire :
    si aucun bon candidat n'existe encore, on veut pouvoir retenter plus tard
    (ex: si le new_bet correspondant arrive après coup)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, raw_image_id, image_type, confidence, extracted_json
            FROM image_analysis
            WHERE image_type = 'winning_bet'
              AND routed_at IS NOT NULL
              AND error IS NULL
              AND raw_image_id NOT IN (
                  SELECT winning_image_id FROM bets WHERE winning_image_id IS NOT NULL
              )
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_bet_won(
    db_path: Path,
    bet_id: int,
    winning_image_id: int,
    confirmed_payout: float | None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE bets
            SET status = 'WON',
                winning_image_id = ?,
                confirmed_payout = ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (winning_image_id, confirmed_payout, bet_id),
        )
        conn.commit()


# --- Phase 5 : détection des paris perdus par délai ---

def get_expirable_bets(db_path: Path, delay_hours: int):
    """Retourne les paris PENDING détectés il y a plus de `delay_hours`
    heures, encore sans confirmation de gain (règle 6, section 13).
    Ne touche pas MANUAL_REVIEW : ces paris restent en attente d'un
    regard humain plutôt que d'être basculés automatiquement."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, team_1, team_2, detected_at
            FROM bets
            WHERE status = 'PENDING'
              AND detected_at <= datetime('now', ?)
            ORDER BY id ASC
            """,
            (f"-{delay_hours} hours",),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_bet_lost(db_path: Path, bet_id: int) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE bets
            SET status = 'LOST', updated_at = datetime('now')
            WHERE id = ?
            """,
            (bet_id,),
        )
        conn.commit()
