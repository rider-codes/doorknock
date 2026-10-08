"""Whole flow through the HTTP API with the model and the job boards faked."""
import io
import time

import docx

from app import llm
from app.services import gmail, sources

RESUME_LINES = [
    "Jane Doe",
    "Software Engineer with one year of experience building backend services.",
    "Built a double-entry ledger reconciling 40,000 transactions a day at Acme.",
    "Wrote Go services backed by PostgreSQL and Kafka for a payments team.",
    "Skills: Go, PostgreSQL, Kafka, Docker, Python",
]


def make_docx() -> bytes:
    d = docx.Document()
    for line in RESUME_LINES:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def fake_structured(*, purpose, system, user, schema, tool_name="respond", max_tokens=4096, accept=None):
    if purpose == "resume_parse":
        return {
            "name": "Jane Doe",
            "headline": "Backend engineer",
            "seniority": "entry",
            "years_experience": 1,
            "skills": ["Go", "PostgreSQL", "Kafka"],
            "experience": [{"company": "Acme", "title": "Engineer", "bullets": [RESUME_LINES[2]]}],
        }
    if purpose == "brief_chat":
        return {
            "reply": "Done. Early career, Bengaluru or remote in India.",
            "brief": {
                "roles": ["Backend Engineer"],
                "cities": ["Bengaluru"],
                "countries": ["India"],
                "remote_ok": True,
                "level": "entry",
                "job_type": "full_time",
                "keywords": ["Go"],
                "exclude_keywords": [],
            },
        }
    if purpose == "score":
        return {
            "role": {"score": 23, "reason": "Backend-only posting"},
            "profile": {"score": 27, "reason": "Payments ledger at scale"},
            "skills": {"score": 18, "reason": "Go, Postgres, Kafka"},
            "location": {"score": 15, "reason": "A city you named"},
            "seniority": {"score": 9, "reason": "Asks 2 years"},
        }
    if purpose == "people_rank":
        return {"ranked": [{"index": 0, "relevance": 85, "role_type": "recruiter", "why": "Engineering recruiter"}]}
    if purpose == "draft":
        facts = [ln for ln in user.split("FACTS:")[1].splitlines()]
        ids = {}
        text = user.split("FACTS:")[1]
        import json

        for f in json.loads(text):
            ids.setdefault(f["source"], f)
        r, p = ids["resume"], ids["posting"]
        return {
            "subject": "Backend Engineer, Payments",
            "greeting": "Hi Sample,",
            "sentences": [
                {"text": r["quote"], "kind": "about_me", "fact_id": r["id"]},
                {"text": p["quote"], "kind": "about_job", "fact_id": p["id"]},
                {"text": "Worth a short chat?", "kind": "ask", "fact_id": None},
            ],
            "closing": "Thanks,",
        }
    raise AssertionError(purpose)


POSTINGS = [
    sources.RawJob("1", "Backend Engineer, Payments", "Bengaluru, India", "You will build ledger services in Go and Postgres.\nWe ship daily.\n2+ years of experience preferred.", "https://x/1"),
    sources.RawJob("2", "Senior Backend Engineer", "Bengaluru, India", "Lead the team.\n7+ years of experience.", "https://x/2"),
    sources.RawJob("3", "Platform Engineer", "Berlin, Germany", "Build platforms in Go for our Berlin office.", "https://x/3"),
]


def wait_for_run(client, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get("/api/runs/latest").json()
        if run and run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_full_flow(client, monkeypatch):
    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(sources, "fetch", lambda ats, slug, hints=None: list(POSTINGS) if slug == "stripe" else [])
    monkeypatch.setenv("PEOPLE_PROVIDER", "mock")

    # resume
    r = client.post("/api/resume", files={"file": ("cv.docx", make_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["skills"] == ["Go", "PostgreSQL", "Kafka"]

    # bad file types are rejected clearly
    bad = client.post("/api/resume", files={"file": ("cv.txt", b"hello", "text/plain")})
    assert bad.status_code == 422

    # brief chat
    r = client.post("/api/brief/chat", json={"message": "backend roles in Bengaluru, nothing senior"})
    assert r.status_code == 200 and r.json()["brief"]["data"]["cities"] == ["Bengaluru"]
    bversion = r.json()["brief"]["version"]
    again = client.post("/api/brief/chat", json={"message": "same thing"})
    assert again.json()["brief"]["version"] == bversion  # unchanged brief does not make scores stale

    # run the pipeline
    assert client.post("/api/runs", json={}).status_code == 200
    run = wait_for_run(client)
    assert run["status"] == "done", run
    assert run["detail"]["scored"] == 1

    scored = client.get("/api/jobs").json()
    assert [j["title"] for j in scored] == ["Backend Engineer, Payments"]
    assert scored[0]["score"] == 92 and scored[0]["verdict"] == "Strong fit"

    filtered = {j["title"]: j["filter_reason"] for j in client.get("/api/jobs?view=filtered").json()}
    assert "Too senior" in filtered["Senior Backend Engineer"]
    assert "outside your cities" in filtered["Platform Engineer"]

    jid = scored[0]["id"]
    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["signals"]["role"]["reason"] == "Backend-only posting"

    # people need a domain; the seeded Stripe company has one
    ppl = client.post(f"/api/jobs/{jid}/people").json()
    assert ppl and ppl[0]["email_status"] == "unknown"

    # grounded draft
    d = client.post(f"/api/jobs/{jid}/draft", json={"person_id": ppl[0]["id"]})
    assert d.status_code == 200, d.text
    draft = d.json()
    assert draft["status"] == "verified" and draft["problems"] == []
    assert len(draft["evidence"]) == 2

    # saved to Gmail drafts only; fake service records the call
    calls = []
    monkeypatch.setattr(gmail, "create_draft", lambda to, subject, body: calls.append((to, subject)) or "gmail-1")
    g = client.post(f"/api/drafts/{draft['id']}/gmail")
    assert g.status_code == 200 and g.json()["gmail_draft_id"] == "gmail-1"
    assert calls and calls[0][0] == ""  # mock contacts use undeliverable .invalid addresses, so no recipient is set

    state = client.get("/api/state").json()
    assert state["counts"]["drafts"] == 1 and state["counts"]["scored"] == 1


def test_jobs_listed_without_text_are_read_in_full_before_scoring(client, monkeypatch):
    monkeypatch.setattr(llm, "structured", fake_structured)
    listed = [
        sources.RawJob("w1", "Software Engineer", "3 Locations", "", "https://x/w1", detail_ref="/job/w1", needs_detail=True),
        sources.RawJob("w2", "Software Engineer II", "3 Locations", "", "https://x/w2", detail_ref="/job/w2", needs_detail=True),
    ]
    texts = {
        "/job/w1": {"description": "You will write Go services for payments.\n2+ years of experience preferred.", "location": "India, Bengaluru"},
        "/job/w2": {"description": "Own the platform.\n8+ years of experience required.", "location": "India, Bengaluru"},
    }
    monkeypatch.setattr(sources, "fetch", lambda ats, slug, hints=None: list(listed) if slug == "stripe" else [])
    monkeypatch.setattr(sources, "hydrate", lambda ats, slug, ref: texts[ref])

    assert client.post("/api/resume", files={"file": ("cv.docx", make_docx(), "application/octet-stream")}).status_code == 200
    client.post("/api/brief/chat", json={"message": "backend roles in Bengaluru, nothing senior"})
    assert client.post("/api/runs", json={}).status_code == 200
    run = wait_for_run(client)
    assert run["status"] == "done", run
    assert run["detail"]["hydrated"] == 2

    scored = [j["title"] for j in client.get("/api/jobs").json()]
    assert scored == ["Software Engineer"]  # "3 Locations" was not rejected up front; the 8+ years job dropped after reading it
    filtered = {j["title"]: j["filter_reason"] for j in client.get("/api/jobs?view=filtered").json()}
    assert "8+ years" in filtered["Software Engineer II"]


def test_missing_key_is_a_readable_error(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    r = client.post("/api/brief/chat", json={"message": "hi"})
    assert r.status_code == 502 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_run_requires_resume(client):
    assert client.post("/api/runs", json={}).status_code == 422


def test_add_company_by_link(client):
    r = client.post("/api/companies", json={"url": "https://jobs.lever.co/acme-co"})
    assert r.status_code == 200 and not r.json()["duplicate"]
    assert client.post("/api/companies", json={"url": "https://jobs.lever.co/acme-co"}).json()["duplicate"]
    assert client.post("/api/companies", json={"url": "https://example.com"}).status_code == 422



def test_a_run_left_running_by_a_dead_process_is_closed_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("DOORKNOCK_DATA", str(tmp_path))
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app
    from app.models import Run

    db.reset_engine()
    with TestClient(app):
        with db.session_scope() as s:
            s.add(Run(status="running", stage="fetch", detail={}))
    with TestClient(app) as c:  # a fresh start
        latest = c.get("/api/runs/latest").json()
        assert latest["status"] == "error" and "restarted" in latest["detail"]["error"]
    db.reset_engine()


def test_state_lists_what_is_limited_and_how_much_is_left(client, monkeypatch):
    from app.services import people

    monkeypatch.setenv("PEOPLE_PROVIDER", "hunter")
    monkeypatch.setenv("HUNTER_API_KEY", "k")
    monkeypatch.setenv("JOOBLE_API_KEY", "j")
    monkeypatch.setenv("MODEL_SCORE", "google/gemma-4-31b-it:free")
    monkeypatch.setattr(people, "hunter_quota", lambda: {"used": 14, "available": 50})
    allow = {a["key"]: a for a in client.get("/api/state").json()["allowances"]}
    assert allow["hunter"]["left"] == 36 and allow["hunter"]["limit"] == 50
    assert allow["jooble"]["left"] == 480 and allow["scoring"]["left"] == 50
    monkeypatch.setenv("MODEL_SCORE", "openai/gpt-5-nano")
    assert "scoring" not in {a["key"] for a in client.get("/api/state").json()["allowances"]}  # a paid model has no free-call cap to show
