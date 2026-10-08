from app.schemas import BriefData
from app.services import brief_agent, filters


def _brief(**kw) -> BriefData:
    return BriefData(**kw)


def test_countries_and_regions_are_moved_out_of_the_city_list():
    b = brief_agent.tidy(_brief(cities=["India", "bangalore", "Remote", "Bengaluru", "Bombay"]), "backend jobs", None)
    assert b.cities == ["Bengaluru", "Mumbai"]
    assert b.countries == ["India"]


def test_a_country_is_added_when_every_city_is_indian():
    b = brief_agent.tidy(_brief(cities=["Pune"]), "jobs in pune", None)
    assert b.countries == ["India"]


def test_plain_cues_override_a_misread():
    b = brief_agent.tidy(_brief(level="mid", remote_ok=True), "I'm a fresher, and I don't want remote", None)
    assert b.level == "entry" and b.remote_ok is False


def test_a_wanted_title_word_is_never_also_avoided():
    b = brief_agent.tidy(_brief(roles=["Support Engineer"], title_keywords=["support engineer"], avoid_titles=["support", "sales"]), "support roles", None)
    assert b.avoid_titles == ["sales"]


def test_empty_roles_fall_back_to_the_resume():
    profile = {"headline": "Full stack developer", "experience": [{"title": "Software Engineering Intern"}]}
    b = brief_agent.tidy(_brief(cities=["Noida"]), "just look at my resume", profile)
    assert b.roles == ["Software Engineering Intern"]


def test_role_filter_matches_synonyms_and_rejects_other_jobs():
    ok = lambda title: filters.role_ok(title, ["Backend Engineer"], ["backend", "software engineer", "sde"], ["sales", "recruiter"]).ok  # noqa: E731
    assert ok("Backend Developer II")
    assert ok("Software Engineer, Payments")
    assert ok("SDE 1")
    assert ok("Engineer, Backend")  # words in another order
    assert not ok("Sales Engineer")  # avoided word
    assert not ok("Technical Recruiter")
    assert not ok("Marketing Manager")  # nothing matches


def test_no_role_information_means_no_title_filter():
    assert filters.role_ok("Marketing Manager", [], [], []).ok


def test_the_search_queries_lead_with_roles_then_synonyms():
    from app import pipeline

    q = pipeline.search_queries({"roles": ["Backend Engineer"], "title_keywords": ["backend", "sde", "api"], "keywords": ["Go"]})
    assert q[:2] == ["Backend Engineer", "backend"] and "Go" in q


def test_chat_cleans_up_what_the_model_returned(client, monkeypatch):
    from app import llm
    from tests.test_api_flow import fake_structured, make_docx

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setattr(
        llm, "_call_openrouter",
        lambda model, system, messages, schema, tool_name, max_tokens, purpose: fake_structured(
            purpose=purpose, system=system, user=messages[-1]["content"] if len(messages) == 1 else messages, schema=schema
        ),
    )

    assert client.post("/api/resume", files={"file": ("cv.docx", make_docx(), "application/octet-stream")}).status_code == 200
    body = client.post("/api/brief/chat", json={"message": "backend jobs in bangalore, no remote"}).json()
    brief = body["brief"]["data"]
    assert brief["remote_ok"] is False  # the cue in the message wins
    assert "title_keywords" in brief and "avoid_titles" in brief
