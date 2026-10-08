"""Settings, read from the environment on every call so tests can override them."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")


def data_dir() -> Path:
    path = Path(os.getenv("DOORKNOCK_DATA") or BACKEND_DIR / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


def anthropic_model() -> str:
    return env("ANTHROPIC_MODEL", "claude-sonnet-5-5")


def daily_token_cap() -> int:
    return int(env("DAILY_TOKEN_CAP", "2000000"))


def people_provider() -> str:
    return env("PEOPLE_PROVIDER", "none").lower()


def google_client_secret_file() -> Path:
    raw = env("GOOGLE_CLIENT_SECRET_FILE", "data/google_client_secret.json")
    path = Path(raw)
    return path if path.is_absolute() else BACKEND_DIR / path


# ---- which model does which job -------------------------------------------------
# A model id with a "/" (e.g. "deepseek/deepseek-v3.2") goes through OpenRouter; a plain id
# (e.g. "claude-sonnet-5-5") goes straight to Anthropic. Each job takes a comma-separated chain:
# the first model is tried first, and the next ones only if it is rate-limited, down or returns bad output.
TASKS = {
    "resume_parse": "PARSE",
    "brief_chat": "BRIEF",
    "score": "SCORE",
    "draft": "DRAFT",
    "people_rank": "PEOPLE",
}

# Used when OPENROUTER_API_KEY is set and the job has no MODEL_* override.
OPENROUTER_DEFAULTS = {
    "PARSE": "nvidia/nemotron-3-super-120b-a12b:free,openai/gpt-oss-120b",  # free first, cheap fallback
    "BRIEF": "google/gemini-3.1-flash-lite,openai/gpt-oss-120b",
    "SCORE": "google/gemini-3.1-flash-lite,openai/gpt-oss-120b",  # high volume, so cheap with a big context
    "DRAFT": "deepseek/deepseek-v3.2,openai/gpt-5.4-nano",  # cheap writers; the quote checker guards the facts
    "PEOPLE": "anthropic/claude-sonnet-5.5,openai/gpt-5.6-terra",  # small prompt, so a strong model costs cents
}


def openrouter_key() -> str:
    return env("OPENROUTER_API_KEY")


def anthropic_key() -> str:
    return env("ANTHROPIC_API_KEY")


def llm_ready() -> bool:
    return bool(openrouter_key() or anthropic_key())


def model_chain(purpose: str) -> list[str]:
    """Models to try for this job, best first."""
    key = TASKS.get(purpose, "DEFAULT")
    override = env(f"MODEL_{key}") or env("MODEL_DEFAULT")
    if override:
        return [m.strip() for m in override.split(",") if m.strip()]
    if openrouter_key():
        return [m.strip() for m in OPENROUTER_DEFAULTS.get(key, OPENROUTER_DEFAULTS["BRIEF"]).split(",")]
    return [anthropic_model()]


def uses_openrouter(model: str) -> bool:
    return "/" in model


# ---- Jev (relevance gate) ---------------------------------------------------------
def typesafe_key() -> str:
    return env("TYPESAFE_API_KEY")


def jev_backend() -> tuple[str, str, str, str] | None:
    """Where to call Jev: (name, endpoint, api key, default model). OpenRouter first, since its one key also covers the
    other models and there is no separate account; otherwise TypeSafe directly. None if neither key is set."""
    choice = env("JEV_PROVIDER", "auto").lower()
    if choice in ("auto", "openrouter") and openrouter_key():
        return "openrouter", "https://openrouter.ai/api/v1/systemone", openrouter_key(), "~typesafe/jev-latest"
    if choice in ("auto", "typesafe") and typesafe_key():
        return "typesafe", "https://api.typesafe.ai/v1/systemone", typesafe_key(), "jev-latest"
    return None


def jev_min_relevance() -> float:
    """Jobs Jev rates below this (0-1) are set aside before the scoring model sees them."""
    try:
        return max(0.0, min(1.0, float(env("JEV_MIN_RELEVANCE", "0.35"))))
    except ValueError:
        return 0.35
