from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "gmat_tutor.sqlite"

VERBAL_TOPIC_SEQUENCE = [
    "CR Assumption",
    "CR Weaken",
    "CR Strengthen",
    "RC",
    "Boldface",
    "Verbal Mixed",
]

QUANT_TOPIC_SEQUENCE = [
    "Arithmetic",
    "Algebra",
    "Number Properties",
    "Word Problems",
    "Geometry",
    "Data Sufficiency",
    "Quant Mixed",
]

TOPIC_SEQUENCE = VERBAL_TOPIC_SEQUENCE


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
