from app import usage
from app.services import portals

INTERNSHALA = """<div class="container-fluid individual_internship logged_out_jd_summary" id="individual_internship_42" internshipId="42" data-href='/job/detail/dev-job-in-noida-at-acme42'>
<h2 class="job-internship-name"><a class="job-title-href" id="job_title" href="/job/detail/x">Software Developer</a></h2>
<p class="company-name">
   Acme Soft   </p>
<p class="row-1-item  locations"><i></i><span><a>Noida</a></span></p>
<div>3 year(s)</div><div>Build web apps with React</div><span>3 weeks ago</span></div>"""


def test_internshala_cards_become_jobs():
    jobs = portals.parse_internshala(INTERNSHALA)
    assert len(jobs) == 1
    j = jobs[0]
    assert (j.external_id, j.title, j.employer, j.location) == ("internshala-42", "Software Developer", "Acme Soft", "Noida")
    assert j.url == "https://internshala.com/job/detail/dev-job-in-noida-at-acme42"
    assert "Experience required: 3 years of experience" in j.description and j.posted_at


def test_unstop_results_become_jobs():
    payload = {
        "data": {
            "data": [
                {
                    "id": 7,
                    "title": "Backend Developer",
                    "organisation": {"name": "Polycab"},
                    "details": "<p>Build APIs</p>",
                    "region": "offline",
                    "jobDetail": {"locations": ["Noida"], "min_experience": 1},
                    "required_skills": [{"skill": "Java"}],
                    "updated_at": "2026-10-01T10:00:00+05:30",
                    "seo_url": "https://unstop.com/jobs/x-7",
                }
            ]
        }
    }
    (j,) = portals.parse_unstop(payload)
    assert (j.external_id, j.employer, j.location, j.posted_at) == ("unstop-7", "Polycab", "Noida", "2026-10-01")
    assert "Build APIs" in j.description and "Java" in j.description


def test_instahyre_and_foundit_results_become_jobs():
    (a,) = portals.parse_instahyre(
        {
            "objects": [
                {
                    "id": 5,
                    "title": "Backend Engineer",
                    "locations": "Bangalore",
                    "keywords": ["Go", "SQL"],
                    "public_url": "https://www.instahyre.com/job-5",
                    "employer": {"company_name": "Accenture"},
                }
            ]
        }
    )
    assert (a.external_id, a.employer, a.location) == ("instahyre-5", "Accenture", "Bangalore")
    (b,) = portals.parse_foundit(
        {
            "jobSearchResponse": {
                "data": [
                    {
                        "jobId": "9",
                        "title": "Java Developer",
                        "companyName": "Orange",
                        "locations": "Gurugram, India",
                        "createdAt": "1791248447000",
                        "skills": "Java",
                        "minimumExperience": {"years": 2},
                        "seoJdUrl": "/job/java-9",
                    }
                ]
            }
        }
    )
    assert (b.external_id, b.employer, b.url) == ("foundit-9", "Orange", "https://www.foundit.in/job/java-9")
    assert "Experience required: 2 years" in b.description and b.posted_at.startswith("2026")


def test_muse_and_remotive_results_become_jobs():
    (m,) = portals.parse_muse(
        {
            "results": [
                {
                    "id": 3,
                    "name": "Junior Dev",
                    "company": {"name": "Zed"},
                    "locations": [{"name": "Flexible / Remote"}],
                    "contents": "<p>Hi</p>",
                    "refs": {"landing_page": "https://themuse.com/x"},
                    "publication_date": "2026-09-01T00:00:00Z",
                }
            ]
        }
    )
    assert m.remote and m.employer == "Zed" and m.posted_at == "2026-09-01"
    (r,) = portals.parse_remotive(
        {"jobs": [{"id": 4, "title": "Engineer", "company_name": "Yo", "url": "https://remotive.com/x", "candidate_required_location": "Worldwide"}]}
    )
    assert r.location == "Remote - Worldwide" and r.remote


def test_a_used_up_portal_is_skipped_and_one_failure_does_not_stop_the_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("DOORKNOCK_DATA", str(tmp_path))
    monkeypatch.setitem(portals.DAILY_CAP, "muse", 0)  # nothing left today

    def boom(queries):
        raise RuntimeError("down")

    monkeypatch.setattr(portals, "fetch_unstop", boom)
    sentinel = [portals.RawJob("remotive-1", "Dev", "Remote", "x", "https://x", employer="Yo")]
    monkeypatch.setattr(portals, "fetch_remotive", lambda: sentinel)
    jobs, problems = portals.fetch_all(["Noida"], ["software engineer"], {"muse", "unstop", "remotive"})
    assert jobs == sentinel
    assert len(problems) == 1 and problems[0].startswith("Unstop")
    assert usage.used("muse") == (0, 0)
