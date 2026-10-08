import uuid

import pytest

from app import db


@pytest.fixture()
def pub(tmp_path, monkeypatch):
    """A client for the public site: PUBLIC_MODE on, and the owner's keys present in the environment (they must be ignored)."""
    monkeypatch.setenv("DOORKNOCK_DATA", str(tmp_path))
    monkeypatch.setenv("PUBLIC_MODE", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-the-owners-key-aaaaaaaaaaaa")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "owner-anthropic")
    monkeypatch.setenv("HUNTER_API_KEY", "owner-hunter")
    monkeypatch.setenv("PEOPLE_PROVIDER", "hunter")
    monkeypatch.setenv("PUBLIC_RUN_COOLDOWN_SECONDS", "300")
    db.reset_engine()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
    db.reset_engine()


def ws() -> dict:
    return {"X-Workspace": uuid.uuid4().hex}


def test_a_request_without_a_workspace_id_is_refused(pub):
    assert pub.get("/api/state").status_code == 400
    assert pub.get("/api/state", headers={"X-Workspace": "not-an-id"}).status_code == 400


def test_each_visitor_has_a_private_workspace(pub):
    a, b = ws(), ws()
    assert pub.post("/api/demo", headers=a).status_code == 200
    assert pub.get("/api/state", headers=a).json()["profile"] is not None
    other = pub.get("/api/state", headers=b).json()
    assert other["profile"] is None and other["counts"]["scored"] == 0  # B sees nothing of A's data
    assert db.workspace_count() == 2


def test_the_owners_keys_are_never_used_and_the_visitors_key_is(pub):
    h = ws()
    setup = pub.get("/api/state", headers=h).json()["setup"]
    assert setup["public"] is True and setup["llm"] is False  # the owner's key in the environment does not count
    assert setup["people_provider"] == "none" and setup["gmail_connected"] is False
    mine = {**h, "X-OpenRouter-Key": "sk-or-v1-visitorkey1234567890"}
    assert pub.get("/api/state", headers=mine).json()["setup"]["llm"] is True
    junk = {**h, "X-OpenRouter-Key": "not a key; drop table"}
    assert pub.get("/api/state", headers=junk).json()["setup"]["llm"] is False  # malformed keys are ignored


def test_owner_only_features_are_switched_off(pub, monkeypatch):
    h = ws()
    assert pub.post("/api/gmail/connect", headers=h).status_code == 403
    assert pub.post("/api/drafts/1/gmail", headers=h).status_code == 403
    monkeypatch.setenv("JOOBLE_API_KEY", "owner-jooble")
    keys = [a["key"] for a in pub.get("/api/state", headers=h).json()["allowances"]]
    assert keys == ["scoring"]  # only the visitor's own free-model count; the owner's Hunter and Jooble allowances stay hidden


def test_sample_data_fills_every_step(pub):
    h = ws()
    assert pub.post("/api/demo", headers=h).status_code == 200
    state = pub.get("/api/state", headers=h).json()
    assert state["demo"] is True and state["counts"]["scored"] >= 6 and state["counts"]["waiting"] >= 2
    assert state["counts"]["filtered"] >= 3 and state["counts"]["drafts"] == 1
    scored = pub.get("/api/jobs?view=scored", headers=h).json()
    assert scored[0]["signals"] and sum(v["score"] for v in scored[0]["signals"].values()) == scored[0]["score"]
    drafted = next(j for j in scored if j["has_draft"])
    detail = pub.get(f"/api/jobs/{drafted['id']}", headers=h).json()
    assert len(detail["people"]) == 2 and all(p["email"].endswith(".invalid") for p in detail["people"])  # undeliverable on purpose
    draft = detail["draft"]
    profile_text = "\n".join(state["profile"]["data"]["experience"][0]["bullets"] + [p["description"] for p in state["profile"]["data"]["projects"]])
    for ev in draft["evidence"]:  # every quote really is in the resume or the posting
        source = profile_text if ev["source"] == "resume" else detail["description"]
        assert ev["quote"] in source, ev


def test_sample_data_can_be_cleared_and_a_workspace_deleted(pub):
    h = ws()
    pub.post("/api/demo", headers=h)
    assert pub.delete("/api/demo", headers=h).status_code == 200
    state = pub.get("/api/state", headers=h).json()
    assert state["demo"] is False and state["profile"] is None and state["counts"]["scored"] == 0
    pub.post("/api/demo", headers=h)
    assert pub.delete("/api/workspace", headers=h).status_code == 200
    assert not db.exists(h["X-Workspace"])
    assert pub.get("/api/state", headers=h).json()["profile"] is None  # a fresh, empty workspace is made on the next visit


def test_searches_cannot_be_started_back_to_back(pub, monkeypatch):
    from app.services import sources

    monkeypatch.setattr(sources, "fetch", lambda *a, **k: [])
    from app import store

    h = ws()  # an ordinary workspace (a resume on file, but not sample data): sample data is exempt from the wait
    token = db.use(h["X-Workspace"])
    try:
        with db.session_scope() as s:
            store.save_profile(s, "cv.pdf", "Jane Doe - built services in Go for two years", {"name": "Jane Doe"})
    finally:
        db.release(token)
    first = pub.post("/api/runs", json={"stages": ["fetch"]}, headers=h)
    assert first.status_code == 200
    import time

    for _ in range(200):  # let it finish, so no search thread outlives the test
        run = pub.get("/api/runs/latest", headers=h).json()
        if run["status"] != "running":
            break
        time.sleep(0.05)
    assert run["status"] == "done", run
    second = pub.post("/api/runs", json={"stages": ["fetch"]}, headers=h)
    assert second.status_code >= 400 and "wait" in second.text.lower()


def test_old_workspaces_are_removed(pub):
    import os
    import time

    h = ws()
    pub.post("/api/demo", headers=h)
    path = db.path_for(h["X-Workspace"])
    old = time.time() - 9 * 86400
    for p in path.parent.glob(path.name + "*"):
        os.utime(p, (old, old))
    assert db.prune_workspaces(7) == 1 and not path.exists()


def test_the_key_check_asks_openrouter(pub, monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, json={"data": {"is_free_tier": True}}, request=httpx.Request("GET", url)))
    h = {**ws(), "X-OpenRouter-Key": "sk-or-v1-visitorkey1234567890"}
    assert pub.post("/api/key/check", headers=h).json() == {"ok": True, "free_tier": True}
    assert pub.post("/api/key/check", headers=ws()).status_code == 400  # no key sent


HUNTER_A = "a" * 40
HUNTER_B = "b" * 40
JOOBLE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ADZUNA = "12345678:" + "5" * 32


def _hunter_account(monkeypatch, used_by_key):
    import httpx

    def fake_get(url, params=None, **kw):
        used = used_by_key.get((params or {}).get("api_key"))
        if used is None:
            return httpx.Response(401, json={}, request=httpx.Request("GET", url))
        return httpx.Response(200, json={"data": {"requests": {"searches": {"used": used, "available": 50}}}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)


def test_a_visitors_hunter_key_turns_contact_search_on_for_them_only(pub, monkeypatch):
    _hunter_account(monkeypatch, {HUNTER_A: 14})
    a, b = {**ws(), "X-Hunter-Key": HUNTER_A}, ws()
    sa, sb = pub.get("/api/state", headers=a).json(), pub.get("/api/state", headers=b).json()
    assert sa["setup"]["people_provider"] == "hunter" and sa["setup"]["keys"]["hunter"] is True
    assert sb["setup"]["people_provider"] == "none" and sb["setup"]["keys"]["hunter"] is False  # the owner's key in the environment is ignored
    tokens = {x["key"]: x for x in sa["allowances"]}["hunter"]
    assert (tokens["left"], tokens["limit"]) == (36, 50)


def test_one_visitors_hunter_allowance_never_shows_for_another(pub, monkeypatch):
    _hunter_account(monkeypatch, {HUNTER_A: 14, HUNTER_B: 40})
    left = lambda key: {x["key"]: x for x in pub.get("/api/state", headers={**ws(), "X-Hunter-Key": key}).json()["allowances"]}["hunter"]["left"]  # noqa: E731
    assert left(HUNTER_A) == 36 and left(HUNTER_B) == 10 and left(HUNTER_A) == 36  # separate caches, no mixing


def test_malformed_keys_are_ignored_and_every_key_kind_is_read(pub):
    h = ws()
    bad = {**h, "X-Hunter-Key": "short", "X-Jooble-Key": "nope", "X-Adzuna-Key": "x:y"}
    assert pub.get("/api/state", headers=bad).json()["setup"]["keys"] == {"openrouter": False, "hunter": False, "jooble": False, "adzuna": False}
    good = {**h, "X-Hunter-Key": HUNTER_A, "X-Jooble-Key": JOOBLE, "X-Adzuna-Key": ADZUNA, "X-OpenRouter-Key": "sk-or-v1-visitorkey1234567890"}
    state = pub.get("/api/state", headers=good).json()["setup"]
    assert state["keys"] == {"openrouter": True, "hunter": True, "jooble": True, "adzuna": True} and state["aggregator"] is True


def test_a_visitors_jooble_budget_is_counted_per_key(pub):
    from app import usage

    h = {**ws(), "X-Jooble-Key": JOOBLE}
    first = {x["key"]: x for x in pub.get("/api/state", headers=h).json()["allowances"]}["jooble"]
    assert first["left"] == 480
    usage.spend(f"jooble-{__import__('app.config', fromlist=['x']).key_id(JOOBLE)}", 5)
    after = {x["key"]: x for x in pub.get("/api/state", headers=h).json()["allowances"]}["jooble"]
    assert after["left"] == 475
    other = {**ws(), "X-Jooble-Key": "11111111-2222-3333-4444-555555555555"}
    assert {x["key"]: x for x in pub.get("/api/state", headers=other).json()["allowances"]}["jooble"]["left"] == 480  # not shared


def test_the_hunter_key_check_reports_what_is_left(pub, monkeypatch):
    _hunter_account(monkeypatch, {HUNTER_A: 14})
    ok = pub.post("/api/key/check?service=hunter", headers={**ws(), "X-Hunter-Key": HUNTER_A})
    assert ok.json() == {"ok": True, "detail": "36 contact searches left this month"}
    assert pub.post("/api/key/check?service=hunter", headers=ws()).status_code == 400  # none sent
    _hunter_account(monkeypatch, {})
    assert pub.post("/api/key/check?service=hunter", headers={**ws(), "X-Hunter-Key": HUNTER_B}).status_code == 401


def test_a_search_on_sample_data_is_quick_offline_and_scores_the_waiting_jobs(pub, monkeypatch):
    import time

    from app.services import sources

    def no_network(*a, **k):
        raise AssertionError("a sample search must not read any job board")

    monkeypatch.setattr(sources, "fetch", no_network)
    h = ws()
    pub.post("/api/demo", headers=h)
    before = pub.get("/api/state", headers=h).json()["counts"]
    assert before["waiting"] == 3 and before["scored"] == 7
    started = time.time()
    assert pub.post("/api/runs", json={"stages": ["fetch", "filter", "hydrate", "rank", "relevance", "score"], "score_limit": 25}, headers=h).status_code == 200
    run = None
    for _ in range(200):
        run = pub.get("/api/runs/latest", headers=h).json()
        if run["status"] != "running":
            break
        time.sleep(0.05)
    assert run["status"] == "done" and time.time() - started < 6, run
    assert run["detail"]["scored"] == 3 and run["detail"]["failed"] == 0
    after = pub.get("/api/state", headers=h).json()
    assert after["counts"]["scored"] == 10 and after["counts"]["waiting"] == 0
    assert after["freshness"]["last_refreshed"] is not None  # the page says the boards were just read
    again = pub.post("/api/runs", json={"stages": ["fetch", "filter"]}, headers=h)
    assert again.status_code == 200  # no five-minute wait on sample data
    for _ in range(200):  # let it finish, so no search thread outlives the test
        if pub.get("/api/runs/latest", headers=h).json()["status"] != "running":
            break
        time.sleep(0.05)
