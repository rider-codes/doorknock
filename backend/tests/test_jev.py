"""Jev as the relevance gate: request shape, how answers are combined, and what the pipeline does with them."""
import httpx
import pytest

from app import llm
from app.services import jev, sources
from tests.test_api_flow import fake_structured, make_docx, wait_for_run


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data or {}

    def json(self):
        return self._data


def answer(role, skills, level):
    return {"model": "jev-1", "answers": {k: {"type": "noul", "noul": v} for k, v in (("role", role), ("skills", skills), ("level", level))}, "usage": {"input_tokens": 700}}


CAND = {"headline": "Backend", "skills": ["Go"]}
JOB = {"title": "Backend Engineer", "company": "Acme", "location": "Bengaluru", "description": "x" * 5000}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "JEV_PROVIDER", "JEV_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_openrouter_is_used_when_its_key_is_set(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")  # both set: OpenRouter wins
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, auth=headers["Authorization"])
        return FakeResp(200, {**answer(0.9, 0.8, 0.7), "usage": {"input_tokens": 500, "output_tokens": 60, "cost": 0.0000210}})

    monkeypatch.setattr(httpx, "post", fake_post)
    out = jev.assess(CAND, JOB)
    assert seen["url"] == "https://openrouter.ai/api/v1/systemone" and seen["auth"] == "Bearer or-key"
    assert seen["body"]["model"] == "~typesafe/jev-latest"
    assert out["cost"] == pytest.approx(0.000021) and out["tokens"] == 500


def test_a_model_can_be_pinned_and_typesafe_direct_still_works(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("JEV_MODEL", "typesafe/jev-1.13")
    seen = {}
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: seen.update(model=json["model"]) or FakeResp(200, answer(1, 1, 1)))
    jev.assess(CAND, JOB)
    assert seen["model"] == "typesafe/jev-1.13"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.delenv("JEV_MODEL")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    urls = []
    monkeypatch.setattr(httpx, "post", lambda url, json=None, headers=None, timeout=None: urls.append((url, json["model"])) or FakeResp(200, answer(1, 1, 1)))
    jev.assess(CAND, JOB)
    assert urls == [("https://api.typesafe.ai/v1/systemone", "jev-latest")]


def test_jev_is_not_configured_without_either_key():
    assert jev.configured() is False


def test_request_matches_the_documented_api(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, body=json, auth=headers["Authorization"])
        return FakeResp(200, answer(0.9, 0.8, 0.7))

    monkeypatch.setattr(httpx, "post", fake_post)
    out = jev.assess(CAND, JOB)
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone" and seen["auth"] == "Bearer ts-key"
    assert seen["body"]["model"] == "jev-latest" and set(seen["body"]["questions"]) == {"role", "skills", "level"}
    assert all(q["type"] == "noul" and set(q["criteria"]) == {"true", "false"} for q in seen["body"]["questions"].values())
    assert len(seen["body"]["state"]["job"]["description"]) == 3000  # long postings are trimmed
    # role counts most: 0.5*0.9 + 0.3*0.8 + 0.2*0.7
    assert out["relevance"] == pytest.approx(0.83) and out["parts"] == {"role": 0.9, "skills": 0.8, "level": 0.7}


def test_weights_sum_to_one_and_role_matters_most():
    assert sum(jev.WEIGHTS.values()) == pytest.approx(1.0)
    assert jev.combine({"role": 1, "skills": 0, "level": 0}) > jev.combine({"role": 0, "skills": 1, "level": 0}) > jev.combine({"role": 0, "skills": 0, "level": 1})


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-key")
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    replies = iter([FakeResp(429), FakeResp(529), FakeResp(200, answer(1, 1, 1))])
    monkeypatch.setattr(httpx, "post", lambda *a, **k: next(replies))
    assert jev.assess(CAND, JOB)["relevance"] == pytest.approx(1.0)


def test_bad_key_and_no_credit_are_distinct_errors_and_odd_answers_are_errors(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(401))
    with pytest.raises(jev.JevAuthError, match="OPENROUTER_API_KEY"):
        jev.assess(CAND, JOB)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(402))
    with pytest.raises(jev.JevCreditError, match="credit"):
        jev.assess(CAND, JOB)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(200, {"answers": {}}))
    with pytest.raises(jev.JevError):
        jev.assess(CAND, JOB)


# ---- in the pipeline ------------------------------------------------------------
POSTINGS = [
    sources.RawJob("1", "Backend Engineer, Payments", "Bengaluru, India", "You will build ledger services in Go.", "https://x/1"),
    sources.RawJob("2", "Backend Developer", "Bengaluru, India", "REST APIs in Python.", "https://x/2"),
    sources.RawJob("3", "Marketing Associate", "Bengaluru, India", "Run campaigns and write copy.", "https://x/3"),
]
BY_TITLE = {"Backend Engineer, Payments": (0.95, 0.9, 0.8), "Backend Developer": (0.7, 0.6, 0.9), "Marketing Associate": (0.05, 0.1, 0.9)}


def setup_run(client, monkeypatch, jev_calls):
    monkeypatch.setattr(llm, "structured", fake_structured)
    monkeypatch.setattr(sources, "fetch", lambda ats, slug, hints=None: list(POSTINGS) if slug == "stripe" else [])

    def fake_post(url, json=None, headers=None, timeout=None):
        title = json["state"]["job"]["title"]
        jev_calls.append(title)
        return FakeResp(200, answer(*BY_TITLE[title]))

    monkeypatch.setattr(httpx, "post", fake_post)
    assert client.post("/api/resume", files={"file": ("cv.docx", make_docx(), "application/octet-stream")}).status_code == 200
    client.post("/api/brief/chat", json={"message": "backend roles in Bengaluru"})


def test_irrelevant_jobs_are_set_aside_before_scoring(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    calls = []
    setup_run(client, monkeypatch, calls)
    assert client.post("/api/runs", json={}).status_code == 200
    run = wait_for_run(client)
    assert run["status"] == "done", run
    assert run["detail"]["assessed"] == 3 and run["detail"]["set_aside"] == 1

    scored = {j["title"] for j in client.get("/api/jobs").json()}
    assert scored == {"Backend Engineer, Payments", "Backend Developer"}  # the marketing job never reached the scoring model
    filtered = {j["title"]: j["filter_reason"] for j in client.get("/api/jobs?view=filtered").json()}
    assert "Not a close match" in filtered["Marketing Associate"] and "role 5%" in filtered["Marketing Associate"]
    assert client.get("/api/state").json()["counts"]["filtered"] == 1
    assert client.get("/api/state").json()["setup"]["jev"] is True


def test_answers_are_cached_per_profile_and_brief(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    calls = []
    setup_run(client, monkeypatch, calls)
    client.post("/api/runs", json={})
    wait_for_run(client)
    first = len(calls)
    assert first == 3
    client.post("/api/runs", json={"stages": ["filter", "rank", "relevance"]})
    wait_for_run(client)
    assert len(calls) == first  # same profile and brief: Jev is not asked again
    client.post("/api/brief/chat", json={"message": "now also data roles"})  # same fake brief => same version, so still cached
    # a real brief change makes a new version and Jev is asked again
    client.put("/api/brief", json={"data": {"roles": ["Data Engineer"], "cities": ["Bengaluru"], "countries": ["India"], "level": "entry"}})
    client.post("/api/runs", json={"stages": ["filter", "rank", "relevance"]})
    wait_for_run(client)
    assert len(calls) > first


def test_without_a_key_the_stage_is_skipped_and_everything_goes_to_scoring(client, monkeypatch):
    calls = []
    setup_run(client, monkeypatch, calls)
    client.post("/api/runs", json={})
    run = wait_for_run(client)
    assert run["status"] == "done" and calls == []
    assert "OPENROUTER_API_KEY" in run["detail"]["relevance_skipped"]
    assert len(client.get("/api/jobs").json()) == 3  # all three scored, including the marketing job


def test_a_rejected_key_fails_the_run_with_a_clear_message(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "bad")
    calls = []
    setup_run(client, monkeypatch, calls)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(401))
    client.post("/api/runs", json={})
    run = wait_for_run(client)
    assert run["status"] == "error" and "OPENROUTER_API_KEY" in run["detail"]["error"]



def test_no_credit_for_jev_skips_the_step_and_the_search_still_scores(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    calls = []
    setup_run(client, monkeypatch, calls)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(402))
    client.post("/api/runs", json={})
    run = wait_for_run(client)
    assert run["status"] == "done", run
    assert "Out of credit" in run["detail"]["relevance_skipped"]
    assert len(client.get("/api/jobs").json()) == 3  # scoring still ran on every job
