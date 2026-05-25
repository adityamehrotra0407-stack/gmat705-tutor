import re


TOPIC_PATTERNS: list[tuple[str, list[str]]] = [
    ("Data Sufficiency", ["data sufficiency", "statement 1", "statement (1)", "statements together"]),
    ("Geometry", ["triangle", "circle", "rectangle", "angle", "area", "perimeter", "coordinate plane"]),
    ("Number Properties", ["integer", "prime", "divisible", "remainder", "factor", "multiple"]),
    ("Algebra", ["equation", "variable", "solve for", "x =", "y =", "expression"]),
    ("Word Problems", ["rate", "work", "mixture", "probability", "percent", "ratio"]),
    ("Arithmetic", ["greatest value", "least value", "sum", "product", "positive integers", "average"]),
    ("Boldface", ["boldface", "bolded", "in bold", "the two portions in bold"]),
    ("CR Assumption", ["assumption", "assumes", "depends on", "required for the argument"]),
    ("CR Weaken", ["weaken", "undermine", "cast doubt"]),
    ("CR Strengthen", ["strengthen", "support", "most helps"]),
    ("Logical Flaw", ["flaw", "vulnerable to criticism", "error in reasoning"]),
    ("Inference", ["infer", "inferred", "must be true", "properly concluded"]),
    ("RC", ["passage", "according to the passage", "primary purpose", "author would agree"]),
]

QUANT_TOPICS = {
    "Arithmetic",
    "Algebra",
    "Number Properties",
    "Word Problems",
    "Geometry",
    "Data Sufficiency",
    "Quant Mixed",
}


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("ß", "fi").replace("Ÿ", "fi").replace("ϐ", "fi")
    text = re.sub(r"(?<=[A-Za-z])8(?=[A-Za-z])", "fi", text)
    text = re.sub(r"(?<=[A-Za-z])\?(?=[A-Za-z])", "fi", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def classify_topic(text: str) -> str:
    haystack = text.lower()
    if is_rc_question(haystack):
        return "RC"
    if is_cr_assumption(haystack):
        return "CR Assumption"
    if any(pattern in haystack for pattern in ["weaken", "undermine", "cast doubt", "call into question"]):
        return "CR Weaken"
    if any(pattern in haystack for pattern in ["strengthen", "support", "most helps", "helps to justify"]):
        return "CR Strengthen"
    if any(pattern in haystack for pattern in ["boldface", "boldfaced", "in bold", "the two portions in bold"]):
        return "Boldface"
    if any(pattern in haystack for pattern in ["flaw", "vulnerable to criticism", "error in reasoning"]):
        return "Logical Flaw"
    if any(pattern in haystack for pattern in ["infer", "inferred", "must be true", "properly concluded"]):
        return "Inference"
    scores: dict[str, int] = {}
    for topic, patterns in TOPIC_PATTERNS:
        scores[topic] = sum(1 for pattern in patterns if pattern in haystack)
    best_topic, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score > 0:
        return best_topic
    return "Quant Mixed" if looks_quant(haystack) else "Verbal Mixed"


def is_cr_assumption(text: str) -> bool:
    assumption_patterns = [
        "argument depends",
        "argument relies",
        "depends on which",
        "depends on assuming",
        "relies on which",
        "assumption on which the argument",
        "assumption on which this argument",
        "assumption on which the reasoning",
        "which of the following is an assumption",
        "which of the following assumptions",
        "depends on the assumption",
        "requires which of the following assumptions",
        "required for the argument",
    ]
    if any(pattern in text for pattern in assumption_patterns):
        return True
    if "assumes that" in text and "passage" not in text:
        return True
    return False


def is_rc_question(text: str) -> bool:
    rc_patterns = [
        "according to the passage",
        "the passage suggests",
        "the passage indicates",
        "the passage mentions",
        "the author of the passage",
        "the author would",
        "the author's argument",
        "the author’s argument",
        "primary purpose",
        "main idea",
        "line ",
        "lines ",
        "see line",
        "see lines",
    ]
    return any(pattern in text for pattern in rc_patterns)


def infer_section(topic: str) -> str:
    return "Quant" if topic in QUANT_TOPICS else "Verbal"


def looks_quant(text: str) -> bool:
    return bool(
        re.search(r"\b(?:integer|value|equation|solve|sum|product|percent|ratio|average|triangle|circle|area)\b", text)
        or re.search(r"[xyz]\s*[=<>]", text)
        or re.search(r"\d+\s*[%/]", text)
    )


def infer_mistake_type(my_answer: str, correct_answer: str) -> str:
    if not correct_answer:
        return "Needs Manual Review"
    if my_answer == correct_answer:
        return "Correct"
    return "Incorrect"
