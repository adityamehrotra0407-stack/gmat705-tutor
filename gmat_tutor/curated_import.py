from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .classifiers import clean_text, infer_section
from .db import insert_question, upsert_source
from .quality import question_is_ready


LETTERS = ["A", "B", "C", "D", "E"]


def _text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return clean_text(str(value))


def _hash(source_name: str, stem: str, choices_json: str) -> str:
    h = hashlib.sha256()
    h.update(source_name.encode("utf-8", errors="ignore"))
    h.update(stem.encode("utf-8", errors="ignore"))
    h.update(choices_json.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def import_curated_frame(conn, frame: pd.DataFrame, source_name: str) -> dict[str, int]:
    required = {"section", "topic", "question", "A", "B", "C", "D", "E", "correct_answer"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")

    source_id = upsert_source(conn, source_name, f"curated://{source_name}", 0)
    inserted = 0
    skipped_duplicates = 0
    needs_review = 0
    for index, row in frame.iterrows():
        question_stem = _text(row.get("question"))
        passage = _text(row.get("passage")) or None
        topic = _text(row.get("topic")) or "Quant Mixed"
        section = _text(row.get("section")) or infer_section(topic)
        choices = [{"letter": letter, "text": _text(row.get(letter))} for letter in LETTERS]
        choices_json = json.dumps(choices, ensure_ascii=False, indent=2)
        correct = _text(row.get("correct_answer")).upper()[:1]
        correct = correct if correct in LETTERS else None
        explanation = _text(row.get("explanation")) or None
        page_number_text = _text(row.get("page_number"))
        question_number = _text(row.get("question_number")) or str(index + 1)
        status = "Ready" if question_is_ready(question_stem, choices_json, correct) else "Needs Manual Review"
        if status != "Ready":
            needs_review += 1
        page_number = int(page_number_text) if page_number_text.isdigit() else None
        raw_text = "\n".join(
            [question_stem, *[f"{choice['letter']}. {choice['text']}" for choice in choices], f"Answer: {correct or ''}"]
        )
        source_pdf = _text(row.get("source_file")) or source_name
        question = {
            "source_id": source_id,
            "source_pdf": source_pdf,
            "page_number": page_number,
            "question_number": question_number,
            "section": section,
            "topic": topic,
            "passage": passage,
            "question_stem": question_stem,
            "answer_choices": choices_json,
            "correct_answer": correct,
            "explanation": explanation,
            "trap_type": _text(row.get("trap_type")) or None,
            "takeaway_rule": _text(row.get("takeaway_rule")) or None,
            "extraction_status": status,
            "repeat_status": "New",
            "raw_text": raw_text,
            "content_hash": _hash(source_name, question_stem, choices_json),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        if insert_question(conn, question):
            inserted += 1
        else:
            skipped_duplicates += 1
    return {"inserted": inserted, "skipped_duplicates": skipped_duplicates, "needs_review": needs_review}


def read_curated_upload(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file)
    raise ValueError("Upload a CSV or Excel file.")


def read_curated_path(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError("Use a CSV or Excel file.")
