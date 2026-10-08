"""Two visitors searching at the same moment must never share a key, a database or a result."""
import threading
import time
import uuid

from sqlalchemy import func, select

from app import config, db, llm, store
from app.models import Job, LlmCall, Score
from app.services import sources
from tests.test_api_flow import fake_structured
from tests.test_public import pub  # noqa: F401  (the public-mode client fixture)

OWNER_KEY = "sk-or-v1-the-owners-key-aaaaaaaaaaaa"  # in the environment, and must never be used


def _visitor(n: int) -> dict:
    return {"id": uuid.uuid4().hex, "key": f"sk-or-v1-visitor{n}-secretkey{n}{n}{n}{n}{n}{n}{n}{n}"}


def _prepare(workspace_id: str, resume_line: str) -> None:
    """A resume and a brief in that visitor's own workspace."""
    token = db.use(workspace_id)
    try:
        with db.session_scope() as s:
            store.seed_companies(s)  # what the server does for a brand-new visitor
            store.save_profile(s, "cv.pdf", resume_line, {"name": "V", "headline": resume_line, "skills": ["Go"], "experience": [], "projects": []})
            store.save_brief(s, {"roles": ["Backend Engineer"], "cities": ["Bengaluru"], "countries": ["India"], "remote_ok": True, "level": "entry",
                                 "job_type": "full_time", "keywords": [], "exclude_keywords": [], "title_keywords": [], "avoid_titles": []}, [])
    finally:
        db.release(token)


def test_two_visitors_searching_at_once_each_use_only_their_own_key_and_workspace(pub, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PUBLIC_RUN_COOLDOWN_SECONDS", "0")
    postings = [sources.RawJob(str(i), f"Backend Engineer {i}", "Bengaluru, India", f"Build services in Go. Posting {i}.", f"https://x/{i}") for i in range(6)]
    monkeypatch.setattr(sources, "fetch", lambda ats, slug, hints=None: list(postings) if slug == "stripe" else [])

    seen: list[tuple[str, str]] = []  # (workspace, key) for every AI call, taken inside the worker threads
    lock = threading.Lock()

    def fake_model_call(model, system, messages, schema, tool_name, max_tokens, purpose):
        with lock:
            seen.append((db.current(), config.openrouter_key()))
        llm._log(purpose, model, 10, 5)  # written to whichever workspace this thread believes it is in
        time.sleep(0.03)  # keep the two visitors' threads overlapping
        return fake_structured(purpose=purpose, system=system, user=messages[-1]["content"] if len(messages) == 1 else messages, schema=schema)

    monkeypatch.setattr(llm, "_call_openrouter", fake_model_call)

    a, b = _visitor(1), _visitor(2)
    _prepare(a["id"], "Visitor A resume: Go services")
    _prepare(b["id"], "Visitor B resume: Go services")
    headers = {name: {"X-Workspace": v["id"], "X-OpenRouter-Key": v["key"]} for name, v in (("a", a), ("b", b))}

    stages = {"stages": ["fetch", "filter", "rank", "score"], "score_limit": 25}
    assert pub.post("/api/runs", json=stages, headers=headers["a"]).status_code == 200
    assert pub.post("/api/runs", json=stages, headers=headers["b"]).status_code == 200  # started while A is still running

    for name in ("a", "b"):
        for _ in range(400):
            run = pub.get("/api/runs/latest", headers=headers[name]).json()
            if run["status"] != "running":
                break
            time.sleep(0.05)
        assert run["status"] == "done" and run["detail"]["scored"] == 6 and run["detail"]["failed"] == 0, (name, run)

    # every AI call carried its own visitor's key and was recorded in its own workspace, and none used the owner's key
    expected = {a["id"]: a["key"], b["id"]: b["key"]}
    assert len(seen) == 12
    for workspace, key in seen:
        assert key == expected[workspace], "a call used another visitor's key"
        assert key != OWNER_KEY
    assert {w for w, _ in seen} == set(expected)

    # and each visitor's results and usage are in their own database only
    for visitor in (a, b):
        token = db.use(visitor["id"])
        try:
            with db.session_scope() as s:
                assert s.execute(select(func.count()).select_from(Score)).scalar_one() == 6
                assert s.execute(select(func.count()).select_from(LlmCall)).scalar_one() == 6
                assert s.execute(select(func.count()).select_from(Job)).scalar_one() == 6
        finally:
            db.release(token)
