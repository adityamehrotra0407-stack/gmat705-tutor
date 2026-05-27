from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


STUDY_PLAN = [
    ("25-May", "Weekday", "Numbers & Number Line (1/3)", "CR Assumptions"),
    ("26-May", "Weekday", "Numbers & Number Line (2/3)", "CR Assumptions"),
    ("27-May", "Weekday", "Numbers & Number Line (3/3)", "CR Assumptions"),
    ("28-May", "Weekday", "Factors & Remainders (1/2)", "CR Assumptions"),
    ("29-May", "Weekday", "Factors & Remainders (2/2)", "CR Weaken"),
    ("30-May", "Weekend", "Decimals (1/2)", "CR Mixed"),
    ("31-May", "Weekend", "Decimals (2/2)", "Full Verbal"),
    ("01-Jun", "Weekday", "Decimals & Place Value (1/2)", "CR Strengthen"),
    ("02-Jun", "Weekday", "Decimals & Place Value (2/2)", "CR Strengthen"),
    ("03-Jun", "Weekday", "Exponents (1/2)", "CR Strengthen"),
    ("04-Jun", "Weekday", "Exponents (2/2)", "RC Inference"),
    ("05-Jun", "Weekday", "Arithmetic Properties (1/3)", "RC Inference"),
    ("06-Jun", "Weekend", "Arithmetic Properties (2/3)", "RC Mixed"),
    ("07-Jun", "Weekend", "Arithmetic Properties (3/3)", "Full Verbal"),
    ("08-Jun", "Weekday", "Algebraic Equations (1/2)", "Weak CR"),
    ("09-Jun", "Weekday", "Algebraic Equations (2/2)", "CR Strengthen"),
    ("10-Jun", "Weekday", "Linear Equations (1/3)", "CR Strengthen"),
    ("11-Jun", "Weekday", "Linear Equations (2/3)", "Logical Flaw"),
    ("12-Jun", "Weekday", "Linear Equations (3/3)", "Logical Flaw"),
    ("13-Jun", "Weekend", "Quadratic (1/2)", "CR+RC Mixed"),
    ("14-Jun", "Weekend", "Quadratic (2/2)", "Full Verbal"),
    ("15-Jun", "Weekday", "Inequalities (1/3)", "Weak CR"),
    ("16-Jun", "Weekday", "Inequalities (2/3)", "RC"),
    ("17-Jun", "Weekday", "Inequalities (3/3)", "RC"),
    ("18-Jun", "Weekday", "Functions (1/2)", "RC"),
    ("19-Jun", "Weekday", "Functions (2/2)", "RC"),
    ("20-Jun", "Weekend", "Graphs (1/2)", "CR Skim"),
    ("21-Jun", "Weekend", "Graphs (2/2)", "Full Verbal"),
    ("22-Jun", "Weekday", "Conversions (1/2)", "Weak CR"),
    ("23-Jun", "Weekday", "Conversions (2/2)", "RC"),
    ("24-Jun", "Weekday", "Ratio (1/3)", "RC Analysis"),
    ("25-Jun", "Weekday", "Ratio (2/3)", "Boldface"),
    ("26-Jun", "Weekday", "Ratio (3/3)", "Boldface"),
    ("27-Jun", "Weekend", "Fractions (1/2)", "CR+RC"),
    ("28-Jun", "Weekend", "Fractions (2/2)", "Full Verbal"),
    ("29-Jun", "Weekday", "Percentage (1/2)", "Weak CR"),
    ("30-Jun", "Weekday", "Percentage (2/2)", "RC"),
    ("01-Jul", "Weekday", "Dec-Fraction-% (1/3)", "RC"),
    ("02-Jul", "Weekday", "Dec-Fraction-% (2/3)", "RC"),
    ("03-Jul", "Weekday", "Dec-Fraction-% (3/3)", "Verbal Mixed"),
    ("04-Jul", "Weekend", "Work & Rate (1/3)", "Verbal Mixed"),
    ("05-Jul", "Weekend", "Work & Rate (2/3)", "Full Verbal"),
    ("06-Jul", "Weekday", "Work & Rate (3/3)", "Weak CR"),
    ("07-Jul", "Weekday", "Mixtures (1/3)", "RC"),
    ("08-Jul", "Weekday", "Mixtures (2/3)", "RC"),
    ("09-Jul", "Weekend", "Mixtures (3/3)", "RC"),
    ("10-Jul", "Weekend", "Statistics (1/2)", "RC"),
    ("11-Jul", "Weekday", "Statistics (2/2)", "Verbal Mixed"),
    ("12-Jul", "Weekday", "Sets (1/2)", "Full Verbal"),
    ("13-Jul", "Weekday", "Sets (2/2)", "Weak CR"),
    ("14-Jul", "Weekday", "Counting (1/2)", "Weak CR"),
    ("15-Jul", "Weekday", "Counting (2/2)", "Weak CR"),
    ("16-Jul", "Weekend", "Probability (1/3)", "Full Verbal"),
    ("17-Jul", "Weekday", "Probability (2/3)", "RC Skim"),
    ("18-Jul", "Weekday", "Probability (3/3)", "RC Skim"),
    ("19-Jul", "Weekday", "Estimations (1/2)", "RC"),
    ("20-Jul", "Weekday", "Estimations (2/2)", "CR Mixed"),
    ("21-Jul", "Weekday", "Sequence (1/3)", "CR Mixed"),
    ("22-Jul", "Weekday", "Sequence (2/3)", "CR Mixed"),
    ("23-Jul", "Weekend", "Sequence (3/3)", "Full Verbal"),
    ("24-Jul", "Weekend", "Weak Quant", "CR+RC"),
    ("25-Jul", "Weekday", "Full Syllabus", "SC Mixed"),
    ("26-Jul", "Weekday", "Weak Quant", "Light Verbal"),
    ("27-Jul", "Weekend", "Timed Quant", "CR Mixed"),
    ("28-Jul", "Weekend", "Mixed Quant", "CR Mixed"),
    ("29-Jul", "Weekday", "Weak Quant", "CR Mixed"),
    ("30-Jul", "Weekday", "Formula Revision", "Full Verbal"),
    ("31-Jul", "Weekday", "Light Quant", "RC Analysis"),
    ("01-Aug", "Weekday", "Full Syllabus", "CR Review"),
    ("02-Aug", "Weekend", "Weak Quant", "Light Review"),
    ("03-Aug", "Weekend", "Timed Quant", "Full Verbal"),
    ("04-Aug", "Weekday", "Weak Quant", "RC Analysis"),
    ("05-Aug", "Weekday", "Mixed Quant", "CR Analysis"),
    ("06-Aug", "Weekday", "Formula Revision", "RC Mixed"),
    ("07-Aug", "Weekday", "Light Quant", "CR Mixed"),
    ("08-Aug", "Weekend", "Full Syllabus", "RC Skim"),
    ("09-Aug", "Weekend", "Weak Quant", "No Study"),
    ("10-Aug", "Weekend", "Timed Quant", "Full Verbal"),
    ("11-Aug", "Weekend", "Weak Quant", "Weak CR"),
    ("12-Aug", "Weekend", "Formulas + Notes", "CR Mixed"),
    ("13-Aug", "Weekend", "Light Quant", "Weak CR"),
    ("14-Aug", "Weekend", "Final Full Test", "RC Skim"),
    ("15-Aug", "Weekend", "No Study", "No Study"),
    ("16-Aug", "Weekend", "Light Revision", "Light Verbal"),
]

PLAN_YEAR = 2026
PLAN_TIMEZONE = "Asia/Kolkata"


def today_in_plan_timezone() -> date:
    return datetime.now(ZoneInfo(PLAN_TIMEZONE)).date()


def plan_date_for_day(day_number: int) -> date:
    if day_number < 1:
        day_number = 1
    index = min(day_number, len(STUDY_PLAN)) - 1
    date_text = STUDY_PLAN[index][0]
    return datetime.strptime(f"{date_text}-{PLAN_YEAR}", "%d-%b-%Y").date()


def current_day_number(today: date | None = None) -> int:
    today = today or today_in_plan_timezone()
    first_day = plan_date_for_day(1)
    last_day = plan_date_for_day(len(STUDY_PLAN))
    if today <= first_day:
        return 1
    if today >= last_day:
        return len(STUDY_PLAN)
    for day in range(1, len(STUDY_PLAN) + 1):
        if plan_date_for_day(day) >= today:
            return day
    return len(STUDY_PLAN)


def timeline_status_for_day(day_number: int, today: date | None = None) -> str:
    today = today or today_in_plan_timezone()
    plan_date = plan_date_for_day(day_number)
    if plan_date < today:
        return "Past"
    if plan_date == today:
        return "Today"
    return "Upcoming"


def plan_row_for_day(day_number: int) -> dict[str, object]:
    if day_number < 1:
        day_number = 1
    index = min(day_number, len(STUDY_PLAN)) - 1
    date, day_type, quant_task, verbal_task = STUDY_PLAN[index]
    return {
        "day": index + 1,
        "date": date,
        "full_date": plan_date_for_day(index + 1).isoformat(),
        "day_type": day_type,
        "quant_task": quant_task,
        "verbal_task": verbal_task,
    }


def task_for_day(day_number: int, section: str) -> str:
    row = plan_row_for_day(day_number)
    return str(row["quant_task"] if section == "Quant" else row["verbal_task"])


def topic_for_task(task: str, section: str) -> str:
    lowered = task.lower()
    if "no study" in lowered:
        return "No Study"
    if section == "Quant":
        if any(word in lowered for word in ["factor", "remainder", "number line", "integer", "sequence"]):
            return "Number Properties"
        if any(word in lowered for word in ["equation", "quadratic", "inequalit", "function", "graph"]):
            return "Algebra"
        if any(word in lowered for word in ["work", "rate", "mixture", "ratio", "percent", "conversion", "fraction", "decimal"]):
            return "Word Problems"
        if any(word in lowered for word in ["counting", "probability", "sets", "statistics"]):
            return "Data Sufficiency"
        if any(word in lowered for word in ["mixed", "weak", "full", "timed", "light", "revision", "formula", "test"]):
            return "Quant Mixed"
        return "Arithmetic"

    if "assumption" in lowered:
        return "CR Assumption"
    if "weaken" in lowered:
        return "CR Weaken"
    if "strengthen" in lowered:
        return "CR Strengthen"
    if "boldface" in lowered:
        return "Boldface"
    if "flaw" in lowered:
        return "Logical Flaw"
    if "inference" in lowered:
        return "Inference"
    if "rc" in lowered:
        return "RC"
    return "Verbal Mixed"


def topic_for_day(day_number: int, section: str = "Verbal") -> str:
    return topic_for_task(task_for_day(day_number, section), section)


def topic_stage_for_day(day_number: int, section: str) -> int:
    topic = topic_for_day(day_number, section)
    if topic in {"No Study", "Verbal Mixed", "Quant Mixed"}:
        return 3
    stage = 0
    for day in range(1, day_number + 1):
        if topic_for_day(day, section) == topic:
            stage += 1
    return max(1, min(stage, 3))


def target_range_for_day(day_number: int, section: str) -> tuple[int, int]:
    row = plan_row_for_day(day_number)
    task = task_for_day(day_number, section).lower()
    if "no study" in task:
        return (0, 0)
    is_weekend = row["day_type"] == "Weekend"
    if section == "Quant":
        return (60, 70) if is_weekend else (40, 40)
    return (45, 60) if is_weekend else (30, 30)


def target_label_for_day(day_number: int, section: str) -> str:
    low, high = target_range_for_day(day_number, section)
    if high == 0:
        return "No Study"
    if low == high:
        return f"{low} questions"
    return f"{low}-{high} questions"


def search_terms_for_task(task: str, section: str) -> list[str]:
    lowered = task.lower()
    if section == "Verbal":
        if "assumption" in lowered:
            return ["assumption", "assumes", "depends on", "relies on", "required"]
        if "weaken" in lowered:
            return ["weaken", "undermine", "casts doubt"]
        if "strengthen" in lowered:
            return ["strengthen", "support", "helps"]
        if "boldface" in lowered:
            return ["boldface", "boldfaced"]
        if "flaw" in lowered:
            return ["flaw", "vulnerable", "error in reasoning"]
        if "inference" in lowered:
            return ["infer", "inferred", "must be true"]
        if "rc" in lowered:
            return ["passage"]
        return []

    if "number line" in lowered or "numbers" in lowered:
        return ["number line", "integer", "positive integer", "negative", "greatest value", "least value"]
    if "factor" in lowered or "remainder" in lowered:
        return ["factor", "remainder", "divisible", "divisor", "multiple"]
    if "decimal" in lowered:
        return ["decimal", "tenths", "hundredths", "place value"]
    if "exponent" in lowered:
        return ["exponent", "power"]
    if "equation" in lowered:
        return ["equation", "solve", "value of x", "value of y"]
    if "quadratic" in lowered:
        return ["quadratic", "square", "root"]
    if "inequalit" in lowered:
        return ["inequality", "greater than", "less than"]
    if "function" in lowered:
        return ["function", "f(x)"]
    if "graph" in lowered:
        return ["graph", "coordinate", "slope"]
    if "conversion" in lowered:
        return ["convert", "conversion"]
    if "ratio" in lowered:
        return ["ratio", "proportion"]
    if "fraction" in lowered:
        return ["fraction"]
    if "percentage" in lowered or "percent" in lowered:
        return ["percent", "percentage"]
    if "work" in lowered or "rate" in lowered:
        return ["work", "rate"]
    if "mixture" in lowered:
        return ["mixture"]
    if "statistics" in lowered:
        return ["mean", "median", "standard deviation", "average"]
    if "sets" in lowered:
        return ["set", "sets"]
    if "counting" in lowered:
        return ["counting", "arrangements", "how many ways"]
    if "probability" in lowered:
        return ["probability", "chance"]
    if "sequence" in lowered:
        return ["sequence", "series"]
    return []


def plan_preview(days: int | None = None, section: str | None = None) -> list[dict[str, object]]:
    rows = [plan_row_for_day(day) for day in range(1, len(STUDY_PLAN) + 1)]
    if days is not None:
        rows = rows[: max(days, 1)]
    if section == "Quant":
        return [
            {
                "day": row["day"],
                "date": row["date"],
                "full_date": row["full_date"],
                "day_type": row["day_type"],
                "task": row["quant_task"],
                "topic_used": topic_for_task(str(row["quant_task"]), "Quant"),
                "target": target_label_for_day(int(row["day"]), "Quant"),
            }
            for row in rows
        ]
    if section == "Verbal":
        return [
            {
                "day": row["day"],
                "date": row["date"],
                "full_date": row["full_date"],
                "day_type": row["day_type"],
                "task": row["verbal_task"],
                "topic_used": topic_for_task(str(row["verbal_task"]), "Verbal"),
                "target": target_label_for_day(int(row["day"]), "Verbal"),
            }
            for row in rows
        ]
    return [
        {
            **row,
            "quant_target": target_label_for_day(int(row["day"]), "Quant"),
            "verbal_target": target_label_for_day(int(row["day"]), "Verbal"),
        }
        for row in rows
    ]
