import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Real keys and model choices from backend/.env are loaded when the app is imported. Tests must never use them:
# a stray test would otherwise make real, billable calls. Every test starts with all of these blanked.
BLANKED = (
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "TYPESAFE_API_KEY",
    "HUNTER_API_KEY",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "JOOBLE_API_KEY",
    "JEV_PROVIDER",
    "JEV_MODEL",
    "JEV_MIN_RELEVANCE",
    "MODEL_DEFAULT",
    "MODEL_PARSE",
    "MODEL_BRIEF",
    "MODEL_SCORE",
    "MODEL_DRAFT",
    "MODEL_PEOPLE",
)


@pytest.fixture(autouse=True)
def isolate_from_real_settings(monkeypatch, tmp_path):
    for name in BLANKED:
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("PEOPLE_PROVIDER", "none")
    monkeypatch.setenv("PORTAL_SOURCES", "")  # never read real portals in tests
    monkeypatch.setenv("AUTO_REFRESH_HOURS", "0")  # no background timer in tests
    monkeypatch.setenv("DOORKNOCK_DATA", str(tmp_path / "data"))  # never the real database


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DOORKNOCK_DATA", str(tmp_path))
    monkeypatch.setenv("EMBEDDINGS", "hash")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from app import db

    db.reset_engine()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
    db.reset_engine()
