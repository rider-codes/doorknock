import pytest

from app.services import filters

BRIEF = {
    "level": "entry",
    "job_type": "full_time",
    "cities": ["Bengaluru"],
    "countries": ["India"],
    "remote_ok": True,
    "exclude_keywords": [],
}


@pytest.mark.parametrize(
    "title,desc,level,ok",
    [
        ("Senior Backend Engineer", "", "entry", False),
        ("Staff Software Engineer", "", "mid", False),
        ("Software Engineer", "5+ years of experience in Go", "entry", False),
        ("Software Engineer", "3-5 years of experience required", "entry", False),
        ("Software Engineer", "2+ years of experience with Python", "entry", True),
        ("Software Engineer", "We value 10 years of history in fintech, no experience needed", "entry", False),
        ("Software Engineer", "Our team has 12 years of history.", "entry", True),
        ("Software Engineer II", "", "mid", True),
        ("Lead Engineer", "", "senior", True),
    ],
)
def test_level(title, desc, level, ok):
    assert filters.level_ok(title, desc, level).ok is ok


def test_level_reason_names_the_cause():
    assert "5+" in filters.level_ok("Engineer", "5+ years of experience", "entry").reason


@pytest.mark.parametrize(
    "location,remote,ok",
    [
        ("Bengaluru, India", False, True),
        ("Bangalore, Karnataka", False, True),  # same city as Bengaluru
        ("Mumbai, India", False, False),  # same country, but the user named cities
        ("Remote - US", True, False),
        ("Remote, India", True, True),
        ("Remote", True, True),
        ("", False, True),
        ("London, United Kingdom", False, False),
    ],
)
def test_location(location, remote, ok):
    v = filters.location_ok(location, remote, BRIEF["cities"], BRIEF["countries"], True)
    assert v.ok is ok, v.reason


@pytest.mark.parametrize("placeholder", ["3 Locations", "2 location", "12 Locations"])
def test_many_locations_placeholder_is_not_rejected(placeholder):
    # Workday lists multi-site jobs this way; the real places are known after the text is fetched
    assert filters.location_ok(placeholder, False, ["Bengaluru"], ["India"], True).ok


def test_location_country_only_accepts_any_city_in_country():
    assert filters.location_ok("Pune, India", False, [], ["India"], True).ok


def test_location_remote_ruled_out():
    assert not filters.location_ok("Remote", True, ["Berlin"], ["Germany"], False).ok


def test_us_token_is_case_sensitive():
    assert filters.detect_countries("Remote, US") == {"united states"}
    assert filters.detect_countries("Let us help you") == set()


@pytest.mark.parametrize(
    "title,job_type,ok",
    [
        ("Software Engineering Intern", "full_time", False),
        ("Software Engineer", "full_time", True),
        ("Contract Backend Engineer", "full_time", False),
        ("Software Engineering Intern", "intern", True),
        ("Software Engineer", "intern", False),
        ("Anything", "any", True),
    ],
)
def test_job_type(title, job_type, ok):
    assert filters.type_ok(title, job_type).ok is ok


def test_exclude_keywords():
    assert not filters.keywords_ok("Backend Engineer", "We are a consulting firm", ["consulting"]).ok
    assert filters.keywords_ok("Backend Engineer", "We build products", ["consulting"]).ok


def test_evaluate_returns_first_failure():
    v = filters.evaluate("Senior Engineer", "Berlin", False, "", BRIEF)
    assert not v.ok and "senior" in v.reason.lower()


def test_remote_flag_does_not_override_a_named_city():
    from app.services.filters import location_ok

    flagged = location_ok("San Francisco, California", True, ["Noida"], ["India"], True)
    assert not flagged.ok and "outside" in flagged.reason
    assert location_ok("Remote - India", True, ["Noida"], ["India"], True).ok
    assert location_ok("", True, ["Noida"], ["India"], True).ok  # flagged remote with no place named


def test_delhi_ncr_cities_count_as_one_area():
    from app.services.filters import location_ok

    for place in ("Gurugram, Haryana", "New Delhi", "Noida, Uttar Pradesh"):
        assert location_ok(place, False, ["Noida"], ["India"], True).ok
    assert not location_ok("Bengaluru", False, ["Noida"], ["India"], True).ok


def test_tech_hub_spellings_match_each_other():
    from app.services.filters import location_ok

    assert location_ok("Bangalore, Karnataka", False, ["Bengaluru"], ["India"], True).ok
    assert location_ok("Navi Mumbai", False, ["Mumbai"], ["India"], True).ok
    assert location_ok("Hyderabad, Telangana", False, ["Noida", "Hyderabad"], ["India"], True).ok
    assert not location_ok("Chennai", False, ["Pune"], ["India"], True).ok


def test_a_country_only_location_passes_for_the_scorer_to_judge():
    from app.services.filters import location_ok

    assert location_ok("India", False, ["Noida"], ["India"], True).ok
    assert not location_ok("United States", False, ["Noida"], ["India"], True).ok
