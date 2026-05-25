# GMAT 705+ Tutor App

Local Streamlit app for practicing from your GMAT PDFs.

The app does not use internet question banks, does not generate custom questions, and does not paraphrase questions. If it cannot confidently extract answer choices or the correct answer, it marks the item as `Needs Manual Review`.

## Features

- Upload or ingest any GMAT PDF whenever you want.
- Extract PDF text page by page with PyMuPDF.
- Store local question bank, attempts, review status, and error log in SQLite.
- Separate Verbal and Quant practice sections.
- Uses the exact day-wise plan from `25-May` through `16-Aug`.
- `START DAY X` loads that day's Quant or Verbal task from the plan.
- Tracks time taken for every submitted question.
- Before each question, the app asks `Ready? Y/N`.
- Prevents repeats after an attempt unless you manually mark a question as `Review`.
- Tracks date, day number, section, topic, source PDF, question/page, answer, correctness, mistake type, trap pattern, notes, and reattempt status.
- Dashboard for accuracy by topic, attempted/correct counts, weak areas, repeated trap patterns, and review questions.

## Windows Setup

Open PowerShell in this folder:

```powershell
cd C:\Users\Aditya\OneDrive\Documents\Talentradar\gmat705_tutor
```

Create and activate a virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run the app:

```powershell
streamlit run app.py
```

Streamlit will print a local URL, usually `http://localhost:8501`.

## Adding PDFs

You can either upload PDFs in the `PDF Ingestion` page or ingest them from local paths such as:

```text
C:\Users\Aditya\Downloads\GMAT 1748 Compiled numbered version.pdf
C:\Users\Aditya\Downloads\GMAT 844 Verbal numbered version.pdf
C:\Users\Aditya\Downloads\Manhattan All the Verbal.pdf
```

Uploaded or ingested files are copied into:

```text
gmat705_tutor\data\uploads
```

The SQLite database is stored at:

```text
gmat705_tutor\data\gmat_tutor.sqlite
```

## Manual Review Policy

PDF extraction is imperfect. The app follows a strict no-guessing policy:

- Missing A/B/C/D/E choices: `Needs Manual Review`
- Missing correct answer: `Needs Manual Review`
- Missing explanation, trap type, or takeaway: shown as `Needs Manual Review`

Use the `Manual Review` page only to enter information copied from your PDFs or your own post-practice notes.

## Notes

- The app tracks time per question after you click `Ready`.
- The app does not call any LLM or external question source.
- The app stores all data locally.
