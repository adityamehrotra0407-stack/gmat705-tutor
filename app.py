from __future__ import annotations

import html
import json
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from gmat_tutor.classifiers import classify_topic, infer_mistake_type, infer_section
from gmat_tutor.config import ensure_dirs
from gmat_tutor.curated_import import import_curated_frame, read_curated_path, read_curated_upload
from gmat_tutor.db import (
    attempts_frame, audit_ready_questions, connect, count_questions, count_questions_by_status,
    dashboard_stats, day_section_progress, fetch_sources, init_db, mark_attempted_topic_review,
    mark_review, question_bank_rows, record_attempt, reclassify_question_bank, topic_counts,
    topic_repeat_counts, update_question_manual_fields,
)
from gmat_tutor.pdf_ingest import copy_pdf_to_uploads, ingest_pdf, save_upload, validate_pdf_name
from gmat_tutor.study_plan import (
    STUDY_PLAN, plan_preview, plan_row_for_day, search_terms_for_task, target_label_for_day,
    target_range_for_day, task_for_day, topic_for_day,
)

PLAN_YEAR = 2026
PLAN_TIMEZONE = "Asia/Kolkata"
LETTERS = ["A", "B", "C", "D", "E"]
TOPIC_OPTIONS = [
    "CR Assumption", "CR Weaken", "CR Strengthen", "Boldface", "Logical Flaw", "Inference", "RC",
    "Verbal Mixed", "Arithmetic", "Algebra", "Number Properties", "Word Problems", "Geometry",
    "Data Sufficiency", "Quant Mixed",
]

st.set_page_config(page_title="GMAT 705+ Tutor", page_icon="705+", layout="wide")
ensure_dirs()
conn = connect()
init_db(conn)
conn.execute("""
    CREATE TABLE IF NOT EXISTS study_task_status (
        day_number INTEGER NOT NULL,
        section TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        updated_at TEXT NOT NULL,
        PRIMARY KEY (day_number, section)
    )
""")
try:
    conn.execute("ALTER TABLE questions ADD COLUMN difficulty TEXT")
except Exception:
    pass
conn.commit()

if "sections_reclassified_once" not in st.session_state:
    reclassify_question_bank(conn, classify_topic, infer_section)
    audit_ready_questions(conn)
    st.session_state["sections_reclassified_once"] = True


def today_in_plan_timezone() -> date:
    return datetime.now(ZoneInfo(PLAN_TIMEZONE)).date()


def plan_date_for_day(day_number: int) -> date:
    day_number = max(1, min(int(day_number), len(STUDY_PLAN)))
    return datetime.strptime(f"{STUDY_PLAN[day_number - 1][0]}-{PLAN_YEAR}", "%d-%b-%Y").date()


def current_day_number(today: date | None = None) -> int:
    today = today or today_in_plan_timezone()
    if today <= plan_date_for_day(1):
        return 1
    if today >= plan_date_for_day(len(STUDY_PLAN)):
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


def topic_stage_for_day(day_number: int, section: str) -> int:
    topic = topic_for_day(day_number, section)
    if topic in {"No Study", "Verbal Mixed", "Quant Mixed"}:
        return 3
    stage = sum(1 for day in range(1, day_number + 1) if topic_for_day(day, section) == topic)
    return max(1, min(stage, 3))


def get_task_status(day_number: int, section: str) -> str:
    row = conn.execute("SELECT status FROM study_task_status WHERE day_number = ? AND section = ?", (day_number, section)).fetchone()
    return row["status"] if row else "Pending"


def set_task_status(day_number: int, section: str, status: str) -> None:
    conn.execute(
        """
        INSERT INTO study_task_status (day_number, section, status, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(day_number, section) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
        """,
        (day_number, section, status, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def stage_order_sql(stage: int) -> str:
    if stage <= 1:
        return """
            CASE
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%easy%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%600%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%medium%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%700%' THEN 2
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%hard%' THEN 2
                ELSE 1
            END,
            id ASC
        """
    if stage == 2:
        return """
            CASE
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%medium%' THEN 0
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%700%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%hard%' THEN 1
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%easy%' THEN 2
                WHEN LOWER(COALESCE(difficulty, '')) LIKE '%600%' THEN 2
                ELSE 1
            END,
            id ASC
        """
    return """
        CASE
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%700%' THEN 0
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%800%' THEN 0
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%hard%' THEN 0
            WHEN LOWER(COALESCE(difficulty, '')) LIKE '%medium%' THEN 1
            ELSE 2
        END,
        id DESC
    """


def next_day_question(section: str, topic: str, search_terms: list[str], stage: int):
    params: list[object] = [section]
    topic_clause = ""
    if topic not in {"Verbal Mixed", "Quant Mixed"}:
        topic_clause = "AND topic = ?"
        params.append(topic)
    term_clause = ""
    if search_terms:
        term_clause = " AND (" + " OR ".join("LOWER(question_stem) LIKE ?" for _ in search_terms) + ")"
        params.extend([f"%{term.lower()}%" for term in search_terms])
    where_sql = f"""
        section = ?
        {topic_clause}
        AND extraction_status = 'Ready'
        AND LENGTH(TRIM(question_stem)) > 0
        {term_clause}
        AND (repeat_status = 'New' OR repeat_status = 'Review')
    """
    query_params = tuple(params)
    count = int(conn.execute(f"SELECT COUNT(*) AS c FROM questions WHERE {where_sql}", query_params).fetchone()["c"])
    if count == 0:
        return None
    offset = 0 if stage <= 1 else count // 3 if stage == 2 else (count * 2) // 3
    return conn.execute(
        f"""
        SELECT *
        FROM questions
        WHERE {where_sql}
        ORDER BY CASE repeat_status WHEN 'Review' THEN 0 ELSE 1 END, {stage_order_sql(stage)}
        LIMIT 1 OFFSET ?
        """,
        (*query_params, min(offset, count - 1)),
    ).fetchone()


def inject_css(theme: str, font_style: str, page: str) -> None:
    dark = theme == "Dark"
    bg = "#0f172a" if dark else "#f5f5f0"
    text = "#e5e7eb" if dark else "#111827"
    panel = "#111827" if dark else "#ffffff"
    border = "#334155" if dark else "#c9ced6"
    sidebar = "#0b1220" if dark else "#f8fafc"
    selected = "#1d4ed8" if dark else "#dbeafe"
    body_font = 'Arial, Helvetica, sans-serif' if font_style == "Clean Sans" else 'Georgia, "Times New Roman", serif'
    practice_css = ""
    if page == "Practice":
        practice_css = f"""
        section[data-testid="stSidebar"] {{ position:fixed!important; left:0; top:0; bottom:0; width:290px!important; min-width:290px!important; transform:translateX(-274px); transition:transform 180ms ease; z-index:999; box-shadow:2px 0 14px rgba(15,23,42,.18); }}
        section[data-testid="stSidebar"]::after {{ content:""; position:absolute; right:-8px; top:0; width:10px; height:100%; background:{border}; }}
        section[data-testid="stSidebar"]:hover, section[data-testid="stSidebar"]:focus-within {{ transform:translateX(0); }}
        .block-container {{ max-width:100%!important; padding:28px 42px!important; }}
        h1 {{ font-size:28px!important; }}
        .question-paper {{ max-width:1180px!important; font-size:16px!important; line-height:1.46!important; }}
        """
    st.markdown(f"""
        <style>
        .stApp {{ background:{bg}; color:{text}; font-family:{body_font}; }}
        .stApp p,.stApp span,.stApp label,.stApp div {{ color:{text}; }}
        h1,h2,h3 {{ color:{text}; font-family:Arial, Helvetica, sans-serif; letter-spacing:0; }}
        section[data-testid="stSidebar"] {{ background:{sidebar}; border-right:1px solid {border}; }}
        section[data-testid="stSidebar"] * {{ color:{text}!important; }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label {{ border-radius:6px; padding:6px 8px; min-height:34px; }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {{ background:{selected}; border:1px solid {border}; }}
        div[data-testid="stMetric"] {{ background:{panel}; border:1px solid {border}; border-radius:4px; padding:10px 12px; }}
        input, textarea, div[data-baseweb="select"] > div {{ background:{panel}!important; color:{text}!important; border-color:{border}!important; }}
        div[data-testid="stButton"] button {{ background:#fff!important; color:#155eb5!important; border:1px solid #aeb7c3!important; border-radius:4px!important; }}
        div[data-testid="stButton"] button[kind="primary"] {{ min-height:44px; font:700 17px Arial, Helvetica, sans-serif!important; }}
        .question-paper {{ background:#fff; color:#111827!important; border:1px solid #d1d5db; border-radius:2px; padding:26px 34px; font-family:Arial, Helvetica, sans-serif; font-size:18px; line-height:1.48; white-space:pre-wrap; max-width:980px; margin:0 auto; }}
        .answer-result-grid {{ display:grid; grid-template-columns:repeat(5,minmax(74px,1fr)); gap:14px; margin:18px 0 26px; }}
        .answer-result-box {{ border-radius:6px; padding:16px 12px; text-align:center; font:700 28px Arial, Helvetica, sans-serif; color:#fff!important; }}
        .answer-result-box.correct {{ background:#15803d; }} .answer-result-box.wrong {{ background:#dc2626; }}
        {practice_css}
        </style>
    """, unsafe_allow_html=True)


def rows_to_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(row) for row in rows])


def choices_from_json(answer_choices: str) -> dict[str, str]:
    try:
        choices = json.loads(answer_choices or "[]")
    except json.JSONDecodeError:
        choices = []
    return {str(c.get("letter", "")).strip().upper(): str(c.get("text", "")).strip() for c in choices if str(c.get("letter", "")).strip().upper() in set(LETTERS)}


def choices_to_json(choice_map: dict[str, str]) -> str:
    return json.dumps([{"letter": l, "text": choice_map.get(l, "").strip()} for l in LETTERS], ensure_ascii=False, indent=2)


def source_reference(question) -> str:
    parts = [question["source_pdf"]]
    if question["page_number"]:
        parts.append(f"page {question['page_number']}")
    if question["question_number"]:
        parts.append(f"question {question['question_number']}")
    return " | ".join(parts)


def question_paper(question, choices: dict[str, str]) -> None:
    parts = []
    if question["passage"]:
        parts.append(str(question["passage"]).strip())
    parts.append(str(question["question_stem"] or "").strip())
    parts.append("")
    for letter in LETTERS:
        parts.append(f"{letter}. {choices.get(letter, '')}")
    st.markdown(f"<div class='question-paper'>{html.escape(chr(10).join(parts))}</div>", unsafe_allow_html=True)


def answer_result_boxes(correct: str | None) -> None:
    boxes = [f"<div class='answer-result-box {'correct' if correct == l else 'wrong'}'>{l}</div>" for l in LETTERS]
    st.markdown(f"<div class='answer-result-grid'>{''.join(boxes)}</div>", unsafe_allow_html=True)


def format_elapsed(seconds: int | float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def live_timer(started_at: float, base_seconds: int = 0) -> None:
    components.html(f"""
        <div id="timer" style="background:#17375e;color:white;border-radius:4px;padding:10px 14px;font:700 22px Arial;text-align:center;width:105px;box-sizing:border-box;">0:00</div>
        <script>
        const start={int(started_at*1000)}, base={int(base_seconds*1000)}, el=document.getElementById('timer');
        function tick(){{const s=Math.max(0,Math.floor((base+Date.now()-start)/1000));el.textContent=Math.floor(s/60)+':'+String(s%60).padStart(2,'0');}}
        tick(); setInterval(tick,1000);
        </script>
    """, height=52)


def ingest_page() -> None:
    st.header("PDF Ingestion")
    st.caption("Upload any GMAT PDF you want to use. Anything uncertain is marked for manual review.")
    uploaded = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
    if uploaded and st.button("Ingest uploaded PDFs", type="primary"):
        for file in uploaded:
            try:
                st.success(f"{file.name}: {ingest_pdf(conn, save_upload(file))}")
            except Exception as exc:
                st.error(f"{file.name}: {exc}")
    st.divider()
    st.subheader("Import curated questions")
    st.caption("Use CSV/Excel columns: Difficulty, section, topic, question, A, B, C, D, E, correct_answer.")
    upload = st.file_uploader("Upload curated CSV or Excel", type=["csv", "xlsx", "xls"], key="curated_question_upload")
    if upload and st.button("Import curated questions", type="primary"):
        try:
            st.success(f"{upload.name}: {import_curated_frame(conn, read_curated_upload(upload), upload.name)}")
        except Exception as exc:
            st.error(str(exc))
    path = st.text_input("Curated CSV/Excel local path", placeholder="outputs/new_materials/combined_ready_questions.csv")
    if st.button("Import curated file from local path") and path:
        try:
            source = Path(path)
            if not source.is_absolute():
                source = Path.cwd() / source
            if not source.exists():
                st.error("That curated file path does not exist.")
            else:
                st.success(f"{source.name}: {import_curated_frame(conn, read_curated_path(source), source.name)}")
        except Exception as exc:
            st.error(str(exc))
    st.divider()
    st.subheader("Current Sources")
    st.dataframe(rows_to_frame(fetch_sources(conn)), use_container_width=True, hide_index=True)
    st.subheader("Question Bank Summary")
    if st.button("Reclassify existing questions into Quant / Verbal"):
        changed = reclassify_question_bank(conn, classify_topic, infer_section)
        flagged = audit_ready_questions(conn)
        st.success(f"Reclassified {changed} questions. Moved {flagged} bad parses back to Manual Review.")
    st.dataframe(rows_to_frame(topic_counts(conn)), use_container_width=True, hide_index=True)


def study_plan_page() -> None:
    st.header("Study Plan")
    today = today_in_plan_timezone()
    today_day = current_day_number(today)
    st.info(f"Today is {today.isoformat()} | Current study day: Day {today_day}")
    view = st.radio("View", ["Full Plan", "Verbal Only", "Quant Only"], horizontal=True)
    days = st.slider("Preview days", 6, len(STUDY_PLAN), len(STUDY_PLAN))
    if view == "Verbal Only":
        frame = pd.DataFrame(plan_preview(days, "Verbal"))
        frame["timeline"] = frame["day"].apply(lambda d: timeline_status_for_day(int(d), today))
        frame["stage"] = frame["day"].apply(lambda d: topic_stage_for_day(int(d), "Verbal"))
        frame["status"] = frame["day"].apply(lambda d: get_task_status(int(d), "Verbal"))
    elif view == "Quant Only":
        frame = pd.DataFrame(plan_preview(days, "Quant"))
        frame["timeline"] = frame["day"].apply(lambda d: timeline_status_for_day(int(d), today))
        frame["stage"] = frame["day"].apply(lambda d: topic_stage_for_day(int(d), "Quant"))
        frame["status"] = frame["day"].apply(lambda d: get_task_status(int(d), "Quant"))
    else:
        frame = pd.DataFrame(plan_preview(days))
        frame["timeline"] = frame["day"].apply(lambda d: timeline_status_for_day(int(d), today))
        frame["quant_status"] = frame["day"].apply(lambda d: get_task_status(int(d), "Quant"))
        frame["verbal_status"] = frame["day"].apply(lambda d: get_task_status(int(d), "Verbal"))
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.subheader("Update Previous / Current Task Status")
    c1, c2, c3 = st.columns(3)
    with c1:
        day = st.number_input("Day to update", min_value=1, max_value=today_day, value=today_day, step=1)
    with c2:
        section = st.radio("Section", ["Verbal", "Quant"], horizontal=True, key="status_update_section")
    with c3:
        status = st.selectbox("Set status", ["Pending", "Completed"])
    row = plan_row_for_day(int(day))
    st.caption(f"Selected: Day {int(day)} ({row['date']}) | {task_for_day(int(day), section)}")
    if st.button("Save task status", type="primary"):
        set_task_status(int(day), section, status)
        st.success(f"Day {int(day)} {section} marked {status}.")
        st.rerun()


def render_day_progress(day: int, section: str) -> None:
    target_low, target_high = target_range_for_day(day, section)
    progress = day_section_progress(conn, day, section)
    attempted = int(progress["attempted"] or 0)
    correct = int(progress["correct"] or 0)
    avg_time = progress["avg_time_seconds"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Target", target_label_for_day(day, section))
    c2.metric("Done", attempted)
    c3.metric("Correct", correct)
    c4.metric("Avg time", "N/A" if avg_time is None else f"{avg_time}s")
    pct = 0 if target_high == 0 else min(100, round(attempted / max(target_low, 1) * 100))
    st.progress(pct / 100, text=f"{attempted}/{target_low} minimum target completed")


def practice_page() -> None:
    st.header("Practice")
    st.caption("No generated questions. No topic switching inside a day.")
    section = st.radio("Choose section", ["Verbal", "Quant"], horizontal=True)
    today = today_in_plan_timezone()
    default_day = current_day_number(today)
    day = int(st.number_input("Day number", min_value=1, max_value=len(STUDY_PLAN), value=default_day, step=1))
    row = plan_row_for_day(day)
    task = task_for_day(day, section)
    topic = topic_for_day(day, section)
    stage = topic_stage_for_day(day, section)
    terms = search_terms_for_task(task, section)
    st.info(f"START {section.upper()} DAY {day} ({row['date']}) loads: {task} -> {topic} | Stage {stage} | Target: {target_label_for_day(day, section)} | {timeline_status_for_day(day, today)} | Status: {get_task_status(day, section)}")
    if day < default_day and get_task_status(day, section) != "Completed":
        st.warning("This previous task is still Pending. Complete it now, then mark it Completed below.")
    c1, c2, _ = st.columns([1, 1, 5])
    with c1:
        if st.button("Mark Completed", type="primary"):
            set_task_status(day, section, "Completed")
            st.rerun()
    with c2:
        if st.button("Mark Pending"):
            set_task_status(day, section, "Pending")
            st.rerun()
    render_day_progress(day, section)
    if topic == "No Study":
        st.warning("This is marked as No Study in your plan.")
        return

    scope = f"{section}_{day}_{topic}_{task}".replace(" ", "_").replace("/", "_")
    result_key = f"last_result_{scope}"
    awaiting_key = f"awaiting_next_{scope}"
    result = st.session_state.get(result_key)
    if st.session_state.get(awaiting_key) and result:
        st.subheader("Result")
        st.success("Correct") if result["is_correct"] is True else st.error("Incorrect") if result["is_correct"] is False else st.warning("Could not auto-evaluate.")
        answer_result_boxes(result["correct_answer"])
        st.write(f"Your answer: {result['my_answer']}")
        st.write(f"Correct answer: {result['correct_answer'] or 'Needs Manual Review'}")
        st.write(f"Time taken: {format_elapsed(result.get('time_seconds', 0))}")
        st.markdown("**Explanation**")
        st.write(result["explanation"] or "Explanation not available from PDF extraction.")
        st.markdown("**Source reference**")
        st.write(result["source"])
        if st.button("Next Question", type="primary"):
            st.session_state.pop(result_key, None)
            st.session_state.pop(awaiting_key, None)
            st.rerun()
        return

    active_key = f"active_question_id_{scope}"
    timer_key = f"question_started_at_{scope}"
    started_key = f"question_timer_started_{scope}"
    paused_key = f"question_timer_paused_{scope}"
    elapsed_key = f"question_elapsed_seconds_{scope}"
    q = None
    if st.session_state.get(active_key):
        q = conn.execute("SELECT * FROM questions WHERE id = ?", (st.session_state[active_key],)).fetchone()
    if q is None:
        q = next_day_question(section, topic, terms, stage)
        if q:
            st.session_state[active_key] = q["id"]
            st.session_state[started_key] = False
            for key in [timer_key, paused_key, elapsed_key]:
                st.session_state.pop(key, None)
    if q is None:
        counts = {r["repeat_status"]: r["count"] for r in topic_repeat_counts(conn, section, topic, terms)}
        st.warning(f"No unused {section} questions left for this day/topic. New: {counts.get('New', 0)} | Review: {counts.get('Review', 0)} | Attempted: {counts.get('Attempted', 0)}")
        if counts.get("Attempted", 0) and st.button("Move attempted questions for this topic to Review", type="primary"):
            moved = mark_attempted_topic_review(conn, section, topic, terms)
            st.success(f"Moved {moved} questions to Review.")
            st.rerun()
        return

    choices = choices_from_json(q["answer_choices"])
    if set(choices) != set(LETTERS):
        conn.execute("UPDATE questions SET extraction_status = 'Needs Manual Review' WHERE id = ?", (q["id"],))
        conn.commit()
        st.error("This question has damaged answer choices and has been removed from practice. Click Next Question.")
        st.session_state.pop(active_key, None)
        if st.button("Next Question", type="primary"):
            st.rerun()
        return

    started = bool(st.session_state.get(started_key))
    paused = bool(st.session_state.get(paused_key))
    elapsed = int(st.session_state.get(elapsed_key, 0) or 0)
    cols = st.columns([1.1, 1.2, 0.9, 0.9, 0.7, 0.7, 0.7, 0.7, 0.7])
    cols[0].markdown("<div style='font:700 15px Arial;color:#111827'>GMAT<br><u>Timer</u></div>", unsafe_allow_html=True)
    with cols[1]:
        if started and not paused:
            live_timer(st.session_state.get(timer_key, time.time()), elapsed)
        else:
            st.markdown(f"<div style='background:#17375e;color:white;border-radius:4px;padding:10px 14px;font:700 22px Arial;text-align:center;width:105px'>{format_elapsed(elapsed)}</div>", unsafe_allow_html=True)
    clicked = None
    with cols[2]:
        if not started and st.button("Start", key=f"start_{scope}_{q['id']}", type="primary", use_container_width=True):
            st.session_state[timer_key] = time.time()
            st.session_state[started_key] = True
            st.session_state[paused_key] = False
            st.session_state[elapsed_key] = 0
            st.rerun()
    with cols[3]:
        if started and not paused and st.button("Pause", key=f"pause_{scope}_{q['id']}", use_container_width=True):
            st.session_state[elapsed_key] = elapsed + int(time.time() - st.session_state.get(timer_key, time.time()))
            st.session_state[paused_key] = True
            st.rerun()
        if started and paused and st.button("Continue", key=f"continue_{scope}_{q['id']}", type="primary", use_container_width=True):
            st.session_state[timer_key] = time.time()
            st.session_state[paused_key] = False
            st.rerun()
    if started:
        for i, letter in enumerate(LETTERS, start=4):
            with cols[i]:
                if st.button(letter, key=f"answer_{scope}_{q['id']}_{letter}", use_container_width=True):
                    clicked = letter
    else:
        st.info("Click Start to begin the timer and reveal answer choices.")
    st.caption(f"{source_reference(q)} | {q['section']} | {q['topic']} | difficulty: {q['difficulty'] or 'auto'}")
    question_paper(q, choices)
    notes = st.text_area("Notes", placeholder="Optional error-log notes")
    if clicked:
        correct = q["correct_answer"]
        is_correct = None if not correct else clicked == correct
        seconds = elapsed if paused else elapsed + int(time.time() - st.session_state.get(timer_key, time.time()))
        record_attempt(conn, q, day, clicked, notes, infer_mistake_type(clicked, correct or ""), is_correct, seconds)
        st.session_state[result_key] = {"is_correct": is_correct, "my_answer": clicked, "correct_answer": correct, "time_seconds": seconds, "explanation": q["explanation"], "source": source_reference(q)}
        st.session_state[awaiting_key] = True
        for key in [active_key, timer_key, started_key, paused_key, elapsed_key]:
            st.session_state.pop(key, None)
        st.rerun()
    if st.button("Mark this question as Review"):
        mark_review(conn, q["id"], True)
        st.success("Marked for review. It can now repeat.")


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
    st.subheader("Pending Study Tasks")
    today = today_in_plan_timezone()
    today_day = current_day_number(today)
    pending = []
    for day in range(1, today_day + 1):
        row = plan_row_for_day(day)
        for section in ["Quant", "Verbal"]:
            task = task_for_day(day, section)
            if "no study" not in task.lower() and get_task_status(day, section) != "Completed":
                pending.append({"day": day, "date": row["date"], "timeline": timeline_status_for_day(day, today), "section": section, "task": task, "topic": topic_for_day(day, section), "target": target_label_for_day(day, section), "status": "Pending"})
    st.dataframe(pd.DataFrame(pending), use_container_width=True, hide_index=True) if pending else st.success("No pending past/current study tasks.")
    daily = rows_to_frame(stats.get("daily", []))
    st.subheader("Daily Section Progress")
    st.dataframe(daily, use_container_width=True, hide_index=True) if not daily.empty else st.info("No daily practice logged yet.")
    traps = rows_to_frame(stats["traps"])
    st.subheader("Repeated Trap Patterns")
    st.dataframe(traps, use_container_width=True, hide_index=True) if not traps.empty else st.info("No trap patterns logged yet.")


def question_bank_page() -> None:
    st.header("Question Bank")
    status = st.radio("Status", ["Ready", "Needs Manual Review"], horizontal=True)
    st.metric(f"{status} questions", count_questions_by_status(conn, status))
    rows = rows_to_frame(question_bank_rows(conn, status))
    if rows.empty:
        st.info(f"No questions with status: {status}.")
        return
    jump_id = st.number_input("Find question ID", min_value=0, step=1, value=0)
    if jump_id:
        rows = rows[rows["id"] == jump_id]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def manual_review_page() -> None:
    st.header("Manual Review")
    rows = conn.execute("""
        SELECT id, source_pdf, page_number, question_number, section, topic, extraction_status, repeat_status, SUBSTR(question_stem, 1, 120) AS question_preview
        FROM questions
        WHERE extraction_status = 'Needs Manual Review' OR repeat_status = 'Review' OR LENGTH(TRIM(question_stem)) = 0
        ORDER BY id LIMIT 200
    """).fetchall()
    frame = rows_to_frame(rows)
    if frame.empty:
        st.info("No questions currently need manual review.")
        return
    st.dataframe(frame, use_container_width=True, hide_index=True)


def error_log_page() -> None:
    st.header("Error Log")
    attempts = rows_to_frame(attempts_frame(conn))
    if attempts.empty:
        st.info("No attempts logged yet.")
        return
    st.dataframe(attempts, use_container_width=True, hide_index=True)
    st.download_button("Download CSV", data=attempts.to_csv(index=False).encode("utf-8"), file_name="gmat_error_log.csv", mime="text/csv")


def main() -> None:
    theme = st.sidebar.radio("Theme", ["Light", "Dark"], horizontal=True, key="theme")
    font_style = st.sidebar.radio("Font style", ["Formal Serif", "Clean Sans"], key="font_style")
    page = st.sidebar.radio("Navigate", ["Dashboard", "PDF Ingestion", "Study Plan", "Practice", "Question Bank", "Error Log", "Manual Review"], key="page")
    inject_css(theme, font_style, page)
    st.title("GMAT 705+ Tutor")
    st.caption("Local-only practice app for your GMAT PDFs.")
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
