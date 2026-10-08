"""Which model does which job, how OpenRouter answers are read, and what happens when a model fails."""
import httpx
import pytest

from app import config, llm
from app.schemas import BriefData, ProfileData
from app.services import people


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DOORKNOCK_DATA", str(tmp_path))
    from app import db

    db.reset_engine()
    db.init_db()
    for name in ("MODEL_DEFAULT", "MODEL_PARSE", "MODEL_BRIEF", "MODEL_SCORE", "MODEL_DRAFT", "MODEL_PEOPLE"):
        monkeypatch.delenv(name, raising=False)
    yield
    db.reset_engine()


def keys(monkeypatch, openrouter="", anthropic=""):
    monkeypatch.setenv("OPENROUTER_API_KEY", openrouter)
    monkeypatch.setenv("ANTHROPIC_API_KEY", anthropic)


def test_defaults_with_openrouter_use_a_different_model_per_job(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    parse, draft, people_, score = (config.model_chain(p) for p in ("resume_parse", "draft", "people_rank", "score"))
    assert parse[0].endswith(":free")  # free first for the resume
    assert draft[0] != parse[0] and people_[0] != draft[0]
    assert people_[0].startswith("anthropic/")  # the strong one for choosing people
    assert score[0].startswith("google/gemini")
    assert all(len(c) >= 2 for c in (parse, draft, people_, score))  # every job has a fallback


def test_anthropic_only_uses_the_one_model(monkeypatch):
    keys(monkeypatch, anthropic="a-key")
    assert config.model_chain("draft") == [config.anthropic_model()]
    assert not config.uses_openrouter(config.anthropic_model())


def test_env_override_beats_defaults_and_supports_a_chain(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    monkeypatch.setenv("MODEL_DRAFT", "meta-llama/llama-3.1-8b-instruct, openai/gpt-oss-20b")
    assert config.model_chain("draft") == ["meta-llama/llama-3.1-8b-instruct", "openai/gpt-oss-20b"]
    monkeypatch.setenv("MODEL_DEFAULT", "claude-sonnet-5-5")
    assert config.model_chain("score") == ["claude-sonnet-5-5"]  # MODEL_DEFAULT applies to jobs without their own setting


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data or {}

    def json(self):
        return self._data


def tool_reply(args, usage=None):
    return {"choices": [{"message": {"tool_calls": [{"function": {"name": "respond", "arguments": args}}]}}], "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}


def test_openrouter_tool_call_is_parsed_and_token_use_logged(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["model"], seen["auth"], seen["tool_choice"] = json["model"], headers["Authorization"], json["tool_choice"]
        return FakeResp(200, tool_reply('{"name": "Jane", "seniority": "entry"}'))

    monkeypatch.setattr(httpx, "post", fake_post)
    out = llm.structured_model(ProfileData, purpose="resume_parse", system="s", user="resume text")
    assert out.name == "Jane"
    assert seen["model"] == config.model_chain("resume_parse")[0]
    assert seen["auth"] == "Bearer or-key" and seen["tool_choice"]["function"]["name"] == "respond"
    assert llm._tokens_used_today() == 15


def test_plain_json_in_text_is_accepted_when_a_model_ignores_tools(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    text = 'Sure! Here you go:\n```json\n{"roles": ["Backend Engineer"], "level": "entry"}\n```'
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(200, {"choices": [{"message": {"content": text}}], "usage": {}}))
    assert llm.structured_model(BriefData, purpose="brief_chat", system="s", user="u").roles == ["Backend Engineer"]


def test_rate_limited_first_model_falls_through_to_the_next(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json["model"])
        if json["model"].endswith(":free"):
            return FakeResp(429, {})
        return FakeResp(200, tool_reply({"name": "From fallback"}))

    monkeypatch.setattr(httpx, "post", fake_post)
    assert llm.structured_model(ProfileData, purpose="resume_parse", system="s", user="u").name == "From fallback"
    assert calls[0].endswith(":free") and calls[-1] == "openai/gpt-oss-120b"


def test_wrong_shape_from_a_cheap_model_moves_on_to_the_next(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    answers = iter([tool_reply('{"years_experience": "not a number"}'), tool_reply({"name": "Right shape"})])
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(200, next(answers)))
    assert llm.structured_model(ProfileData, purpose="resume_parse", system="s", user="u").name == "Right shape"


def test_out_of_credit_and_bad_key_are_clear_errors(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(402, {}))
    with pytest.raises(llm.LLMError, match="credit"):
        llm.structured_model(ProfileData, purpose="draft", system="s", user="u")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(401, {}))
    with pytest.raises(llm.LLMError, match="OPENROUTER_API_KEY"):
        llm.structured_model(ProfileData, purpose="draft", system="s", user="u")


def test_no_key_at_all_names_both_options(monkeypatch):
    keys(monkeypatch)
    with pytest.raises(llm.LLMError) as e:
        llm.structured_model(ProfileData, purpose="draft", system="s", user="u")
    assert "OPENROUTER_API_KEY" in str(e.value) and "ANTHROPIC_API_KEY" in str(e.value)


def test_openrouter_model_without_that_key_is_skipped_not_crashed(monkeypatch):
    keys(monkeypatch, anthropic="a-key")
    monkeypatch.setenv("MODEL_DRAFT", "deepseek/deepseek-v3.2")
    with pytest.raises(llm.LLMError, match="OPENROUTER_API_KEY is not set"):
        llm.structured_model(ProfileData, purpose="draft", system="s", user="u")


# ---- choosing people with the strong model ---------------------------------------
RAW = [
    people.RawPerson("Sales Sam", "VP Sales", "sam@x.com", "verified", "Hunter"),
    people.RawPerson("Rita Recruiter", "Technical Recruiter, Engineering", "rita@x.com", "verified", "Hunter"),
    people.RawPerson("Mo Manager", "Engineering Manager, Payments", "mo@x.com", "unknown", "Hunter"),
    people.RawPerson("Lena Lawyer", "General Counsel", "lena@x.com", "verified", "Hunter"),
]
JOB = {"title": "Backend Engineer, Payments", "company": "Fenwick Pay", "location": "Bengaluru", "description": "Build ledgers."}


def fake_ranking(ranked):
    return lambda **kw: {"ranked": ranked}


def test_ai_ranking_drops_unrelated_people_and_keeps_the_order(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    monkeypatch.setattr(llm, "structured", lambda **kw: {"ranked": [
        {"index": 2, "relevance": 90, "role_type": "hiring_manager", "why": "Manages the payments team"},
        {"index": 1, "relevance": 80, "role_type": "recruiter", "why": "Engineering recruiter"},
        {"index": 0, "relevance": 5, "role_type": "skip", "why": "Sales"},
        {"index": 3, "relevance": 0, "role_type": "skip", "why": "Legal"},
        {"index": 99, "relevance": 90, "role_type": "recruiter", "why": "not a real index"},
    ]})
    rows = people.rank_with_llm(RAW, JOB)
    # Rita: 80 + 10 for a verified email = 90. Mo: 90, unverified. A tie goes to the verified email.
    assert [r["name"] for r in rows] == ["Rita Recruiter", "Mo Manager"]
    assert rows[0]["relevance"] == 90 and rows[1]["relevance"] == 90
    assert rows[1]["role_type"] == "hiring_manager" and all(r["email"] for r in rows)
    assert "Sales Sam" not in [r["name"] for r in rows] and "Lena Lawyer" not in [r["name"] for r in rows]


def test_ai_failure_falls_back_to_the_rule_based_ranking(monkeypatch):
    keys(monkeypatch, openrouter="or-key")
    monkeypatch.setenv("PEOPLE_PROVIDER", "mock")

    def boom(**kw):
        raise llm.LLMError("all models down")

    monkeypatch.setattr(llm, "structured", boom)
    rows = people.find("example", "Backend Engineer", JOB)
    assert rows and {"name", "role_type", "relevance"} <= set(rows[0])  # rules answered instead


def test_objects_returned_as_json_strings_are_decoded():
    from app import llm

    messy = {"role": '{"score": 10, "reason": "ok"}', "list": ['{"a": 1}', "plain", "{broken"], "n": 3}
    assert llm._decode_nested(messy) == {"role": {"score": 10, "reason": "ok"}, "list": [{"a": 1}, "plain", "{broken"], "n": 3}
