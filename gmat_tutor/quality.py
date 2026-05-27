from __future__ import annotations

import json
import re


EXPLANATION_CHOICE_RE = re.compile(
    r"(?is)^\s*(?:correct|incorrect|this is irrelevant|as explained|the passage|the argument|once again)\b|"
    r"\b(?:the correct answer is|reasoning section|this choice is|this answer choice|answer\s*\([A-E]\)|"
    r"in the first example|in the second example)\b"
)
EXPLANATION_STEM_RE = re.compile(
    r"\bthe correct answer is\b|^\s*[A-E]\s+(?:this information|this does|this is|the passage|it provides)\b",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)


def choices_from_json(answer_choices: str) -> list[dict[str, str]]:
    try:
        choices = json.loads(answer_choices or "[]")
    except json.JSONDecodeError:
        return []
    return choices if isinstance(choices, list) else []


def choices_are_exam_like(answer_choices: str) -> bool:
    choices = choices_from_json(answer_choices)
    if len(choices) != 5:
        return False
    if [choice.get("letter") for choice in choices] != ["A", "B", "C", "D", "E"]:
        return False
    if {choice.get("letter") for choice in choices} != {"A", "B", "C", "D", "E"}:
        return False
    for choice in choices:
        text = str(choice.get("text", "")).strip()
        if not text:
            return False
        if EXPLANATION_CHOICE_RE.search(text):
            return False
        if len(text.split()) > 140:
            return False
    return True


def question_is_ready(question_stem: str, answer_choices: str, correct_answer: str | None) -> bool:
    stem = question_stem.strip()
    return bool(stem and not EXPLANATION_STEM_RE.search(stem) and correct_answer and choices_are_exam_like(answer_choices))
