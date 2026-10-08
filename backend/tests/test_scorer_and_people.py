from app.schemas import SIGNAL_MAX, ScoreResult, Signal
from app.services import people, scorer


def _result(**scores):
    base = {k: Signal(score=0, reason="r") for k in SIGNAL_MAX}
    for k, v in scores.items():
        base[k] = Signal(score=v, reason="because")
    return ScoreResult(**base)


def test_total_is_summed_in_code_and_clamped():
    out = scorer.clamp(_result(role=99, profile=-5, skills=10, location=15, seniority=3))
    assert out["signals"]["role"]["score"] == SIGNAL_MAX["role"]
    assert out["signals"]["profile"]["score"] == 0
    assert out["total"] == 25 + 0 + 10 + 15 + 3
    assert out["total"] == sum(s["score"] for s in out["signals"].values())


def test_weights_sum_to_100():
    assert sum(SIGNAL_MAX.values()) == 100


def test_verdict_bands():
    assert scorer.verdict(92) == "Strong fit"
    assert scorer.verdict(70) == "Good fit"
    assert scorer.verdict(40) == "Stretch"


def test_classify_titles():
    assert people.classify("Technical Recruiter, Engineering") == "recruiter"
    assert people.classify("Head of Talent") == "recruiter"
    assert people.classify("Engineering Manager, Payments") == "hiring_manager"
    assert people.classify("Software Engineer") == "teammate"


def test_ranking_prefers_relevant_and_verified():
    raw = [
        people.RawPerson("A", "Software Engineer", "a@x.com", "verified", "t"),
        people.RawPerson("B", "Technical Recruiter", "b@x.com", "unknown", "t"),
        people.RawPerson("C", "Technical Recruiter", "c@x.com", "verified", "t"),
        people.RawPerson("C again", "Technical Recruiter", "c@x.com", "verified", "t"),
    ]
    rows = people.rank(raw, "Backend Engineer")
    assert [r["name"] for r in rows][:2] == ["C", "B"]
    assert len(rows) == 3  # duplicate email removed


def test_no_provider_gives_a_clear_error(monkeypatch):
    monkeypatch.setenv("PEOPLE_PROVIDER", "none")
    try:
        people.find("x.com", "Engineer")
    except people.PeopleError as exc:
        assert "PEOPLE_PROVIDER" in str(exc)
    else:
        raise AssertionError("expected PeopleError")


def test_mock_provider_uses_undeliverable_addresses(monkeypatch):
    monkeypatch.setenv("PEOPLE_PROVIDER", "mock")
    rows = people.find("example", "Engineer")
    assert rows and all(r["email"].endswith(".invalid") for r in rows)


def test_posting_scan_finds_published_contacts():
    text = "Questions? Email jane.doe@acme.com or careers@acme.com. Recruiter: Priya Nair. Do not use help@vendor.io"
    found = people.scan_posting(text, "acme.com")
    emails = {p.email for p in found}
    assert emails == {"jane.doe@acme.com", "careers@acme.com", ""}
    assert any(p.name == "Priya Nair" and p.title == "Recruiter" for p in found)
    assert any(p.name == "Jane Doe" for p in found)


def test_manual_person_guesses_and_labels_the_email():
    row = people.add_manual("Sam Rivera", "Engineering Manager", "", "acme.com", "Backend Engineer")
    assert row["email"] == "sam.rivera@acme.com" and row["email_status"] == "unknown"
    assert row["role_type"] == "hiring_manager" and "guessed" in row["why"]
    given = people.add_manual("Sam Rivera", "", "Sam@Acme.com", "", "Backend Engineer")
    assert given["email"] == "sam@acme.com"


def test_hunter_search_is_refused_when_the_monthly_allowance_is_nearly_used(monkeypatch):
    import httpx
    import pytest

    monkeypatch.setenv("HUNTER_API_KEY", "k")
    body = {"data": {"requests": {"searches": {"used": 49, "available": 50}}}}
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, json=body, request=httpx.Request("GET", url)))
    with pytest.raises(people.PeopleError, match="nearly used"):
        people._hunter("acme.com")


def test_a_hunter_refusal_becomes_a_readable_error_and_asks_for_no_more_than_the_free_plan_allows(monkeypatch):
    import httpx
    import pytest

    monkeypatch.setenv("HUNTER_API_KEY", "k")
    seen = {}

    def fake_get(url, params=None, **kw):
        if url.endswith("/account"):
            return httpx.Response(200, json={"data": {"requests": {"searches": {"used": 1, "available": 50}}}}, request=httpx.Request("GET", url))
        seen.update(params)
        return httpx.Response(400, json={"errors": [{"details": "limit must be 10 or less"}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(people.PeopleError, match="limit must be 10 or less"):
        people._hunter("acme.com")
    assert seen["limit"] == 10
