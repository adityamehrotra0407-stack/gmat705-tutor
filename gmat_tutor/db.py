from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import json
import re
import sqlite3
import zlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_dirs
from .quality import question_is_ready

LETTERS = ["A", "B", "C", "D", "E"]
BUNDLED_QUESTION_CSV = Path(__file__).resolve().parent.parent / "data" / "seed" / "combined_ready_questions.csv"
SUPPLEMENTAL_QUESTION_FILES = [
    Path(__file__).resolve().parent.parent / "data" / "seed" / "supplemental_assumption_questions.csv",
    Path(__file__).resolve().parent.parent / "data" / "seed" / "supplemental_assumption_questions.csv.zlib.b64",
]
SUPPLEMENTAL_SEED_PART_COUNT = 13
CLASSIFICATION_REPAIR_STATE_NAME = "__classification_repair__"
CLASSIFICATION_REPAIR_SIGNATURE = "source-aware-section-topic-v3"


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
            difficulty TEXT,
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

        CREATE TABLE IF NOT EXISTS study_task_status (
            day_number INTEGER NOT NULL,
            section TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (day_number, section)
        );

        CREATE TABLE IF NOT EXISTS seed_state (
            seed_name TEXT PRIMARY KEY,
            file_signature TEXT NOT NULL,
            synced_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_questions_topic ON questions(topic);
        CREATE INDEX IF NOT EXISTS idx_questions_repeat_status ON questions(repeat_status);
        CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id);
        CREATE INDEX IF NOT EXISTS idx_study_task_status_day ON study_task_status(day_number);
        """
    )
    existing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(attempts)").fetchall()
    }
    if "time_seconds" not in existing_columns:
        conn.execute("ALTER TABLE attempts ADD COLUMN time_seconds INTEGER")
    question_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(questions)").fetchall()
    }
    if "difficulty" not in question_columns:
        conn.execute("ALTER TABLE questions ADD COLUMN difficulty TEXT")
    question_count_before_seed = conn.execute("SELECT COUNT(*) AS count FROM questions").fetchone()["count"]
    conn.commit()
    seed_bundled_questions(conn)
    run_classification_repair_once(conn, repair_existing_rows=question_count_before_seed > 0)


def seed_bundled_questions(conn: sqlite3.Connection) -> int:
    changed = seed_questions_if_empty(conn, BUNDLED_QUESTION_CSV)
    for seed_path in SUPPLEMENTAL_QUESTION_FILES:
        changed += seed_questions_if_empty(conn, seed_path)
    return changed


def _seed_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _seed_hash(source_name: str, stem: str, choices_json: str) -> str:
    h = hashlib.sha256()
    h.update(source_name.encode("utf-8", errors="ignore"))
    h.update(stem.encode("utf-8", errors="ignore"))
    h.update(choices_json.encode("utf-8", errors="ignore"))
    return h.hexdigest()


VERBAL_SOURCE_RE = re.compile(
    r"(^|[\s_\-])(cr|rc|lsat)([\s_\-.]|$)|critical reasoning|reading comprehension|verbal",
    re.IGNORECASE,
)
QUANT_SOURCE_RE = re.compile(
    r"quant|number|geometry|statistics|probability|ratio|percent|set|interest|speed|distance|"
    r"algebra|inequal|permutation|combination|combinatorics",
    re.IGNORECASE,
)


def normalize_section_topic(
    section: str | None,
    topic: str | None,
    question_stem: str,
    source_pdf: str = "",
    passage: str | None = None,
) -> tuple[str, str]:
    from .classifiers import QUANT_TOPICS, classify_topic, infer_section

    raw_topic = _seed_text(topic)
    raw_section = _seed_text(section)
    text_for_classification = " ".join(part for part in [passage or "", question_stem or ""] if part)
    classified_topic = classify_topic(text_for_classification)
    classified_section = infer_section(classified_topic)
    raw_topic_section = infer_section(raw_topic) if raw_topic else ""
    source_name = source_pdf or ""
    source_says_verbal = bool(VERBAL_SOURCE_RE.search(source_name))
    source_says_quant = bool(QUANT_SOURCE_RE.search(source_name))

    if source_says_verbal and not source_says_quant:
        if classified_section == "Verbal":
            return "Verbal", classified_topic
        return "Verbal", raw_topic if raw_topic and raw_topic not in QUANT_TOPICS else "Verbal Mixed"

    if source_says_quant and not source_says_verbal:
        if classified_section == "Quant":
            return "Quant", classified_topic
        if raw_topic and raw_topic in QUANT_TOPICS:
            return "Quant", raw_topic
        return "Quant", "Quant Mixed"

    if raw_section == "Quant" and classified_section == "Verbal":
        return "Verbal", classified_topic

    if raw_section == "Verbal" and classified_section == "Quant" and raw_topic_section == "Quant":
        return "Quant", classified_topic

    if raw_section in {"Quant", "Verbal"}:
        return raw_section, raw_topic or ("Quant Mixed" if raw_section == "Quant" else "Verbal Mixed")

    if raw_topic:
        return raw_topic_section, raw_topic

    return classified_section, classified_topic


def seed_questions_if_empty(conn: sqlite3.Connection, csv_path: Path = BUNDLED_QUESTION_CSV) -> int:
    if not _seed_path_exists(csv_path):
        return 0
    file_signature = _file_signature(csv_path)
    state = conn.execute(
        "SELECT file_signature FROM seed_state WHERE seed_name = ?",
        (csv_path.name,),
    ).fetchone()
    question_count = conn.execute("SELECT COUNT(*) AS count FROM questions").fetchone()["count"]
    if question_count > 0 and state and state["file_signature"] == file_signature:
        return 0

    source_id = upsert_source(conn, csv_path.name, f"bundled://{csv_path.name}", 0)
    changed = 0
    now = datetime.now().isoformat(timespec="seconds")
    for index, row in enumerate(_seed_rows(csv_path), start=1):
        question_stem = _seed_text(row.get("question"))
        source_pdf = _seed_text(row.get("source_file")) or csv_path.name
        passage = _seed_text(row.get("passage")) or None
        section, topic = normalize_section_topic(
            _seed_text(row.get("section")),
            _seed_text(row.get("topic")),
            question_stem,
            source_pdf,
            passage,
        )
        choices = [{"letter": letter, "text": _seed_text(row.get(letter))} for letter in LETTERS]
        choices_json = json.dumps(choices, ensure_ascii=False, indent=2)
        correct = _seed_text(row.get("correct_answer")).upper()[:1]
        correct = correct if correct in LETTERS else None
        seed_status = _seed_text(row.get("status"))
        status = "Ready" if question_is_ready(question_stem, choices_json, correct) else "Needs Manual Review"
        if seed_status == "Needs Manual Review":
            status = "Needs Manual Review"
        page_text = _seed_text(row.get("page_number"))
        page_number = int(page_text) if page_text.isdigit() else None
        raw_text = _seed_text(row.get("raw_text")) or "\n".join(
            [question_stem, *[f"{choice['letter']}. {choice['text']}" for choice in choices], f"Answer: {correct or ''}"]
        )
        question = {
            "source_id": source_id,
            "source_pdf": source_pdf,
            "page_number": page_number,
            "question_number": _seed_text(row.get("question_number")) or str(index),
            "section": section,
            "topic": topic,
            "passage": passage,
            "question_stem": question_stem,
            "answer_choices": choices_json,
            "correct_answer": correct,
            "explanation": _seed_text(row.get("explanation")) or None,
            "trap_type": _seed_text(row.get("trap_type")) or None,
            "takeaway_rule": _seed_text(row.get("takeaway_rule")) or None,
            "difficulty": _seed_text(row.get("Difficulty")) or _seed_text(row.get("difficulty")) or None,
            "extraction_status": status,
            "repeat_status": "New",
            "raw_text": raw_text,
            "content_hash": _seed_hash(source_pdf, question_stem, choices_json),
            "created_at": now,
        }
        if upsert_seed_question(conn, question, commit=False):
            changed += 1
    conn.execute(
        """
        INSERT INTO seed_state (seed_name, file_signature, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(seed_name) DO UPDATE SET
            file_signature = excluded.file_signature,
            synced_at = excluded.synced_at
        """,
        (csv_path.name, file_signature, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return changed


def _file_signature(path: Path) -> str:
    h = hashlib.sha256()
    parts = _seed_payload_parts(path)
    if parts and not path.exists():
        for part in parts:
            stat = part.stat()
            h.update(part.name.encode("utf-8"))
            h.update(str(stat.st_size).encode("ascii"))
            h.update(str(int(stat.st_mtime)).encode("ascii"))
    else:
        stat = path.stat()
        h.update(str(stat.st_size).encode("ascii"))
        h.update(str(int(stat.st_mtime)).encode("ascii"))
    return h.hexdigest()


def _seed_payload_part_files(path: Path, index: int) -> list[Path]:
    chunks = sorted(path.parent.glob(f"{path.name}.part{index:02d}.chunk*"))
    if chunks:
        suffixes = [chunk.name.rsplit(".chunk", 1)[-1] for chunk in chunks]
        expected = [f"{chunk_index:02d}" for chunk_index in range(1, len(chunks) + 1)]
        if suffixes != expected:
            return []
        return chunks
    full_part = path.parent / f"{path.name}.part{index:02d}"
    if full_part.exists():
        return [full_part]
    return []


def _seed_payload_parts(path: Path) -> list[Path]:
    files: list[Path] = []
    for index in range(1, SUPPLEMENTAL_SEED_PART_COUNT + 1):
        part_files = _seed_payload_part_files(path, index)
        if not part_files:
            return []
        files.extend(part_files)
    return files


def _seed_payload_complete(path: Path) -> bool:
    if path.exists():
        return True
    parts = _seed_payload_parts(path)
    return bool(parts)


def _seed_path_exists(path: Path) -> bool:
    if path.name.endswith(".zlib.b64"):
        return _seed_payload_complete(path)
    return path.exists()


def _seed_payload_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="ascii")
    if not _seed_payload_complete(path):
        return ""
    return "".join(
        "".join(part.read_text(encoding="ascii").split())
        for part in _seed_payload_parts(path)
    )


def _seed_rows(path: Path) -> list[dict[str, str]]:
    if path.name.endswith(".zlib.b64"):
        encoded = _seed_payload_text(path)
        if not encoded:
            return []
        try:
            payload = base64.b64decode(encoded, validate=True)
            text = zlib.decompress(payload).decode("utf-8-sig")
        except (ValueError, binascii.Error, zlib.error, UnicodeDecodeError):
            return []
        return list(csv.DictReader(io.StringIO(text)))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def upsert_seed_question(conn: sqlite3.Connection, question: dict[str, Any], commit: bool = True) -> bool:
    existing = conn.execute(
        "SELECT id FROM questions WHERE content_hash = ?",
        (question["content_hash"],),
    ).fetchone()
    if not existing:
        return insert_question(conn, question, commit=commit)
    conn.execute(
        """
        UPDATE questions
        SET source_id = ?,
            source_pdf = ?,
            page_number = ?,
            question_number = ?,
            section = ?,
            topic = ?,
            passage = ?,
            question_stem = ?,
            answer_choices = ?,
            correct_answer = ?,
            explanation = ?,
            trap_type = ?,
            takeaway_rule = ?,
            difficulty = ?,
            extraction_status = ?,
            raw_text = ?
        WHERE content_hash = ?
        """,
        (
            question["source_id"],
            question["source_pdf"],
            question["page_number"],
            question["question_number"],
            question["section"],
            question["topic"],
            question["passage"],
            question["question_stem"],
            question["answer_choices"],
            question["correct_answer"],
            question["explanation"],
            question["trap_type"],
            question["takeaway_rule"],
            question["difficulty"],
            question["extraction_status"],
            question["raw_text"],
            question["content_hash"],
        ),
    )
    if commit:
        conn.commit()
    return True


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


def insert_question(conn: sqlite3.Connection, question: dict[str, Any], commit: bool = True) -> bool:
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
        "difficulty",
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
        if commit:
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


def _stage_order_sql(day_stage: int) -> str:
    if day_stage <= 1:
        return """
            CASE
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%505-605%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%easy%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%600%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%605-705%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%medium%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%705-805%' THEN 2
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%700%' THEN 2
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%hard%' THEN 2
                ELSE 1
            END,
            id ASC
        """
    if day_stage == 2:
        return """
            CASE
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%605-705%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%medium%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%705-805%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%700%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%hard%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%505-605%' THEN 2
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%easy%' THEN 2
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%600%' THEN 2
                ELSE 1
            END,
            id ASC
        """
    return """
        CASE
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%705-805%' THEN 0
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%700%' THEN 0
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%800%' THEN 0
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%hard%' THEN 0
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%605-705%' THEN 1
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%medium%' THEN 1
            ELSE 2
        END,
        id ASC
    """


def _candidate_offset(
    conn: sqlite3.Connection,
    where_sql: str,
    params: tuple[object, ...],
    day_stage: int,
    day_number: int = 1,
    day_quota: int = 1,
) -> int:
    count = int(conn.execute(f"SELECT COUNT(*) AS c FROM questions WHERE {where_sql}", params).fetchone()["c"])
    if count <= 1:
        return 0
    if day_stage <= 1:
        base_offset = 0
    elif day_stage == 2:
        base_offset = count // 3
    else:
        base_offset = (count * 2) // 3
    # Keep day changes from wrapping around small topic pools by a large quota.
    # The quota is a target count, not a stable question offset.
    day_shift = max(0, day_number - 1) * 7
    stage_shift = max(0, day_stage - 1) * 3
    return (base_offset + day_shift + stage_shift) % count


def _candidate_count(conn: sqlite3.Connection, where_sql: str, params: tuple[object, ...]) -> int:
    return int(conn.execute(f"SELECT COUNT(*) AS c FROM questions WHERE {where_sql}", params).fetchone()["c"])


def next_question(
    conn: sqlite3.Connection,
    section: str,
    topic: str,
    search_terms: list[str] | None = None,
    day_stage: int = 1,
    day_number: int = 1,
    day_quota: int = 1,
) -> sqlite3.Row | None:
    term_clause = ""
    params: list[object] = [section]
    if search_terms:
        term_clause = " AND (" + " OR ".join("LOWER(question_stem) LIKE ?" for _ in search_terms) + ")"
        params.extend([f"%{term.lower()}%" for term in search_terms])
    if topic in ("Verbal Mixed", "Quant Mixed"):
        where_sql = f"""
            section = ?
            AND extraction_status = 'Ready'
            AND LENGTH(TRIM(question_stem)) > 0
            {term_clause}
            AND (repeat_status = 'New' OR repeat_status = 'Review')
        """
        query_params = tuple(params)
        if search_terms and _candidate_count(conn, where_sql, query_params) < 8:
            return next_question(conn, section, topic, None, day_stage, day_number, day_quota)
        offset = _candidate_offset(conn, where_sql, query_params, day_stage, day_number, day_quota)
        row = conn.execute(
            f"""
            SELECT *
            FROM questions
            WHERE {where_sql}
            ORDER BY
                CASE repeat_status WHEN 'Review' THEN 0 ELSE 1 END,
                {_stage_order_sql(day_stage)}
            LIMIT 1 OFFSET ?
            """,
            (*query_params, offset),
        ).fetchone()
    else:
        params = [section, topic]
        if search_terms:
            term_clause = " AND (" + " OR ".join("LOWER(question_stem) LIKE ?" for _ in search_terms) + ")"
            params.extend([f"%{term.lower()}%" for term in search_terms])
        where_sql = f"""
            section = ?
            AND topic = ?
            AND extraction_status = 'Ready'
            AND LENGTH(TRIM(question_stem)) > 0
            {term_clause}
            AND (repeat_status = 'New' OR repeat_status = 'Review')
        """
        query_params = tuple(params)
        if search_terms and _candidate_count(conn, where_sql, query_params) < 8:
            return next_question(conn, section, topic, None, day_stage, day_number, day_quota)
        offset = _candidate_offset(conn, where_sql, query_params, day_stage, day_number, day_quota)
        row = conn.execute(
            f"""
            SELECT *
            FROM questions
            WHERE {where_sql}
            ORDER BY
                CASE repeat_status WHEN 'Review' THEN 0 ELSE 1 END,
                {_stage_order_sql(day_stage)}
            LIMIT 1 OFFSET ?
            """,
            (*query_params, offset),
        ).fetchone()
    return row


def reclassify_question_bank(conn: sqlite3.Connection, classify_topic, infer_section) -> int:
    rows = conn.execute("SELECT id, source_pdf, section, topic, passage, question_stem FROM questions").fetchall()
    changed = 0
    for row in rows:
        section, topic = normalize_section_topic(
            row["section"],
            row["topic"],
            row["question_stem"] or "",
            row["source_pdf"] or "",
            row["passage"] or "",
        )
        if section != row["section"] or topic != row["topic"]:
            conn.execute(
                "UPDATE questions SET topic = ?, section = ? WHERE id = ?",
                (topic, section, row["id"]),
            )
            changed += 1
    conn.commit()
    return changed


def repair_question_sections(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT id, source_pdf, section, topic, passage, question_stem
        FROM questions
        """
    ).fetchall()
    changed = 0
    for row in rows:
        section, topic = normalize_section_topic(
            row["section"],
            row["topic"],
            row["question_stem"] or "",
            row["source_pdf"] or "",
            row["passage"] or "",
        )
        if section != row["section"] or topic != row["topic"]:
            conn.execute(
                "UPDATE questions SET section = ?, topic = ? WHERE id = ?",
                (section, topic, row["id"]),
            )
            changed += 1
    conn.commit()
    return changed


def run_classification_repair_once(conn: sqlite3.Connection, repair_existing_rows: bool = True) -> int:
    state = conn.execute(
        "SELECT file_signature FROM seed_state WHERE seed_name = ?",
        (CLASSIFICATION_REPAIR_STATE_NAME,),
    ).fetchone()
    if state and state["file_signature"] == CLASSIFICATION_REPAIR_SIGNATURE:
        return 0

    changed = repair_question_sections(conn) if repair_existing_rows else 0
    conn.execute(
        """
        INSERT INTO seed_state (seed_name, file_signature, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(seed_name) DO UPDATE SET
            file_signature = excluded.file_signature,
            synced_at = excluded.synced_at
        """,
        (
            CLASSIFICATION_REPAIR_STATE_NAME,
            CLASSIFICATION_REPAIR_SIGNATURE,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
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
        is_low_confidence = topic == "RC" and len(passage.strip()) < 300
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


def day_section_progress(conn: sqlite3.Connection, day_number: int, section: str) -> sqlite3.Row:
    return conn.execute(
        """
        SELECT
            COUNT(*) AS attempted,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
            ROUND(AVG(time_seconds), 1) AS avg_time_seconds
        FROM attempts
        WHERE day_number = ?
          AND section = ?
        """,
        (day_number, section),
    ).fetchone()


def daily_progress_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            day_number,
            section,
            COUNT(*) AS attempted,
            SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) AS correct,
            ROUND(AVG(time_seconds), 1) AS avg_time_seconds
        FROM attempts
        GROUP BY day_number, section
        ORDER BY day_number DESC, section
        """
    ).fetchall()


def get_task_status(conn: sqlite3.Connection, day_number: int, section: str) -> str:
    row = conn.execute(
        """
        SELECT status
        FROM study_task_status
        WHERE day_number = ?
          AND section = ?
        """,
        (day_number, section),
    ).fetchone()
    return str(row["status"]) if row else "Pending"


def set_task_status(conn: sqlite3.Connection, day_number: int, section: str, status: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO study_task_status (day_number, section, status, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(day_number, section) DO UPDATE SET
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (day_number, section, status, now),
    )
    conn.commit()


def study_task_status_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT day_number, section, status, updated_at
        FROM study_task_status
        ORDER BY day_number DESC, section
        """
    ).fetchall()


def export_progress_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    attempts = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                questions.content_hash,
                attempts.attempted_at,
                attempts.day_number,
                attempts.section,
                attempts.topic,
                attempts.source_pdf,
                attempts.page_number,
                attempts.question_number,
                attempts.my_answer,
                attempts.correct_answer,
                attempts.is_correct,
                attempts.mistake_type,
                attempts.trap_pattern,
                attempts.notes,
                attempts.time_seconds,
                attempts.reattempt_status
            FROM attempts
            JOIN questions ON questions.id = attempts.question_id
            ORDER BY attempts.id
            """
        ).fetchall()
    ]
    repeat_statuses = [
        dict(row)
        for row in conn.execute(
            """
            SELECT content_hash, repeat_status
            FROM questions
            WHERE repeat_status != 'New'
            ORDER BY id
            """
        ).fetchall()
    ]
    task_statuses = [dict(row) for row in study_task_status_rows(conn)]
    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "attempts": attempts,
        "repeat_statuses": repeat_statuses,
        "study_task_status": task_statuses,
    }


def restore_progress_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> dict[str, int]:
    if not isinstance(snapshot, dict):
        raise ValueError("Progress backup is not valid JSON.")
    attempts = snapshot.get("attempts", [])
    repeat_statuses = snapshot.get("repeat_statuses", [])
    task_statuses = snapshot.get("study_task_status", [])
    if not isinstance(attempts, list) or not isinstance(repeat_statuses, list) or not isinstance(task_statuses, list):
        raise ValueError("Progress backup has an invalid structure.")

    hash_to_id = {
        row["content_hash"]: row["id"]
        for row in conn.execute("SELECT id, content_hash FROM questions").fetchall()
    }

    conn.execute("DELETE FROM attempts")
    conn.execute("DELETE FROM study_task_status")
    conn.execute("UPDATE questions SET repeat_status = 'New'")

    restored_repeats = 0
    valid_repeats = {"New", "Attempted", "Review"}
    for item in repeat_statuses:
        if not isinstance(item, dict):
            continue
        content_hash = str(item.get("content_hash", ""))
        status = str(item.get("repeat_status", "New"))
        if content_hash in hash_to_id and status in valid_repeats:
            conn.execute(
                "UPDATE questions SET repeat_status = ? WHERE id = ?",
                (status, hash_to_id[content_hash]),
            )
            restored_repeats += 1

    restored_attempts = 0
    for item in attempts:
        if not isinstance(item, dict):
            continue
        question_id = hash_to_id.get(str(item.get("content_hash", "")))
        if not question_id:
            continue
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
                question_id,
                item.get("attempted_at") or datetime.now().isoformat(timespec="seconds"),
                int(item.get("day_number") or 1),
                item.get("section") or "",
                item.get("topic") or "",
                item.get("source_pdf") or "",
                item.get("page_number"),
                item.get("question_number"),
                item.get("my_answer") or "",
                item.get("correct_answer"),
                item.get("is_correct"),
                item.get("mistake_type"),
                item.get("trap_pattern"),
                item.get("notes"),
                item.get("time_seconds"),
                item.get("reattempt_status") or "No",
            ),
        )
        restored_attempts += 1

    restored_tasks = 0
    valid_task_statuses = {"Pending", "Completed"}
    now = datetime.now().isoformat(timespec="seconds")
    for item in task_statuses:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "Pending"))
        section = str(item.get("section", ""))
        if section not in {"Quant", "Verbal"} or status not in valid_task_statuses:
            continue
        conn.execute(
            """
            INSERT INTO study_task_status (day_number, section, status, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(day_number, section) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                int(item.get("day_number") or 1),
                section,
                status,
                item.get("updated_at") or now,
            ),
        )
        restored_tasks += 1

    conn.commit()
    return {
        "attempts": restored_attempts,
        "repeat_statuses": restored_repeats,
        "study_task_status": restored_tasks,
    }


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
    daily = daily_progress_rows(conn)
    statuses = study_task_status_rows(conn)
    return {"totals": totals, "by_topic": by_topic, "traps": traps, "review": review, "daily": daily, "statuses": statuses}
