from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_dirs
from .quality import question_is_ready


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL UNIQUE,
            stored_path TEXT NOT NULL,
            page_count INTEGER NOT NULL DEFAULT 0,
            ingested_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            source_pdf TEXT NOT NULL,
            page_number INTEGER,
            question_number TEXT,
            section TEXT NOT NULL,
            topic TEXT NOT NULL,
            passage TEXT,
            question_stem TEXT NOT NULL,
            answer_choices TEXT NOT NULL,
            correct_answer TEXT,
            explanation TEXT,
            trap_type TEXT,
            takeaway_rule TEXT,
            extraction_status TEXT NOT NULL,
            repeat_status TEXT NOT NULL DEFAULT 'New',
            raw_text TEXT NOT NULL,
            content_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            attempted_at TEXT NOT NULL,
            day_number INTEGER NOT NULL,
            section TEXT NOT NULL,
            topic TEXT NOT NULL,
            source_pdf TEXT NOT NULL,
            page_number INTEGER,
            question_number TEXT,
            my_answer TEXT NOT NULL,
            correct_answer TEXT,
            is_correct INTEGER,
            mistake_type TEXT,
            trap_pattern TEXT,
            notes TEXT,
            time_seconds INTEGER,
            reattempt_status TEXT NOT NULL DEFAULT 'No'
        );

        CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);
        CREATE INDEX IF NOT EXISTS idx_questions_repeat_status ON questions(repeat_status);
        CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
        """
    )
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(attempts)").fetchall()
    }
    if "time_seconds" not in existing_columns:
        conn.execute("ALTER TABLE attempts ADD COLUMN time_seconds INTEGER")
    conn.commit()


def upsert_source(conn: sqlite3.Connection, file_name: str, stored_path: str, page_count: int) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO sources (file_name, stored_path, page_count, ingested_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(file_name) DO UPDATE SET
            stored_path = excluded.stored_path,
            page_count = excluded.page_count,
            ingested_at = excluded.ingested_at
        """,
        (file_name, stored_path, page_count, now),
    )
    conn.commit()
    return int(conn.execute("SELECT id FROM sources WHERE file_name = ?", (file_name,)).fetchone()["id"])


def insert_question(conn: sqlite3.Connection, question: dict[str, Any]) -> bool:
    keys = [
        "source_id",
        "source_pdf",
        "page_number",
        "question_number",
        "section",
        "topic",
        "passage",
        "question_stem",
        "answer_choices",
        "correct_answer",
        "explanation",
        "trap_type",
        "takeaway_rule",
        "extraction_status",
        "repeat_status",
        "raw_text",
        "content_hash",
        "created_at",
    ]
    placeholders = ", ".join("?" for _ in keys)
    try:
        conn.execute(
            f"INSERT INTO questions ({', '.join(keys)}) VALUES ({placeholders})",
            tuple(question.get(key) for key in keys),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def fetch_sources(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM sources ORDER BY file_name").fetchall()


def count_questions(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM questions").fetchone()["c"])


def count_questions_by_status(conn: sqlite3.Connection, status: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) AS c FROM questions WHERE extraction_status = ?",
            (status,),
        ).fetchone()["c"]
    )


def topic_counts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT section, topic, extraction_status, repeat_status, COUNT(*) AS count
        FROM questions
        GROUP BY section, topic, extraction_status, repeat_status
        ORDER BY section, topic, extraction_status
        """
    ).fetchall()


def next_question(conn: sqlite3.Connection, section: str, topic: str, search_terms: list[str] | None = None) -> sqlite3.Row | None:
    term_clause = ""
    params: list[object] = [section]
    if search_terms:
        term_clause = " AND (" + " OR ".join("LOWER(question_stem) LIKE ?" for _ in search_terms) + ")"
        params.extend([f"%{term.lower()}%" for term in search_terms])
    if topic in ("Verbal Mixed", "Quant Mixed"):
        row = conn.execute(
            f"""
            SELECT *
            FROM questions
            WHERE section = ?
              AND extraction_status = 'Ready'
              AND LENGTH(TRIM(question_stem)) > 0
              {term_clause}
              AND (
                repeat_status = 'New'
                OR repeat_status = 'Review'
              )
            ORDER BY
                CASE repeat_status WHEN 'Review' THEN 0 ELSE 1 END,
                id
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    else:
        params = [section, topic]
        if search_terms:
            term_clause = " AND (" + " OR ".join("LOWER(question_stem) LIKE ?" for _ in search_terms) + ")"
            params.extend([f"%{term.lower()}%" for term in search_terms])
        row = conn.execute(
            f"""
            SELECT *
            FROM questions
            WHERE section = ?
              AND topic = ?
              AND extraction_status = 'Ready'
              AND LENGTH(TRIM(question_stem)) > 0
              {term_clause}
              AND (
                repeat_status = 'New'
                OR repeat_status = 'Review'
              )
            ORDER BY
                CASE repeat_status WHEN 'Review' THEN 0 ELSE 1 END,
                id
            LIMIT 1
            """,
            tuple(params),
        ).fetchone()
    return row


def reclassify_question_bank(conn: sqlite3.Connection, classify_topic, infer_section) -> int:
    rows = conn.execute("SELECT id, question_stem FROM questions").fetchall()
    changed = 0
    for row in rows:
        topic = classify_topic(row["question_stem"] or "")
        section = infer_section(topic)
        conn.execute(
            "UPDATE questions SET topic = ?, section = ? WHERE id = ?",
            (topic, section, row["id"]),
        )
        changed += 1
    conn.commit()
    return changed


def audit_ready_questions(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT id, topic, passage, question_stem, answer_choices, correct_answer
        FROM questions
        WHERE extraction_status = 'Ready'
        """
    ).fetchall()
    changed = 0
    for row in rows:
        topic = row["topic"] or ""
        passage = row["passage"] or ""
        is_low_confidence = topic in {"Verbal Mixed", "Quant Mixed"} or (
            topic == "RC" and len(passage.strip()) < 300
        )
        if is_low_confidence or not question_is_ready(row["question_stem"] or "", row["answer_choices"] or "", row["correct_answer"]):
            conn.execute(
                "UPDATE questions SET extraction_status = 'Needs Manual Review' WHERE id = ?",
                (row["id"],),
            )
            changed += 1
    conn.commit()
    return changed


def record_attempt(
    conn: sqlite3.Connection,
    question: sqlite3.Row,
    day_number: int,
    my_answer: str,
    notes: str,
    mistake_type: str,
    is_correct: bool | None,
    time_seconds: int | None,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO attempts (
            question_id, attempted_at, day_number, section, topic, source_pdf,
            page_number, question_number, my_answer, correct_answer, is_correct,
            mistake_type, trap_pattern, notes, time_seconds, reattempt_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question["id"],
            now,
            day_number,
            question["section"],
            question["topic"],
            question["source_pdf"],
            question["page_number"],
            question["question_number"],
            my_answer,
            question["correct_answer"],
            None if is_correct is None else int(is_correct),
            mistake_type,
            question["trap_type"],
            notes,
            time_seconds,
            "Yes" if question["repeat_status"] == "Review" else "No",
        ),
    )
    conn.execute(
        "UPDATE questions SET repeat_status = 'Attempted' WHERE id = ? AND repeat_status != 'Review'",
        (question["id"],),
    )
    conn.commit()


def mark_review(conn: sqlite3.Connection, question_id: int, value: bool) -> None:
    conn.execute(
        "UPDATE questions SET repeat_status = ? WHERE id = ?",
        ("Review" if value else "Attempted", question_id),
    )
    conn.commit()


def topic_repeat_counts(
    conn: sqlite3.Connection,
    section: str,
    topic: str,
    search_terms: list[str] | None = None,
) -> list[sqlite3.Row]:
    term_clause = ""
    params: list[object] = [section, topic]
    if search_terms:
        term_clause = " AND (" + " OR ".join("LOWER(question_stem) LIKE ?" for _ in search_terms) + ")"
        params.extend([f"%{term.lower()}%" for term in search_terms])
    return conn.execute(
        f"""
        SELECT repeat_status, COUNT(*) AS count
        FROM questions
        WHERE section = ?
          AND topic = ?
          AND extraction_status = 'Ready'
          {term_clause}
        GROUP BY repeat_status
        ORDER BY repeat_status
        """,
        tuple(params),
    ).fetchall()


def mark_attempted_topic_review(
    conn: sqlite3.Connection,
    section: str,
    topic: str,
    search_terms: list[str] | None = None,
) -> int:
    term_clause = ""
    params: list[object] = [section, topic]
    if search_terms:
        term_clause = " AND (" + " OR ".join("LOWER(question_stem) LIKE ?" for _ in search_terms) + ")"
        params.extend([f"%{term.lower()}%" for term in search_terms])
    cursor = conn.execute(
        f"""
        UPDATE questions
        SET repeat_status = 'Review'
        WHERE section = ?
          AND topic = ?
          AND extraction_status = 'Ready'
          AND repeat_status = 'Attempted'
          {term_clause}
        """,
        tuple(params),
    )
    conn.commit()
    return int(cursor.rowcount or 0)


def update_question_manual_fields(
    conn: sqlite3.Connection,
    question_id: int,
    section: str,
    topic: str,
    passage: str | None,
    question_stem: str,
    answer_choices: str,
    correct_answer: str | None,
    explanation: str | None,
    trap_type: str | None,
    takeaway_rule: str | None,
    extraction_status: str,
    repeat_status: str,
) -> None:
    conn.execute(
        """
        UPDATE questions
        SET section = ?,
            topic = ?,
            passage = ?,
            question_stem = ?,
            answer_choices = ?,
            correct_answer = ?,
            explanation = ?,
            trap_type = ?,
            takeaway_rule = ?,
            extraction_status = ?,
            repeat_status = ?
        WHERE id = ?
        """,
        (
            section,
            topic,
            passage,
            question_stem,
            answer_choices,
            correct_answer,
            explanation,
            trap_type,
            takeaway_rule,
            extraction_status,
            repeat_status,
            question_id,
        ),
    )
    conn.commit()


def question_bank_rows(conn: sqlite3.Connection, status: str = "Ready") -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            id, source_pdf, page_number, question_number, section, topic,
            extraction_status, repeat_status, SUBSTR(question_stem, 1, 140) AS question_preview
        FROM questions
        WHERE extraction_status = ?
        ORDER BY id DESC
        """,
        (status,),
    ).fetchall()


def attempts_frame(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM attempts ORDER BY attempted_at DESC").fetchall()


def dashboard_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    totals = conn.execute(
        """
        SELECT
            COUNT(*) AS attempted,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct
        FROM attempts
        """
    ).fetchone()
    by_topic = conn.execute(
        """
        SELECT
            section,
            topic,
            COUNT(*) AS attempted,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
            ROUND(AVG(time_seconds), 1) AS avg_time_seconds
        FROM attempts
        GROUP BY section, topic
        ORDER BY section, topic
        """
    ).fetchall()
    traps = conn.execute(
        """
        SELECT COALESCE(NULLIF(trap_pattern, ''), 'Unlabeled') AS trap_pattern, COUNT(*) AS count
        FROM attempts
        WHERE is_correct = 0 OR is_correct IS NULL
        GROUP BY COALESCE(NULLIF(trap_pattern, ''), 'Unlabeled')
        ORDER BY count DESC
        LIMIT 10
        """
    ).fetchall()
    review = conn.execute(
        """
        SELECT id, source_pdf, page_number, question_number, section, topic, repeat_status
        FROM questions
        WHERE repeat_status = 'Review'
        ORDER BY id
        """
    ).fetchall()
    return {"totals": totals, "by_topic": by_topic, "traps": traps, "review": review}
