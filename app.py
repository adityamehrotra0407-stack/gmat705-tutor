from __future__ import annotations

import json
import time
import html
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from gmat_tutor.classifiers import classify_topic, infer_mistake_type, infer_section
from gmat_tutor.config import ensure_dirs
from gmat_tutor.curated_import import import_curated_frame, read_curated_path, read_curated_upload
from gmat_tutor.db import (
    attempts_frame,
    count_questions_by_status,
    audit_ready_questions,
    connect,
    count_questions,
    dashboard_stats,
    day_section_progress,
    fetch_sources,
    init_db,
    mark_review,
    mark_attempted_topic_review,
    next_question,
    question_bank_rows,
    record_attempt,
    reclassify_question_bank,
    get_task_status,
    set_task_status,
    topic_repeat_counts,
    topic_counts,
    update_question_manual_fields,
)
from gmat_tutor.pdf_ingest import copy_pdf_to_uploads, ingest_pdf, save_upload, validate_pdf_name
from gmat_tutor.study_plan import (
    STUDY_PLAN,
    current_day_number,
    plan_preview,
    plan_row_for_day,
    search_terms_for_task,
    target_label_for_day,
    target_range_for_day,
    task_for_day,
    timeline_status_for_day,
    today_in_plan_timezone,
    topic_stage_for_day,
    topic_for_day,
)


st.set_page_config(page_title="GMAT 705+ Tutor", page_icon="705+", layout="wide")

ensure_dirs()
conn = connect()
init_db(conn)
if "sections_reclassified_once" not in st.session_state:
    reclassify_question_bank(conn, classify_topic, infer_section)
    audit_ready_questions(conn)
    st.session_state["sections_reclassified_once"] = True

TOPIC_OPTIONS = [
    "CR Assumption",
    "CR Weaken",
    "CR Strengthen",
    "Boldface",
    "Logical Flaw",
    "Inference",
    "RC",
    "Verbal Mixed",
    "Arithmetic",
    "Algebra",
    "Number Properties",
    "Word Problems",
    "Geometry",
    "Data Sufficiency",
    "Quant Mixed",
]


def inject_exam_css(theme: str, font_style: str, page: str = "Dashboard") -> None:
    if theme == "Dark":
        colors = {
            "app_bg": "#0f172a",
            "text": "#e5e7eb",
            "muted": "#cbd5e1",
            "panel": "#111827",
            "panel_border": "#334155",
            "sidebar": "#0b1220",
            "sidebar_text": "#e5e7eb",
            "sidebar_muted": "#94a3b8",
            "sidebar_border": "#1e293b",
            "sidebar_selected": "#1d4ed8",
            "metric": "#1f2937",
            "input_bg": "#111827",
            "input_text": "#f9fafb",
            "info_bg": "#1e3a5f",
            "info_text": "#bfdbfe",
            "accent": "#93c5fd",
        }
    else:
        colors = {
            "app_bg": "#f5f5f0",
            "text": "#111827",
            "muted": "#4b5563",
            "panel": "#ffffff",
            "panel_border": "#c9ced6",
            "sidebar": "#f8fafc",
            "sidebar_text": "#111827",
            "sidebar_muted": "#475569",
            "sidebar_border": "#d6dde8",
            "sidebar_selected": "#dbeafe",
            "metric": "#ffffff",
            "input_bg": "#ffffff",
            "input_text": "#111827",
            "input_border": "#c9ced6",
            "info_bg": "#d9ecfb",
            "info_text": "#1d4f91",
            "accent": "#2563eb",
        }
    colors.setdefault("input_border", colors["panel_border"])
    body_font = 'Arial, Helvetica, sans-serif' if font_style == "Clean Sans" else 'Georgia, "Times New Roman", serif'
    ui_font = 'Arial, Helvetica, sans-serif'
    practice_css = ""
    if page == "Practice":
        practice_css = f"""
        section[data-testid="stSidebar"] {{
            position: fixed !important;
            left: 0;
            top: 0;
            bottom: 0;
            width: 290px !important;
            min-width: 290px !important;
            transform: translateX(-274px);
            transition: transform 180ms ease;
            z-index: 999;
            box-shadow: 2px 0 14px rgba(15, 23, 42, 0.16);
        }}
        section[data-testid="stSidebar"]::after {{
            content: "";
            position: absolute;
            right: -8px;
            top: 0;
            width: 10px;
            height: 100%;
            background: {colors["sidebar_border"]};
        }}
        section[data-testid="stSidebar"]:hover,
        section[data-testid="stSidebar"]:focus-within {{
            transform: translateX(0);
        }}
        [data-testid="stAppViewContainer"] > .main {{
            margin-left: 0 !important;
        }}
        .block-container {{
            max-width: 100% !important;
            padding-left: 42px !important;
            padding-right: 42px !important;
            padding-top: 28px !important;
        }}
        .question-paper {{
            max-width: 1180px;
            padding: 24px 30px;
            font-size: 16px;
            line-height: 1.46;
        }}
        h1 {{
            font-size: 28px !important;
            margin-bottom: 4px !important;
        }}
        """
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: {colors["app_bg"]};
            color: {colors["text"]};
            font-family: {body_font};
        }}
        .stApp p, .stApp span, .stApp label, .stApp div {{
            color: {colors["text"]};
        }}
        [data-testid="stMarkdownContainer"] p {{
            color: {colors["text"]};
        }}
        h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
            color: {colors["text"]};
            font-family: {ui_font};
            letter-spacing: 0;
        }}
        section[data-testid="stSidebar"] {{
            background: {colors["sidebar"]};
            border-right: 1px solid {colors["sidebar_border"]};
        }}
        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
            padding: 20px 18px 24px 18px;
        }}
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] div {{
            color: {colors["sidebar_text"]} !important;
        }}
        section[data-testid="stSidebar"] [role="radiogroup"] label,
        section[data-testid="stSidebar"] [role="radiogroup"] span,
        section[data-testid="stSidebar"] [role="radiogroup"] p {{
            color: {colors["sidebar_text"]} !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{
            color: {colors["sidebar_muted"]} !important;
            font-family: {ui_font};
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.02em;
            margin-bottom: 4px;
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] {{
            gap: 4px;
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label {{
            border-radius: 6px;
            padding: 6px 8px;
            min-height: 34px;
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {{
            background: {colors["sidebar_selected"]};
            border: 1px solid {colors["sidebar_border"]};
        }}
        section[data-testid="stSidebar"] hr {{
            border-color: {colors["sidebar_border"]} !important;
            opacity: 1;
        }}
        section[data-testid="stSidebar"] div[data-testid="stAlert"] {{
            background: {colors["sidebar_selected"]} !important;
            border: 1px solid {colors["sidebar_border"]} !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stAlert"] * {{
            color: {colors["sidebar_text"]} !important;
        }}
        div[data-testid="stMetric"] {{
            background: {colors["metric"]};
            border: 1px solid {colors["panel_border"]};
            border-radius: 4px;
            padding: 10px 12px;
        }}
        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] div {{
            color: {colors["text"]} !important;
        }}
        .exam-box {{
            background: {colors["panel"]};
            border: 1px solid {colors["panel_border"]};
            border-radius: 4px;
            padding: 18px 20px;
            color: {colors["text"]};
            font-family: {body_font};
            font-size: 18px;
            line-height: 1.65;
            white-space: pre-wrap;
        }}
        .exam-timer {{
            background: {colors["sidebar"]};
            color: white;
            border-radius: 4px;
            padding: 10px 14px;
            font: 700 22px {ui_font};
            text-align: center;
            width: 130px;
        }}
        .exam-toolbar-title {{
            color: #111827 !important;
            font: 700 15px Arial, Helvetica, sans-serif;
            line-height: 1.1;
            padding-top: 7px;
        }}
        .question-paper {{
            background: #ffffff;
            color: #111827 !important;
            border: 1px solid #d1d5db;
            border-radius: 2px;
            padding: 26px 34px;
            font-family: Arial, Helvetica, sans-serif;
            font-size: 18px;
            line-height: 1.48;
            white-space: pre-wrap;
            max-width: 980px;
            margin: 0 auto;
        }}
        .question-paper * {{
            color: #111827 !important;
        }}
        .stApp div.question-paper {{
            color: #111827 !important;
        }}
        div[data-testid="stButton"] button {{
            border-radius: 4px;
        }}
        div[data-testid="stButton"] button {{
            background: #ffffff !important;
            color: #155eb5 !important;
            border: 1px solid #aeb7c3 !important;
        }}
        div[data-testid="stButton"] button * {{
            color: #155eb5 !important;
        }}
        div[data-testid="stButton"] button[kind="primary"] {{
            min-height: 48px;
            font: 700 18px Arial, Helvetica, sans-serif !important;
        }}
        .answer-result-grid {{
            display: grid;
            grid-template-columns: repeat(5, minmax(74px, 1fr));
            gap: 14px;
            margin: 18px 0 26px 0;
        }}
        .answer-result-box {{
            border-radius: 6px;
            padding: 16px 12px;
            text-align: center;
            font: 700 28px Arial, Helvetica, sans-serif;
            color: #ffffff !important;
            border: 1px solid transparent;
        }}
        .answer-result-box.correct {{
            background: #15803d;
            border-color: #166534;
        }}
        .answer-result-box.wrong {{
            background: #dc2626;
            border-color: #991b1b;
        }}
        .stRadio label, .stTextArea label, .stSelectbox label, .stNumberInput label {{
            color: {colors["text"]} !important;
            font-weight: 600;
        }}
        .stRadio [role="radiogroup"] label,
        .stRadio [role="radiogroup"] label span,
        .stRadio [role="radiogroup"] p {{
            color: {colors["text"]} !important;
        }}
        div[data-baseweb="radio"] label,
        div[data-baseweb="radio"] span {{
            color: {colors["text"]} !important;
        }}
        div[data-testid="stNumberInput"] input {{
            color: {colors["input_text"]} !important;
            background: {colors["input_bg"]} !important;
            border-color: {colors["input_border"]} !important;
        }}
        textarea, input, div[data-baseweb="select"] > div {{
            color: {colors["input_text"]} !important;
            background: {colors["input_bg"]} !important;
            border-color: {colors["input_border"]} !important;
        }}
        div[data-testid="stFileUploader"] section {{
            background: {colors["input_bg"]} !important;
            border: 1px dashed {colors["input_border"]} !important;
            border-radius: 6px !important;
        }}
        div[data-testid="stFileUploader"] section div,
        div[data-testid="stFileUploader"] section span,
        div[data-testid="stFileUploader"] section p,
        div[data-testid="stFileUploader"] small {{
            color: {colors["text"]} !important;
        }}
        div[data-testid="stFileUploader"] button {{
            background: #ffffff !important;
            color: #155eb5 !important;
            border: 1px solid #aeb7c3 !important;
        }}
        div[data-testid="stAlert"] {{
            color: {colors["info_text"]} !important;
        }}
        div[data-testid="stAlert"] * {{
            color: inherit !important;
        }}
        button {{
            font-family: {ui_font} !important;
        }}
        {practice_css}
        </style>
        """,
        unsafe_allow_html=True,
    )


def exam_text_box(text: str) -> None:
    st.markdown(f"<div class='exam-box'>{html.escape(text or '')}</div>", unsafe_allow_html=True)


def question_paper(question, choice_map: dict[str, str]) -> None:
    parts: list[str] = []
    if question["passage"]:
        parts.append(str(question["passage"]).strip())
    parts.append(str(question["question_stem"] or "").strip())
    parts.append("")
    for letter in ["A", "B", "C", "D", "E"]:
        parts.append(f"{letter}. {choice_map.get(letter, '')}")
    text = "\n".join(part for part in parts if part is not None)
    st.markdown(f"<div class='question-paper'>{html.escape(text)}</div>", unsafe_allow_html=True)


def answer_result_boxes(correct_answer: str | None) -> None:
    boxes = []
    for letter in ["A", "B", "C", "D", "E"]:
        status = "correct" if correct_answer == letter else "wrong"
        boxes.append(f"<div class='answer-result-box {status}'>{letter}</div>")
    st.markdown(f"<div class='answer-result-grid'>{''.join(boxes)}</div>", unsafe_allow_html=True)


def live_timer(started_at: float) -> None:
    live_timer_with_elapsed(started_at, 0)


def format_elapsed(seconds: int | float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def live_timer_with_elapsed(started_at: float, base_seconds: int | float = 0) -> None:
    started_ms = int(started_at * 1000)
    base_ms = int(base_seconds * 1000)
    timer_bg = "#020617" if st.session_state.get("theme") == "Dark" else "#17375e"
    components.html(
        f"""
        <div id="timer" style="
            background:{timer_bg};color:white;border-radius:4px;padding:10px 14px;
            font:700 22px Arial, Helvetica, sans-serif;text-align:center;width:105px;
            box-sizing:border-box;">0:00</div>
        <script>
        const start = {started_ms};
        const base = {base_ms};
        const el = document.getElementById("timer");
        function tick() {{
            const seconds = Math.max(0, Math.floor((base + Date.now() - start) / 1000));
            const mins = Math.floor(seconds / 60);
            const secs = String(seconds % 60).padStart(2, "0");
            el.textContent = mins + ":" + secs;
        }}
        tick();
        setInterval(tick, 1000);
        </script>
        """,
        height=52,
    )


def rows_to_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(row) for row in rows])


def render_choices(answer_choices: str) -> list[dict[str, str]]:
    try:
        choices = json.loads(answer_choices)
    except json.JSONDecodeError:
        choices = []
    for choice in choices:
        st.radio(
            label=f"{choice.get('letter', '')}. {choice.get('text', '')}",
            options=[""],
            label_visibility="visible",
            disabled=True,
            key=f"choice_preview_{choice.get('letter')}_{choice.get('text')[:20]}",
        )
    return choices


def source_reference(question) -> str:
    parts = [question["source_pdf"]]
    if question["page_number"]:
        parts.append(f"page {question['page_number']}")
    if question["question_number"]:
        parts.append(f"question {question['question_number']}")
    return " | ".join(parts)


def choices_from_json(answer_choices: str) -> dict[str, str]:
    try:
        choices = json.loads(answer_choices or "[]")
    except json.JSONDecodeError:
        choices = []
    return {
        str(choice.get("letter", "")).strip().upper(): str(choice.get("text", "")).strip()
        for choice in choices
        if str(choice.get("letter", "")).strip().upper() in {"A", "B", "C", "D", "E"}
    }


def choices_to_json(choice_map: dict[str, str]) -> str:
    return json.dumps(
        [{"letter": letter, "text": choice_map.get(letter, "").strip()} for letter in ["A", "B", "C", "D", "E"]],
        ensure_ascii=False,
        indent=2,
    )


def ingest_page() -> None:
    st.header("PDF Ingestion")
    st.caption("Upload any GMAT PDF you want to use. Anything uncertain is marked for manual review.")

    uploaded = st.file_uploader(
        "Upload PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        help="You can add more PDFs whenever you want.",
    )
    if uploaded and st.button("Ingest uploaded PDFs", type="primary"):
        for file in uploaded:
            try:
                target = save_upload(file)
                result = ingest_pdf(conn, target)
                st.success(f"{file.name}: {result}")
            except Exception as exc:
                st.error(f"{file.name}: {exc}")

    st.divider()
    st.subheader("Ingest from local file path")
    st.caption("Useful for PDFs already in Downloads.")
    local_path = st.text_input("PDF path", placeholder=r"C:\Users\Aditya\Downloads\GMAT 844 Verbal numbered version.pdf")
    if st.button("Copy and ingest local PDF") and local_path:
        try:
            source = Path(local_path)
            validate_pdf_name(source.name)
            if not source.exists():
                st.error("That path does not exist.")
            else:
                target = copy_pdf_to_uploads(source)
                result = ingest_pdf(conn, target)
                st.success(f"{source.name}: {result}")
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Import curated questions")
    st.caption("Use CSV/Excel columns: section, topic, question, A, B, C, D, E, correct_answer. Optional: passage, explanation, source_file, page_number, question_number.")
    curated_upload = st.file_uploader(
        "Upload curated CSV or Excel",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=False,
        key="curated_question_upload",
    )
    if curated_upload and st.button("Import curated questions", type="primary"):
        try:
            frame = read_curated_upload(curated_upload)
            result = import_curated_frame(conn, frame, curated_upload.name)
            st.success(f"{curated_upload.name}: {result}")
        except Exception as exc:
            st.error(str(exc))

    curated_path = st.text_input("Curated CSV/Excel local path", placeholder=str(Path("outputs/new_materials/combined_ready_questions.csv")))
    if st.button("Import curated file from local path") and curated_path:
        try:
            source = Path(curated_path)
            if not source.is_absolute():
                source = Path.cwd() / source
            if not source.exists():
                st.error("That curated file path does not exist.")
            else:
                frame = read_curated_path(source)
                result = import_curated_frame(conn, frame, source.name)
                st.success(f"{source.name}: {result}")
        except Exception as exc:
            st.error(str(exc))

    st.divider()
    st.subheader("Current Sources")
    sources = rows_to_frame(fetch_sources(conn))
    if sources.empty:
        st.info("No PDFs ingested yet.")
    else:
        _ = st.dataframe(sources, use_container_width=True, hide_index=True)

    st.subheader("Question Bank Summary")
    if st.button("Reclassify existing questions into Quant / Verbal"):
        changed = reclassify_question_bank(conn, classify_topic, infer_section)
        flagged = audit_ready_questions(conn)
        st.success(f"Reclassified {changed} questions. Moved {flagged} bad parses back to Manual Review.")
    counts = rows_to_frame(topic_counts(conn))
    if counts.empty:
        st.info("No questions extracted yet.")
    else:
        _ = st.dataframe(counts, use_container_width=True, hide_index=True)


def study_plan_page() -> None:
    st.header("Study Plan")
    st.caption("Your exact day-wise plan from 25-May to 16-Aug, with daily question targets.")
    today = today_in_plan_timezone()
    today_day = current_day_number(today)
    st.info(f"Today is {today.isoformat()} | Current study day: Day {today_day}")
    view = st.radio("View", ["Full Plan", "Verbal Only", "Quant Only"], horizontal=True)
    days = st.slider("Preview days", 6, len(STUDY_PLAN), len(STUDY_PLAN))
    if view == "Verbal Only":
        frame = pd.DataFrame(plan_preview(days, "Verbal"))
        frame["timeline"] = frame["day"].apply(lambda day: timeline_status_for_day(int(day), today))
        frame["status"] = frame["day"].apply(lambda day: get_task_status(conn, int(day), "Verbal"))
    elif view == "Quant Only":
        frame = pd.DataFrame(plan_preview(days, "Quant"))
        frame["timeline"] = frame["day"].apply(lambda day: timeline_status_for_day(int(day), today))
        frame["status"] = frame["day"].apply(lambda day: get_task_status(conn, int(day), "Quant"))
    else:
        frame = pd.DataFrame(plan_preview(days))
        frame["timeline"] = frame["day"].apply(lambda day: timeline_status_for_day(int(day), today))
        frame["quant_status"] = frame["day"].apply(lambda day: get_task_status(conn, int(day), "Quant"))
        frame["verbal_status"] = frame["day"].apply(lambda day: get_task_status(conn, int(day), "Verbal"))
    _ = st.dataframe(frame, use_container_width=True, hide_index=True)

    st.subheader("Update Previous / Current Task Status")
    c1, c2, c3 = st.columns(3)
    with c1:
        status_day = st.number_input("Day to update", min_value=1, max_value=today_day, value=today_day, step=1)
    with c2:
        status_section = st.radio("Section", ["Verbal", "Quant"], horizontal=True, key="status_update_section")
    with c3:
        status_value = st.selectbox("Set status", ["Pending", "Completed"])
    status_row = plan_row_for_day(int(status_day))
    st.caption(
        f"Selected: Day {int(status_day)} ({status_row['date']}) | "
        f"{task_for_day(int(status_day), status_section)}"
    )
    if st.button("Save task status", type="primary"):
        set_task_status(conn, int(status_day), status_section, status_value)
        st.success(f"Day {int(status_day)} {status_section} marked {status_value}.")
        st.rerun()


def render_day_progress(day_number: int, section: str) -> None:
    target_low, target_high = target_range_for_day(day_number, section)
    progress = day_section_progress(conn, day_number, section)
    attempted = int(progress["attempted"] or 0)
    correct = int(progress["correct"] or 0)
    avg_time = progress["avg_time_seconds"]
    target_text = target_label_for_day(day_number, section)
    if target_high == 0:
        percent = 0
    else:
        percent = min(100, round(attempted / target_low * 100))
    st.markdown(f"**{section} daily progress**")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Target", target_text)
    c2.metric("Done", attempted)
    c3.metric("Correct", correct)
    c4.metric("Avg time", "N/A" if avg_time is None else f"{avg_time}s")
    _ = st.progress(percent / 100, text=f"{attempted}/{target_low} minimum target completed")


def practice_page() -> None:
    st.header("Practice")
    st.caption("No generated questions. No topic switching inside a day.")
    section = st.radio("Choose section", ["Verbal", "Quant"], horizontal=True)
    today = today_in_plan_timezone()
    default_day = current_day_number(today)
    day_number = st.number_input("Day number", min_value=1, max_value=len(STUDY_PLAN), value=default_day, step=1)
    plan_row = plan_row_for_day(int(day_number))
    assigned_task = task_for_day(int(day_number), section)
    assigned_topic = topic_for_day(int(day_number), section)
    task_terms = search_terms_for_task(assigned_task, section)
    st.info(
        f"START {section.upper()} DAY {int(day_number)} ({plan_row['date']}) loads: "
        f"{assigned_task} -> {assigned_topic} | Target: {target_label_for_day(int(day_number), section)} | "
        f"{timeline_status_for_day(int(day_number), today)} | Status: {get_task_status(conn, int(day_number), section)}"
    )
    if int(day_number) < default_day and get_task_status(conn, int(day_number), section) != "Completed":
        st.warning("This is a previous task and is still Pending. You can complete it now, then mark it Completed below.")
    mark_cols = st.columns([1, 1, 5])
    with mark_cols[0]:
        if st.button("Mark Completed", type="primary"):
            set_task_status(conn, int(day_number), section, "Completed")
            st.success("Marked Completed.")
            st.rerun()
    with mark_cols[1]:
        if st.button("Mark Pending"):
            set_task_status(conn, int(day_number), section, "Pending")
            st.success("Marked Pending.")
            st.rerun()
    render_day_progress(int(day_number), section)
    if assigned_topic == "No Study":
        st.warning("This is marked as No Study in your plan.")
        return

    result_key = f"last_result_{section}"
    awaiting_next_key = f"awaiting_next_{section}"
    result = st.session_state.get(result_key)
    if st.session_state.get(awaiting_next_key) and result:
        st.subheader("Result")
        if result["is_correct"] is True:
            st.success("Correct")
        elif result["is_correct"] is False:
            st.error("Incorrect")
        else:
            st.warning("Could not auto-evaluate. Correct answer needs manual review.")
        answer_result_boxes(result["correct_answer"])
        st.write(f"Your answer: {result['my_answer']}")
        st.write(f"Correct answer: {result['correct_answer'] or 'Needs Manual Review'}")
        st.write(f"Time taken: {result.get('time_seconds', 0) // 60}:{result.get('time_seconds', 0) % 60:02d}")
        st.markdown("**Explanation**")
        st.write(result["explanation"] or "Explanation not available from PDF extraction.")
        if result["is_correct"] is False:
            st.markdown("**Why my answer is wrong**")
            st.write(result["explanation"] or "Needs Manual Review. No exact wrong-answer explanation was confidently extracted.")
        elif result["is_correct"] is True:
            st.markdown("**Result note**")
            st.write("Your answer matched the correct answer.")
        else:
            st.markdown("**Result note**")
            st.write("Needs Manual Review")
        st.markdown("**Trap type**")
        st.write(result["trap_type"] or "Needs Manual Review")
        st.markdown("**Takeaway rule**")
        st.write(result["takeaway_rule"] or "Needs Manual Review")
        st.markdown("**Source reference**")
        st.write(result["source"])
        if st.button("Next Question", type="primary"):
            st.session_state.pop(result_key, None)
            st.session_state.pop(awaiting_next_key, None)
            st.rerun()
        return

    day_stage = topic_stage_for_day(int(day_number), section)
    session_scope = f"{section}_{int(day_number)}_{assigned_topic}_{assigned_task}".replace(" ", "_")
    active_key = f"active_question_id_{session_scope}"
    timer_key = f"question_started_at_{session_scope}"
    started_key = f"question_timer_started_{session_scope}"
    paused_key = f"question_timer_paused_{session_scope}"
    elapsed_key = f"question_elapsed_seconds_{session_scope}"
    active_id = st.session_state.get(active_key)
    question = None
    if active_id:
        question = conn.execute("SELECT * FROM questions WHERE id = ?", (active_id,)).fetchone()
    if question is None:
        question = next_question(conn, section, assigned_topic, task_terms, day_stage)
        if question is not None:
            st.session_state[active_key] = question["id"]
            st.session_state.pop(timer_key, None)
            st.session_state.pop(paused_key, None)
            st.session_state.pop(elapsed_key, None)
            st.session_state[started_key] = False

    if question is None:
        counts = {row["repeat_status"]: row["count"] for row in topic_repeat_counts(conn, section, assigned_topic, task_terms)}
        new_count = counts.get("New", 0)
        review_count = counts.get("Review", 0)
        attempted_count = counts.get("Attempted", 0)
        st.warning(
            f"No unused {section} questions left for this day/topic. "
            f"New: {new_count} | Review: {review_count} | Attempted: {attempted_count}"
        )
        if attempted_count:
            st.info("You already completed the available clean questions for this exact topic. To repeat them, manually move them to Review.")
            if st.button("Move attempted questions for this topic to Review", type="primary"):
                moved = mark_attempted_topic_review(conn, section, assigned_topic, task_terms)
                st.success(f"Moved {moved} questions to Review. Click Next Question.")
                st.rerun()
        else:
            st.info("There are no clean extracted questions for this exact filter yet.")
        return

    if question["extraction_status"] == "Needs Manual Review":
        st.warning("This item needs manual review. The app will not guess missing answers or choices.")

    choice_map = choices_from_json(question["answer_choices"])
    if set(choice_map) != {"A", "B", "C", "D", "E"}:
        st.error("This question has damaged answer choices and has been removed from practice. Click Next Question.")
        conn.execute("UPDATE questions SET extraction_status = 'Needs Manual Review' WHERE id = ?", (question["id"],))
        conn.commit()
        st.session_state.pop(active_key, None)
        st.session_state.pop(timer_key, None)
        st.session_state.pop(started_key, None)
        st.session_state.pop(paused_key, None)
        st.session_state.pop(elapsed_key, None)
        if st.button("Next Question", type="primary"):
            st.rerun()
        return

    timer_started = bool(st.session_state.get(started_key))
    timer_paused = bool(st.session_state.get(paused_key))
    elapsed_seconds = int(st.session_state.get(elapsed_key, 0) or 0)
    toolbar_cols = st.columns([1.3, 1.4, 0.9, 0.9, 0.72, 0.72, 0.72, 0.72, 0.72])
    with toolbar_cols[0]:
        st.markdown("<div class='exam-toolbar-title'>GMAT<br><u>Timer</u></div>", unsafe_allow_html=True)
    with toolbar_cols[1]:
        if timer_started and not timer_paused:
            live_timer_with_elapsed(st.session_state.get(timer_key, time.time()), elapsed_seconds)
        elif timer_started and timer_paused:
            st.markdown(
                f"<div style='background:#17375e;color:white;border-radius:4px;padding:10px 14px;"
                f"font:700 22px Arial, Helvetica, sans-serif;text-align:center;width:105px;'>{format_elapsed(elapsed_seconds)}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='background:#17375e;color:white;border-radius:4px;padding:10px 14px;"
                "font:700 22px Arial, Helvetica, sans-serif;text-align:center;width:105px;'>0:00</div>",
                unsafe_allow_html=True,
            )
    clicked_answer = None
    with toolbar_cols[2]:
        if not timer_started and st.button("Start", key=f"start_question_{question['id']}", type="primary", use_container_width=True):
            st.session_state[timer_key] = time.time()
            st.session_state[started_key] = True
            st.session_state[paused_key] = False
            st.session_state[elapsed_key] = 0
            st.rerun()
    with toolbar_cols[3]:
        if timer_started and not timer_paused:
            if st.button("Pause", key=f"pause_question_{question['id']}", use_container_width=True):
                st.session_state[elapsed_key] = elapsed_seconds + int(time.time() - st.session_state.get(timer_key, time.time()))
                st.session_state[paused_key] = True
                st.rerun()
        elif timer_started and timer_paused:
            if st.button("Continue", key=f"continue_question_{question['id']}", type="primary", use_container_width=True):
                st.session_state[timer_key] = time.time()
                st.session_state[paused_key] = False
                st.rerun()
    if timer_started:
        for idx, letter in enumerate(["A", "B", "C", "D", "E"], start=4):
            with toolbar_cols[idx]:
                if st.button(letter, key=f"answer_button_{question['id']}_{letter}", use_container_width=True):
                    clicked_answer = letter
    else:
        st.info("Click Start to begin the timer and reveal answer choices.")

    source_line = source_reference(question)
    st.caption(f"{source_line} | {question['section']} | {question['topic']}")
    question_paper(question, choice_map)

    notes = st.text_area("Notes", placeholder="Optional error-log notes")

    if clicked_answer:
            correct_answer = question["correct_answer"]
            is_correct = None if not correct_answer else clicked_answer == correct_answer
            mistake_type = infer_mistake_type(clicked_answer, correct_answer or "")
            if timer_paused:
                time_seconds = elapsed_seconds
            else:
                time_seconds = elapsed_seconds + int(time.time() - st.session_state.get(timer_key, time.time()))
            record_attempt(conn, question, int(day_number), clicked_answer, notes, mistake_type, is_correct, time_seconds)
            st.session_state[result_key] = {
                "question_id": question["id"],
                "is_correct": is_correct,
                "my_answer": clicked_answer,
                "correct_answer": correct_answer,
                "time_seconds": time_seconds,
                "explanation": question["explanation"],
                "trap_type": question["trap_type"],
                "takeaway_rule": question["takeaway_rule"],
                "source": source_reference(question),
            }
            st.session_state[awaiting_next_key] = True
            st.session_state.pop(active_key, None)
            st.session_state.pop(timer_key, None)
            st.session_state.pop(started_key, None)
            st.session_state.pop(paused_key, None)
            st.session_state.pop(elapsed_key, None)
            st.rerun()

    if st.button("Mark this question as Review"):
        mark_review(conn, question["id"], True)
        st.success("Marked for review. It can now repeat.")


def error_log_page() -> None:
    st.header("Error Log")
    attempts = rows_to_frame(attempts_frame(conn))
    if attempts.empty:
        st.info("No attempts logged yet.")
        return
        _ = st.dataframe(attempts, use_container_width=True, hide_index=True)
    csv = attempts.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv, file_name="gmat_error_log.csv", mime="text/csv")


def dashboard_page() -> None:
    st.header("Dashboard")
    stats = dashboard_stats(conn)
    total = stats["totals"]["attempted"] or 0
    correct = stats["totals"]["correct"] or 0
    accuracy = 0 if total == 0 else round(correct / total * 100, 1)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Attempted", total)
    c2.metric("Correct", correct)
    c3.metric("Accuracy", f"{accuracy}%")
    c4.metric("Question Bank", count_questions(conn))

    by_topic = rows_to_frame(stats["by_topic"])
    if not by_topic.empty:
        by_topic["accuracy"] = (by_topic["correct"].fillna(0) / by_topic["attempted"] * 100).round(1)
        st.subheader("Accuracy by Topic")
        _ = st.dataframe(by_topic, use_container_width=True, hide_index=True)
        weak = by_topic.sort_values(["accuracy", "attempted"], ascending=[True, False]).head(5)
        st.subheader("Weak Areas")
        _ = st.dataframe(weak, use_container_width=True, hide_index=True)

    daily = rows_to_frame(stats["daily"])
    st.subheader("Daily Section Progress")
    if daily.empty:
        st.info("No daily practice logged yet.")
    else:
        daily["target"] = daily.apply(
            lambda row: target_label_for_day(int(row["day_number"]), str(row["section"])),
            axis=1,
        )
        daily["minimum_target"] = daily.apply(
            lambda row: target_range_for_day(int(row["day_number"]), str(row["section"]))[0],
            axis=1,
        )
        daily["remaining_to_minimum"] = (daily["minimum_target"] - daily["attempted"]).clip(lower=0)
        daily["accuracy"] = (daily["correct"].fillna(0) / daily["attempted"] * 100).round(1)
        _ = st.dataframe(daily, use_container_width=True, hide_index=True)

    st.subheader("Pending Study Tasks")
    today = today_in_plan_timezone()
    today_day = current_day_number(today)
    pending_rows = []
    for day in range(1, today_day + 1):
        row = plan_row_for_day(day)
        for section in ["Quant", "Verbal"]:
            task = task_for_day(day, section)
            if "no study" in task.lower():
                continue
            status = get_task_status(conn, day, section)
            if status != "Completed":
                pending_rows.append(
                    {
                        "day": day,
                        "date": row["date"],
                        "timeline": timeline_status_for_day(day, today),
                        "section": section,
                        "task": task,
                        "topic": topic_for_day(day, section),
                        "target": target_label_for_day(day, section),
                        "status": status,
                    }
                )
    if pending_rows:
        _ = st.dataframe(pd.DataFrame(pending_rows), use_container_width=True, hide_index=True)
    else:
        st.success("No pending past/current study tasks.")

    traps = rows_to_frame(stats["traps"])
    st.subheader("Repeated Trap Patterns")
    if traps.empty:
        st.info("No trap patterns logged yet.")
    else:
        _ = st.dataframe(traps, use_container_width=True, hide_index=True)

    review = rows_to_frame(stats["review"])
    st.subheader("Questions Marked for Review")
    if review.empty:
        st.info("No review questions.")
    else:
        _ = st.dataframe(review, use_container_width=True, hide_index=True)


def question_bank_page() -> None:
    st.header("Question Bank")
    st.caption("Questions here are approved for Practice.")
    if "last_confirmed_qid" in st.session_state:
        st.success(f"Question #{st.session_state.pop('last_confirmed_qid')} is now in the Ready question bank.")
    status = st.radio("Status", ["Ready", "Needs Manual Review"], horizontal=True)
    st.metric(f"{status} questions", count_questions_by_status(conn, status))
    rows = rows_to_frame(question_bank_rows(conn, status))
    if rows.empty:
        st.info(f"No questions with status: {status}.")
        return
    jump_id = st.number_input("Find question ID", min_value=0, step=1, value=0)
    if jump_id:
        rows = rows[rows["id"] == jump_id]
        if rows.empty:
            st.warning(f"Question #{jump_id} is not currently under status: {status}.")
            return
    _ = st.dataframe(rows, use_container_width=True, hide_index=True)


def manual_review_page() -> None:
    st.header("Manual Review")
    st.caption("Select a row, edit the bad parts, then confirm it into the question bank.")
    rows = conn.execute(
        """
        SELECT
            id, source_pdf, page_number, question_number, section, topic,
            extraction_status, repeat_status, SUBSTR(question_stem, 1, 120) AS question_preview
        FROM questions
        WHERE extraction_status = 'Needs Manual Review'
           OR repeat_status = 'Review'
           OR LENGTH(TRIM(question_stem)) = 0
        ORDER BY id
        LIMIT 200
        """
    ).fetchall()
    frame = rows_to_frame(rows)
    if frame.empty:
        st.info("No questions currently need manual review.")
        return
    selection = st.dataframe(
        frame,
        use_container_width=True,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
    )
    selected_rows = selection.selection.rows if selection and selection.selection else []
    default_qid = int(frame.iloc[selected_rows[0]]["id"]) if selected_rows else int(frame.iloc[0]["id"])
    qid = st.number_input("Selected question ID", min_value=1, step=1, value=default_qid)
    question = conn.execute("SELECT * FROM questions WHERE id = ?", (int(qid),)).fetchone()
    if not question:
        return

    st.divider()
    st.subheader(f"Edit Question #{qid}")
    st.text_area("Raw extracted text from PDF", question["raw_text"], height=180, disabled=True)

    section_options = ["Verbal", "Quant"]
    section = st.radio(
        "Section",
        section_options,
        horizontal=True,
        index=section_options.index(question["section"]) if question["section"] in section_options else 0,
    )
    topic = st.selectbox(
        "Topic",
        TOPIC_OPTIONS,
        index=TOPIC_OPTIONS.index(question["topic"]) if question["topic"] in TOPIC_OPTIONS else 0,
    )
    passage = st.text_area("Passage", question["passage"] or "", height=160)
    question_stem = st.text_area("Question Stem", question["question_stem"] or "", height=160)

    choice_map = choices_from_json(question["answer_choices"])
    st.markdown("**Answer Choices**")
    choice_a = st.text_area("A", choice_map.get("A", ""), height=80)
    choice_b = st.text_area("B", choice_map.get("B", ""), height=80)
    choice_c = st.text_area("C", choice_map.get("C", ""), height=80)
    choice_d = st.text_area("D", choice_map.get("D", ""), height=80)
    choice_e = st.text_area("E", choice_map.get("E", ""), height=80)

    correct = st.selectbox(
        "Correct answer",
        ["", "A", "B", "C", "D", "E"],
        index=["", "A", "B", "C", "D", "E"].index(question["correct_answer"] or ""),
    )
    explanation = st.text_area("Exact explanation from PDF", question["explanation"] or "", height=120)
    trap_type = st.text_input("Trap type", question["trap_type"] or "")
    takeaway_rule = st.text_input("Takeaway rule", question["takeaway_rule"] or "")
    status = st.selectbox("Status after save", ["Needs Manual Review", "Ready"], index=1)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Confirm and send to Question Bank", type="primary"):
            new_choices = {
                "A": choice_a,
                "B": choice_b,
                "C": choice_c,
                "D": choice_d,
                "E": choice_e,
            }
            missing = [letter for letter, text in new_choices.items() if not text.strip()]
            if status == "Ready" and (not question_stem.strip() or not correct or missing):
                st.error("To mark Ready, fill question stem, A-E choices, and correct answer.")
                return
            update_question_manual_fields(
                conn,
                int(qid),
                section,
                topic,
                passage or None,
                question_stem,
                choices_to_json(new_choices),
                correct or None,
                explanation or None,
                trap_type or None,
                takeaway_rule or None,
                status,
                "New" if status == "Ready" else question["repeat_status"],
            )
            if status == "Ready":
                st.session_state["last_confirmed_qid"] = int(qid)
                st.session_state["pending_page"] = "Question Bank"
                st.rerun()
            st.success("Saved for more manual review.")
    with c2:
        review_value = st.checkbox("Allow repeat by marking Review", value=question["repeat_status"] == "Review")
        if st.button("Update repeat status"):
            mark_review(conn, int(qid), review_value)
            st.success("Repeat status updated.")


def main() -> None:
    if "pending_page" in st.session_state:
        st.session_state["page"] = st.session_state.pop("pending_page")
    theme = st.sidebar.radio("Theme", ["Light", "Dark"], horizontal=True, key="theme")
    font_style = st.sidebar.radio("Font style", ["Formal Serif", "Clean Sans"], key="font_style")
    current_page = st.session_state.get("page", "Dashboard")
    inject_exam_css(theme, font_style, current_page)
    st.title("GMAT 705+ Tutor")
    st.caption("Local-only practice app for your GMAT PDFs.")
    page = st.sidebar.radio(
        "Navigate",
        ["Dashboard", "PDF Ingestion", "Study Plan", "Practice", "Question Bank", "Error Log", "Manual Review"],
        key="page",
    )
    st.sidebar.divider()
    st.sidebar.write("PDF access")
    st.sidebar.success("Any PDF can be added locally.")

    if page == "Dashboard":
        dashboard_page()
    elif page == "PDF Ingestion":
        ingest_page()
    elif page == "Study Plan":
        study_plan_page()
    elif page == "Practice":
        practice_page()
    elif page == "Question Bank":
        question_bank_page()
    elif page == "Error Log":
        error_log_page()
    elif page == "Manual Review":
        manual_review_page()


if __name__ == "__main__":
    main()
