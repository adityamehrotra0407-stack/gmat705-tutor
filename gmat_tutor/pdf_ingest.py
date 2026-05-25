from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

import fitz

from .classifiers import classify_topic, clean_text, infer_section
from .config import UPLOAD_DIR
from .db import insert_question, upsert_source
from .quality import question_is_ready


ANSWER_CHOICE_RE = re.compile(
    r"(?ms)(?:^|\n)\s*[\(\[]?([A-E])[\)\].:-]\s+(.+?)(?=(?:\n\s*[\(\[]?[A-E][\)\].:-]\s+)|\Z)"
)
ANSWER_TAIL_RE = re.compile(r"(?is)\n\s*(?:correct\s+answer|answer|ans|explanation|solution|analysis)\b")
EXPLANATION_LINE_RE = re.compile(r"(?im)^\s*[A-E][\)\].:-]\s+(?:correct|incorrect|this is irrelevant|as explained)\b")
QUESTION_START_RE = re.compile(r"(?m)^\s*(?:Question\s*)?(\d{1,4})[\).:-]\s+")
STANDALONE_NUMBER_RE = re.compile(r"(?m)^\s*(\d{1,4})\s*$")
CORRECT_ANSWER_RE = re.compile(
    r"(?i)\b(?:correct\s+answer|answer|ans)\s*(?:is|:|-)?\s*[\(\[]?([A-E])[\)\]]?\.?\b"
)
ANSWER_KEY_PAIR_RE = re.compile(r"(?m)(\d{1,4})\.\s*([A-E])\b")
LETTER_CORRECT_RE = re.compile(r"(?im)^\s*([A-E])[\)\].:-]\s+Correct\b")
EXPLANATION_RE = re.compile(r"(?is)\b(?:explanation|solution|analysis)\s*[:\-]\s*(.+)")
EXPLANATION_START_RE = re.compile(
    r"(?im)^\s*(?:Evaluation|Argument Evaluation|Reading Comprehension|Critical Reasoning|"
    r"Quantitative Review|Data Insights|Situation|Reasoning|Supporting Idea|Inference|Main Idea|"
    r"Algebra|Arithmetic|Geometry|Number Properties|Word Problems|Data Sufficiency|"
    r"The correct answer is|[A-E][\)\].:-]\s+Correct\b)"
)
PAGE_MARK_RE = re.compile(r"@@PAGE:(\d+)@@")


def validate_pdf_name(file_name: str) -> None:
    if not file_name.lower().endswith(".pdf"):
        raise ValueError(f"{file_name} is not a PDF file.")


def save_upload(uploaded_file) -> Path:
    validate_pdf_name(uploaded_file.name)
    target = UPLOAD_DIR / uploaded_file.name
    with target.open("wb") as fh:
        fh.write(uploaded_file.getbuffer())
    return target


def copy_pdf_to_uploads(source_path: Path) -> Path:
    validate_pdf_name(source_path.name)
    target = UPLOAD_DIR / source_path.name
    shutil.copy2(source_path, target)
    return target


def extract_pages(pdf_path: Path) -> list[dict[str, object]]:
    pages: list[dict[str, object]] = []
    with fitz.open(pdf_path) as doc:
        for index, page in enumerate(doc, start=1):
            pages.append({"page_number": index, "text": clean_text(page.get_text("text"))})
    return pages


def pages_to_document_text(pages: list[dict[str, object]]) -> tuple[str, list[tuple[int, int]]]:
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for page in pages:
        marker = f"\n@@PAGE:{page['page_number']}@@\n"
        text = str(page["text"])
        parts.append(marker)
        cursor += len(marker)
        offsets.append((cursor, int(page["page_number"])))
        parts.append(text)
        cursor += len(text)
    return "\n".join(parts), offsets


def page_for_offset(offsets: list[tuple[int, int]], position: int) -> int | None:
    page_number = None
    for start, page in offsets:
        if start <= position:
            page_number = page
        else:
            break
    return page_number


def remove_page_markers(text: str) -> str:
    return clean_text(PAGE_MARK_RE.sub("", text))


def iter_document_question_blocks(document_text: str, offsets: list[tuple[int, int]]) -> Iterable[dict[str, object]]:
    matches = list(QUESTION_START_RE.finditer(document_text))
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document_text)
        block = remove_page_markers(document_text[start:end])
        if not has_complete_choice_letters(block):
            continue
        if not looks_like_exam_question(block):
            continue
        yield {
            "question_number": match.group(1),
            "page_number": page_for_offset(offsets, start),
            "raw_text": block,
        }


def iter_question_blocks(page_text: str) -> Iterable[tuple[str | None, str]]:
    if EXPLANATION_LINE_RE.search(page_text):
        return
    matches = list(QUESTION_START_RE.finditer(page_text))
    if not matches:
        if len(page_text) > 120 and ANSWER_CHOICE_RE.search(page_text):
            yield None, page_text
        return

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(page_text)
        block = page_text[start:end].strip()
        if ANSWER_CHOICE_RE.search(block):
            yield match.group(1), block


def iter_page_question_blocks(pages: list[dict[str, object]]) -> Iterable[dict[str, object]]:
    for page in pages:
        page_number = int(page["page_number"])
        page_text = str(page["text"])
        yielded = False
        for question_number, block in iter_question_blocks(page_text):
            if not has_complete_choice_letters(block):
                continue
            if not looks_like_exam_question(block):
                continue
            yielded = True
            yield {
                "question_number": question_number or str(page_number),
                "page_number": page_number,
                "raw_text": block,
            }
        if yielded:
            continue
        if not has_complete_choice_letters(page_text):
            continue
        if not looks_like_exam_question(page_text):
            continue
        number_match = STANDALONE_NUMBER_RE.search(page_text)
        yield {
            "question_number": number_match.group(1) if number_match else str(page_number),
            "page_number": page_number,
            "raw_text": page_text,
        }


def has_complete_choice_letters(block: str) -> bool:
    return {match.group(1) for match in ANSWER_CHOICE_RE.finditer(block)} == {"A", "B", "C", "D", "E"}


def looks_like_exam_question(block: str) -> bool:
    lower = block.lower()
    if any(bad in lower for bad in ["how should i prepare", "official guide offers", "getting ready for exam day"]):
        return False
    if re.search(r"(?im)^\s*[A-E][\)\].:-]\s+(?:correct|incorrect|this is irrelevant|as explained)\b", block):
        return True
    stem = strip_choices_from_stem(block)
    return "?" in stem or "which of the following" in lower or "if true" in lower


def explanation_start_in_choice(text: str) -> int | None:
    match = EXPLANATION_START_RE.search(text)
    return match.start() if match else None


def clean_choice_text(text: str) -> str:
    split_at = explanation_start_in_choice(text)
    if split_at is not None:
        text = text[:split_at]
    text = ANSWER_TAIL_RE.split(text, maxsplit=1)[0]
    return clean_text(text)


def extract_choices(block: str) -> tuple[str, bool]:
    choices = []
    for letter, text in ANSWER_CHOICE_RE.findall(block):
        cleaned = clean_choice_text(text)
        choices.append({"letter": letter, "text": cleaned})
    normalized = first_clean_choice_set(choices) or choices
    found_letters = {choice["letter"] for choice in normalized}
    is_complete = len(normalized) == 5 and found_letters == {"A", "B", "C", "D", "E"}
    return json.dumps(normalized, ensure_ascii=False, indent=2), is_complete


def first_clean_choice_set(choices: list[dict[str, str]]) -> list[dict[str, str]] | None:
    for index in range(0, max(0, len(choices) - 4)):
        chunk = choices[index : index + 5]
        if [choice.get("letter") for choice in chunk] != ["A", "B", "C", "D", "E"]:
            continue
        if all(choice.get("text", "").strip() for choice in chunk):
            return chunk
    return None


def extract_correct_answer(block: str) -> str | None:
    match = LETTER_CORRECT_RE.search(block)
    if match:
        return match.group(1).upper()
    match = CORRECT_ANSWER_RE.search(block)
    return match.group(1).upper() if match else None


def extract_answer_key(pages: list[dict[str, object]]) -> dict[str, str]:
    answer_key: dict[str, str] = {}
    for page in pages:
        text = str(page["text"])
        pairs = ANSWER_KEY_PAIR_RE.findall(text)
        if len(pairs) < 8:
            continue
        for number, answer in pairs:
            answer_key[number] = answer.upper()
    return answer_key


def extract_explanation(block: str) -> str | None:
    start = EXPLANATION_START_RE.search(block)
    if start:
        explanation = block[start.start() :]
        explanation = re.sub(r"(?is)\bThe correct answer is [A-E]\.?\s*", "", explanation)
        return clean_text(explanation)
    match = EXPLANATION_RE.search(block)
    return clean_text(match.group(1)) if match else None


def strip_choices_from_stem(block: str) -> str:
    first_choice = ANSWER_CHOICE_RE.search(block)
    stem_part = block[: first_choice.start()] if first_choice else block
    stem_part = QUESTION_START_RE.sub("", stem_part, count=1)
    return clean_text(stem_part)


def split_passage_and_stem(stem_text: str, topic: str) -> tuple[str | None, str]:
    if topic != "RC":
        return None, stem_text
    question_mark = stem_text.rfind("?")
    if question_mark > 0:
        prior_period = stem_text.rfind(".", 0, question_mark)
        if prior_period > 300:
            return clean_text(stem_text[: prior_period + 1]), clean_text(stem_text[prior_period + 1 :])
    paragraphs = [part.strip() for part in stem_text.split("\n\n") if part.strip()]
    if len(paragraphs) > 1:
        return clean_text("\n\n".join(paragraphs[:-1])), clean_text(paragraphs[-1])
    return stem_text, stem_text


def make_hash(source_pdf: str, page_number: int, raw_text: str) -> str:
    h = hashlib.sha256()
    h.update(source_pdf.encode("utf-8"))
    h.update(str(page_number).encode("utf-8"))
    h.update(raw_text.encode("utf-8", errors="ignore"))
    return h.hexdigest()


def question_signature(question_number: str, stem: str) -> str:
    normalized = re.sub(r"\W+", " ", stem.lower()).strip()
    return normalized[:500]


def ingest_pdf(conn, pdf_path: Path) -> dict[str, int]:
    validate_pdf_name(pdf_path.name)
    pages = extract_pages(pdf_path)
    answer_key = extract_answer_key(pages)
    document_text, offsets = pages_to_document_text(pages)
    blocks = list(iter_document_question_blocks(document_text, offsets))
    blocks.extend(iter_page_question_blocks(pages))
    by_signature: dict[str, dict[str, object]] = {}
    for block in blocks:
        number = str(block["question_number"])
        raw = str(block["raw_text"])
        correct_answer = extract_correct_answer(raw)
        if not correct_answer:
            correct_answer = answer_key.get(number)
        explanation = extract_explanation(raw)
        choices_json, complete_choices = extract_choices(raw)
        stem = strip_choices_from_stem(raw)
        candidate_ready = question_is_ready(stem, choices_json, correct_answer if isinstance(correct_answer, str) else None)
        signature = question_signature(number, stem)
        existing = by_signature.get(signature)
        if existing is None:
            by_signature[signature] = {
                **block,
                "correct_answer": correct_answer,
                "explanation": explanation,
                "answer_choices": choices_json,
                "complete_choices": complete_choices,
                "question_stem": stem,
                "candidate_ready": candidate_ready,
            }
            continue
        if candidate_ready and not existing.get("candidate_ready"):
            by_signature[signature] = {
                **block,
                "correct_answer": correct_answer,
                "explanation": explanation,
                "answer_choices": choices_json,
                "complete_choices": complete_choices,
                "question_stem": stem,
                "candidate_ready": candidate_ready,
            }
            continue
        if not existing.get("correct_answer") and correct_answer:
            existing["correct_answer"] = correct_answer
        if not existing.get("explanation") and explanation:
            existing["explanation"] = explanation
        existing["candidate_ready"] = question_is_ready(
            str(existing.get("question_stem") or ""),
            str(existing.get("answer_choices") or "[]"),
            existing.get("correct_answer") if isinstance(existing.get("correct_answer"), str) else None,
        )
        existing_text = str(existing.get("question_stem") or "")
        if existing_text and EXPLANATION_LINE_RE.search(existing_text) and not EXPLANATION_LINE_RE.search(stem):
            existing["raw_text"] = raw
            existing["answer_choices"] = choices_json
            existing["complete_choices"] = complete_choices
            existing["question_stem"] = stem
            existing["page_number"] = block["page_number"]
            existing["candidate_ready"] = question_is_ready(
                stem,
                choices_json,
                existing.get("correct_answer") if isinstance(existing.get("correct_answer"), str) else None,
            )
    source_id = upsert_source(conn, pdf_path.name, str(pdf_path), len(pages))
    inserted = 0
    skipped_duplicates = 0
    needs_review = 0

    for item in by_signature.values():
        page_number = int(item["page_number"] or 0)
        question_number = str(item["question_number"])
        raw_text = clean_text(str(item["raw_text"]))
        choices_json = str(item["answer_choices"])
        correct_answer = item.get("correct_answer")
        explanation = item.get("explanation")
        stem = clean_text(str(item["question_stem"]))
        topic = classify_topic(stem)
        passage, question_stem = split_passage_and_stem(stem, topic)
        status = "Ready" if question_is_ready(question_stem, choices_json, correct_answer if isinstance(correct_answer, str) else None) else "Needs Manual Review"
        if status == "Needs Manual Review":
            needs_review += 1
        question = {
            "source_id": source_id,
            "source_pdf": pdf_path.name,
            "page_number": page_number,
            "question_number": question_number,
            "section": infer_section(topic),
            "topic": topic,
            "passage": passage,
            "question_stem": question_stem,
            "answer_choices": choices_json,
            "correct_answer": correct_answer,
            "explanation": explanation,
            "trap_type": None,
            "takeaway_rule": None,
            "extraction_status": status,
            "repeat_status": "New",
            "raw_text": raw_text,
            "content_hash": make_hash(pdf_path.name, page_number, raw_text),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        if insert_question(conn, question):
            inserted += 1
        else:
            skipped_duplicates += 1

    return {
        "pages": len(pages),
        "inserted": inserted,
        "skipped_duplicates": skipped_duplicates,
        "needs_review": needs_review,
    }
