from app.services import sources


def test_greenhouse_normalises_and_strips_html():
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Backend Engineer",
                "location": {"name": "Remote - India"},
                "absolute_url": "https://boards.greenhouse.io/x/jobs/123",
                "updated_at": "2026-09-30T10:00:00-04:00",
                "content": "&lt;p&gt;Build &lt;b&gt;APIs&lt;/b&gt;&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Go&lt;/li&gt;&lt;/ul&gt;",
            }
        ]
    }
    (job,) = sources.parse_greenhouse(payload)
    assert job.external_id == "123" and job.remote and job.posted_at == "2026-09-30"
    assert "Build" in job.description and "<" not in job.description and "- Go" in job.description


def test_lever_normalises():
    payload = [
        {
            "id": "abc",
            "text": "Software Engineer",
            "categories": {"location": "Bengaluru"},
            "descriptionPlain": "Write code.",
            "hostedUrl": "https://jobs.lever.co/x/abc",
            "createdAt": 1767225600000,
            "workplaceType": "hybrid",
        }
    ]
    (job,) = sources.parse_lever(payload)
    assert job.title == "Software Engineer" and not job.remote and job.posted_at == "2026-01-01"


def test_ashby_skips_unlisted():
    payload = {
        "jobs": [
            {"id": "1", "title": "A", "location": "Berlin", "isListed": False},
            {"id": "2", "title": "B", "location": "Remote", "isRemote": True, "descriptionPlain": "x", "jobUrl": "u"},
        ]
    }
    jobs = sources.parse_ashby(payload)
    assert [j.external_id for j in jobs] == ["2"] and jobs[0].remote


def test_smartrecruiters_list_has_no_text_until_hydrated():
    payload = {
        "totalFound": 1,
        "content": [
            {"id": "744", "name": "Backend Engineer", "releasedDate": "2026-10-06T16:28:54.878Z",
             "location": {"city": "Bengaluru", "region": "KA", "country": "in", "remote": True, "fullLocation": "Bengaluru, KA, India"}}
        ],
    }
    (job,) = sources.parse_smartrecruiters("BoschGroup", payload)
    assert job.needs_detail and job.description == "" and job.detail_ref == "744"
    assert job.location == "Remote - Bengaluru, KA, India" and job.remote
    assert job.url == "https://jobs.smartrecruiters.com/BoschGroup/744" and job.posted_at == "2026-10-06"


def test_workday_list_item():
    payload = {"total": 1, "jobPostings": [{"title": "Software Engineer", "externalPath": "/job/India-Pune/Software-Engineer_JR1",
                                            "locationsText": "3 Locations", "postedOn": "Posted 3 Days Ago", "bulletFields": ["JR1"]}]}
    (job,) = sources.parse_workday("nvidia/wd5/NVIDIAExternalCareerSite", payload)
    assert job.external_id == "JR1" and job.needs_detail and job.detail_ref == "/job/India-Pune/Software-Engineer_JR1"
    assert job.url == "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/India-Pune/Software-Engineer_JR1"
    assert len(job.posted_at) == 10


def test_workday_finds_the_tenants_own_country_filter():
    payload = {"facets": [{"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locationHierarchy1", "descriptor": "Locations", "values": [
            {"descriptor": "Germany", "id": "g1", "count": 3}, {"descriptor": "India", "id": "in1", "count": 9}]}]}]}
    assert sources._wd_country_facet(payload, {"india"}) == ("locationHierarchy1", "in1")
    assert sources._wd_country_facet(payload, {"japan"}) is None


def test_workable_list_item():
    payload = {"results": [{"shortcode": "C3FA", "title": "BDR", "remote": False, "published": "2026-09-29T00:00:00.000Z",
                            "location": {"city": "Barcelona", "region": "Catalonia", "country": "Spain"}}]}
    (job,) = sources.parse_workable("kantox", payload)
    assert job.location == "Barcelona, Catalonia, Spain" and job.url == "https://apply.workable.com/kantox/j/C3FA/" and job.needs_detail


def test_country_helpers():
    assert sources.country_code("India") == "in" and sources.country_code("UK") == "gb" and sources.country_code("Atlantis") is None


def test_board_url_parsing_new_systems():
    assert sources.parse_board_url("https://jobs.smartrecruiters.com/BoschGroup") == ("smartrecruiters", "BoschGroup")
    assert sources.parse_board_url("https://careers.smartrecruiters.com/Sodexo/") == ("smartrecruiters", "Sodexo")
    assert sources.parse_board_url("https://apply.workable.com/kantox/") == ("workable", "kantox")
    assert sources.parse_board_url("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite") == ("workday", "nvidia/wd5/NVIDIAExternalCareerSite")
    assert sources.parse_board_url("https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced?q=x") == ("workday", "adobe/wd5/external_experienced")


def test_board_url_parsing():
    assert sources.parse_board_url("https://boards.greenhouse.io/stripe") == ("greenhouse", "stripe")
    assert sources.parse_board_url("https://job-boards.greenhouse.io/airbnb/jobs/1") == ("greenhouse", "airbnb")
    assert sources.parse_board_url("https://jobs.lever.co/spotify") == ("lever", "spotify")
    assert sources.parse_board_url("https://jobs.ashbyhq.com/ramp") == ("ashby", "ramp")
    assert sources.parse_board_url("https://example.com/careers") is None


def test_adzuna_results_become_jobs_filed_under_their_employer():
    payload = {
        "results": [
            {"id": "42", "title": "Junior <b>Developer</b>", "company": {"display_name": "Acme Soft"}, "location": {"display_name": "Noida, Uttar Pradesh"},
             "description": "Build web apps in React.", "redirect_url": "https://www.adzuna.in/land/ad/42", "created": "2026-10-01T08:00:00Z"},
            {"id": "43", "title": "No employer listed", "company": {}, "location": {"display_name": "Delhi"}},
        ]
    }
    jobs = sources.parse_adzuna(payload)
    assert len(jobs) == 1
    assert jobs[0].employer == "Acme Soft" and jobs[0].title == "Junior Developer" and jobs[0].posted_at == "2026-10-01"


def test_a_rate_limited_request_is_retried(monkeypatch):
    import httpx

    calls = []

    def fake_get(url, **kw):
        calls.append(1)
        return httpx.Response(429 if len(calls) == 1 else 200, json={"ok": True}, headers={"retry-after": "0"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    assert sources._get_json("https://example.test/jobs") == {"ok": True}
    assert len(calls) == 2


def test_jooble_results_become_jobs_and_old_or_incomplete_ones_are_dropped():
    from datetime import date, timedelta

    fresh = (date.today() - timedelta(days=3)).isoformat()
    payload = {
        "jobs": [
            {"id": "9", "title": "Software Engineer", "company": "Acme Soft", "location": "India", "snippet": "Build &nbsp;apps", "link": "https://jooble.org/jdp/9", "updated": fresh + "T00:00:00.0000000"},
            {"id": "10", "title": "Old role", "company": "Acme Soft", "location": "India", "snippet": "x", "link": "https://jooble.org/jdp/10", "updated": "2025-01-01T00:00:00"},
            {"id": "11", "title": "No company", "company": "", "location": "India", "snippet": "x", "link": "https://jooble.org/jdp/11", "updated": fresh},
        ]
    }
    jobs = sources.parse_jooble(payload)
    assert [(j.external_id, j.employer, j.posted_at) for j in jobs] == [("jooble-9", "Acme Soft", fresh)]


def test_the_request_budget_stops_calls_and_survives_a_restart(tmp_path, monkeypatch):
    from app import usage

    monkeypatch.setenv("DOORKNOCK_DATA", str(tmp_path))
    assert usage.allow("jooble", daily=2, total=10)
    usage.spend("jooble")
    usage.spend("jooble")
    assert not usage.allow("jooble", daily=2, total=10)  # today's allowance is used
    assert usage.used("jooble") == (2, 2)
    assert not usage.allow("jooble", daily=50, total=2)  # the overall limit is reached


def test_fetch_jooble_stops_when_the_budget_runs_out(monkeypatch):
    import httpx

    calls = []

    def fake_post(url, **kw):
        calls.append(1)
        return httpx.Response(200, json={"jobs": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    left = [1]

    def allow():
        return left[0] > 0

    def spend():
        left[0] -= 1

    sources.fetch_jooble("k", ["a", "b", "c"], "India", 2, allow, spend)
    assert len(calls) == 1  # one allowed request, then it stops


def test_a_board_that_says_come_back_tomorrow_is_paused_not_retried(monkeypatch):
    import httpx
    import pytest

    calls = []

    def fake_get(url, **kw):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "75082"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(sources.Paused):
        sources._get_json("https://example.test/jobs")
    assert len(calls) == 1  # no waiting and no retrying
