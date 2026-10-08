"""Scoring runs on worker threads that each log their AI usage to the database. That must not collide with the run
itself writing progress ("database is locked" lost most of a real search's scores)."""
import time

from sqlalchemy import func, select

from app import db, llm
from app.models import LlmCall
from app.services import sources
from tests.test_api_flow import fake_structured, make_docx, wait_for_run


def test_scoring_threads_can_log_llm_calls_while_a_run_is_in_progress(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")  # use the real routing code, with the network call replaced
    monkeypatch.setenv("JEV_PROVIDER", "typesafe")  # no TypeSafe key, so the Jev step is skipped (it would call the network)
    postings = [
        sources.RawJob(str(i), f"Backend Engineer {i}", "Bengaluru, India", f"Build services in Go. Posting {i}.", f"https://x/{i}")
        for i in range(12)
    ]
    monkeypatch.setattr(sources, "fetch", lambda ats, slug, hints=None: list(postings) if slug == "stripe" else [])

    def fake_model_call(model, system, messages, schema, tool_name, max_tokens, purpose):
        llm._log(purpose, model, 100, 20)  # exactly what the real call does, from whichever thread called it
        time.sleep(0.05)  # keep the worker threads overlapping with the run's own writes
        user = messages[-1]["content"] if len(messages) == 1 else messages
        return fake_structured(purpose=purpose, system=system, user=user, schema=schema)

    monkeypatch.setattr(llm, "_call_openrouter", fake_model_call)

    assert client.post("/api/resume", files={"file": ("cv.docx", make_docx(), "application/octet-stream")}).status_code == 200
    client.post("/api/brief/chat", json={"message": "backend roles in Bengaluru"})
    assert client.post("/api/runs", json={}).status_code == 200
    run = wait_for_run(client, timeout=60)

    assert run["status"] == "done", run
    assert run["detail"]["scored"] == 12 and run["detail"]["failed"] == 0, run["detail"]
    assert len(client.get("/api/jobs").json()) == 12
    with db.session_scope() as s:
        assert s.execute(select(func.count()).select_from(LlmCall).where(LlmCall.purpose == "score")).scalar_one() == 12


def test_aggregator_jobs_are_filed_under_their_employer_when_keys_are_set(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("JEV_PROVIDER", "typesafe")
    monkeypatch.setattr(
        llm, "_call_openrouter",
        lambda model, system, messages, schema, tool_name, max_tokens, purpose: fake_structured(
            purpose=purpose, system=system, user=messages[-1]["content"] if len(messages) == 1 else messages, schema=schema
        ),
    )
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setattr(sources, "fetch", lambda ats, slug, hints=None: [])
    monkeypatch.setattr(
        sources, "fetch_adzuna",
        lambda *a, **k: [sources.RawJob("adzuna-1", "Junior Developer", "Noida, Uttar Pradesh", "React and Node.", "https://x/1", employer="Acme Soft")],
    )
    assert client.get("/api/state").json()["setup"]["aggregator"] is True
    assert client.post("/api/resume", files={"file": ("cv.docx", make_docx(), "application/octet-stream")}).status_code == 200
    client.post("/api/brief/chat", json={"message": "developer roles in Noida"})
    assert client.post("/api/runs", json={"stages": ["fetch", "filter"]}).status_code == 200
    run = wait_for_run(client, timeout=60)
    assert run["status"] == "done", run
    jobs = client.get("/api/jobs?view=waiting").json() + client.get("/api/jobs?view=filtered").json()
    assert [j["company"] for j in jobs] == ["Acme Soft"], jobs  # filed under the employer, not under "Adzuna"
    assert all(c["ats"] != "aggregator" for c in client.get("/api/companies").json())


def test_jobs_taken_down_from_a_board_stop_showing_and_new_ones_lead(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("JEV_PROVIDER", "typesafe")
    monkeypatch.setattr(
        llm, "_call_openrouter",
        lambda model, system, messages, schema, tool_name, max_tokens, purpose: fake_structured(
            purpose=purpose, system=system, user=messages[-1]["content"] if len(messages) == 1 else messages, schema=schema
        ),
    )
    board = {
        "old": sources.RawJob("old", "Backend Engineer", "Bengaluru, India", "Build services in Go.", "https://x/old", posted_at="2024-01-05"),
        "gone": sources.RawJob("gone", "Backend Engineer II", "Bengaluru, India", "Build services in Go.", "https://x/gone", posted_at="2026-09-01"),
        "new": sources.RawJob("new", "Backend Engineer III", "Bengaluru, India", "Build services in Go.", "https://x/new", posted_at="2026-10-05"),
    }
    monkeypatch.setattr(sources, "fetch", lambda ats, slug, hints=None: list(board.values()) if slug == "stripe" else [])
    assert client.post("/api/resume", files={"file": ("cv.docx", make_docx(), "application/octet-stream")}).status_code == 200
    client.put("/api/brief", json={"data": {"roles": [], "cities": ["Bengaluru"], "countries": ["India"], "remote_ok": True, "level": "entry", "job_type": "full_time", "keywords": [], "exclude_keywords": []}})

    def search():
        assert client.post("/api/runs", json={"stages": ["fetch", "filter"]}).status_code == 200
        assert wait_for_run(client, timeout=60)["status"] == "done"
        return client.get("/api/jobs?view=waiting").json()

    first = search()
    assert [j["title"] for j in first] == ["Backend Engineer III", "Backend Engineer II", "Backend Engineer"]  # newest first
    del board["gone"]  # the employer took it down
    second = search()
    assert "Backend Engineer II" not in [j["title"] for j in second]
    assert client.get("/api/state").json()["counts"]["found"] == 2
