"""Job portals that publish listings to anyone who visits, read the way a visitor's browser would.

These are not employers' own boards, so each posting is filed under the employer named on it. Rules this module keeps:
- a visitor's requests only: no logins, no CAPTCHA or bot-protection workarounds (Naukri and Wellfound refuse plain
  requests, so they are not read);
- gentle: a pause between requests and a daily request cap per portal, kept across restarts (see usage.py);
- one portal failing never stops the others."""
import html
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from .. import usage
from .sources import RawJob, html_to_text

BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}
TIMEOUT = 25
DEFAULT_ON = "internshala,unstop,instahyre,foundit,muse,remotive"
PAUSE = 0.7  # seconds between two requests to the same portal
DAILY_CAP = {"internshala": 80, "unstop": 40, "instahyre": 40, "foundit": 40, "muse": 20, "remotive": 2}  # Remotive asks for at most a few reads a day


class _Budget:
    """Counts a portal's requests against its daily cap."""

    def __init__(self, name: str):
        self.name = name

    def get(self, url: str, **kw) -> httpx.Response:
        if not usage.allow(self.name, DAILY_CAP[self.name], 10**9):
            raise PermissionError(f"{self.name}: today's request allowance is used")
        usage.spend(self.name)
        time.sleep(PAUSE)
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, **{**kw, "headers": {**BROWSER, **kw.get("headers", {})}})
        resp.raise_for_status()
        return resp


def _date_from_ago(text: str) -> str:
    """'3 weeks ago' -> a YYYY-MM-DD date."""
    low = text.lower()
    now = datetime.now(timezone.utc)
    if "just now" in low or "today" in low or "hour" in low or "minute" in low:
        return now.date().isoformat()
    m = re.search(r"(\d+)\s+(day|week|month)", low)
    if not m:
        return ""
    days = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
    return (now - timedelta(days=days)).date().isoformat()


def _clean(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))).strip()


# ---- Internshala (HTML pages) ---------------------------------------------------------
_ROLE_PAGES = ("software-development", "web-development")


def parse_internshala(page: str) -> list[RawJob]:
    out = []
    for block in page.split('class="container-fluid individual_internship')[1:]:
        href = re.search(r"data-href='([^']+)'", block)
        title = re.search(r'class="job-title-href"[^>]*>\s*([^<]+)', block)
        company = re.search(r'class="company-name">\s*([^<]+)', block)
        if not (href and title and company):
            continue
        loc = re.search(r'row-1-item\s+locations">(.*?)</p>', block, re.S)
        location = _clean(loc.group(1)) if loc else ""
        text = _clean(block)
        years = re.search(r"(\d+)\s*year\(s\)", text)
        posted = _date_from_ago(" ".join(re.findall(r"\d+\s+(?:day|week|month)s?\s+ago|Just now|Today|Few hours ago", block)[:1]))
        experience = f" Experience required: {years.group(1)} years of experience." if years else ""
        iid = re.search(r"individual_internship_(\d+)", block)
        out.append(
            RawJob(
                external_id="internshala-" + (iid.group(1) if iid else href.group(1)),
                title=title.group(1).strip(),
                location=location,
                description=f"{title.group(1).strip()} at {company.group(1).strip()}. Location: {location}.{experience} {text}"[:3000],
                url="https://internshala.com" + href.group(1),
                posted_at=posted,
                employer=company.group(1).strip(),
            )
        )
    return out


def fetch_internshala(cities: list[str], pages: int = 2) -> list[RawJob]:
    web, found = _Budget("internshala"), {}
    for city in cities:
        slug = re.sub(r"[^a-z]+", "-", city.lower()).strip("-")
        for role in _ROLE_PAGES:
            for page in range(1, pages + 1):
                url = f"https://internshala.com/jobs/{role}-jobs-in-{slug}/" + (f"page-{page}/" if page > 1 else "")
                try:
                    batch = parse_internshala(web.get(url).text)
                except httpx.HTTPStatusError:
                    break  # no such city page
                for job in batch:
                    found.setdefault(job.external_id, job)
                if len(batch) < 20:
                    break
    return list(found.values())


# ---- Unstop (public JSON) --------------------------------------------------------------
def parse_unstop(payload: dict) -> list[RawJob]:
    out = []
    for j in ((payload.get("data") or {}).get("data")) or []:
        org = ((j.get("organisation") or {}).get("name") or "").strip()
        if not (j.get("id") and j.get("title") and org):
            continue
        detail = j.get("jobDetail") or {}
        places = [p if isinstance(p, str) else (p.get("city") or p.get("name") or "") for p in (detail.get("locations") or [])]
        addr = j.get("address_with_country_logo") or {}
        location = ", ".join(x for x in places if x) or ", ".join(x for x in (addr.get("city"), addr.get("state"), addr.get("country")) if x)
        remote = (j.get("region") or "").lower() == "online" and not location
        skills = ", ".join(s.get("skill", "") for s in (j.get("required_skills") or []))
        minx = detail.get("min_experience")
        exp = f" Experience required: {minx} years of experience." if minx not in (None, "", 0) else ""
        out.append(
            RawJob(
                external_id=f"unstop-{j['id']}",
                title=_clean(j["title"]),
                location=location or ("Remote" if remote else ""),
                description=f"{html_to_text(j.get('details', ''))}{exp} Skills: {skills}".strip()[:5000],
                url=j.get("seo_url") or f"https://unstop.com/{j.get('public_url', '')}",
                posted_at=str(j.get("updated_at", ""))[:10],
                remote=remote,
                employer=org,
            )
        )
    return out


def fetch_unstop(queries: list[str], pages: int = 2) -> list[RawJob]:
    web, found = _Budget("unstop"), {}
    for q in queries:
        for page in range(1, pages + 1):
            resp = web.get(
                "https://unstop.com/api/public/opportunity/search-result",
                params={"opportunity": "jobs", "per_page": 30, "oppstatus": "open", "searchTerm": q, "page": page},
                headers={"Accept": "application/json"},
            )
            data = resp.json()
            for job in parse_unstop(data):
                found.setdefault(job.external_id, job)
            if not (data.get("data") or {}).get("next_page_url"):
                break
    return list(found.values())


# ---- Instahyre (public JSON) -----------------------------------------------------------
def parse_instahyre(payload: dict) -> list[RawJob]:
    out = []
    for j in payload.get("objects") or []:
        company = ((j.get("employer") or {}).get("company_name") or "").strip()
        if not (j.get("id") and j.get("title") and company and j.get("public_url")):
            continue
        location = (j.get("locations") or "").strip()
        keywords = ", ".join(j.get("keywords") or [])
        out.append(
            RawJob(
                external_id=f"instahyre-{j['id']}",
                title=j["title"].strip(),
                location=location,
                description=f"{j['title']} at {company}. Location: {location}. Skills: {keywords}",
                url=j["public_url"],
                remote="work from home" in location.lower(),
                employer=company,
            )
        )
    return out


def fetch_instahyre(pages: int = 3) -> list[RawJob]:
    web, found = _Budget("instahyre"), {}
    for page in range(pages):
        data = web.get(
            "https://www.instahyre.com/api/v1/job_search",
            params={"years": 0, "limit": 35, "offset": page * 35},  # 0 years: entry-level roles
            headers={"Accept": "application/json"},
        ).json()
        batch = parse_instahyre(data)
        for job in batch:
            found.setdefault(job.external_id, job)
        if not data.get("objects") or len(data["objects"]) < 35:
            break
    return list(found.values())


# ---- Foundit (public JSON, needs the Referer a visitor's browser sends) ------------------
def parse_foundit(payload: dict) -> list[RawJob]:
    out = []
    for j in (payload.get("jobSearchResponse") or {}).get("data") or []:
        company = (j.get("companyName") or "").strip()
        if not (j.get("jobId") and j.get("title") and company):
            continue
        posted = ""
        try:
            posted = datetime.fromtimestamp(int(j["createdAt"]) / 1000, tz=timezone.utc).date().isoformat()
        except (KeyError, TypeError, ValueError):
            pass
        low = (j.get("minimumExperience") or {}).get("years")
        exp = f" Experience required: {low} years of experience." if low else ""
        link = j.get("applyUrl") or ("https://www.foundit.in" + j["seoJdUrl"] if j.get("seoJdUrl") else "")
        out.append(
            RawJob(
                external_id=f"foundit-{j['jobId']}",
                title=j["title"].strip(),
                location=(j.get("locations") or "").strip(),
                description=f"{j['title']} at {company}. Location: {j.get('locations', '')}.{exp} Skills: {j.get('skills', '')}",
                url=link,
                posted_at=posted,
                employer=company,
            )
        )
    return out


def fetch_foundit(queries: list[str], cities: list[str], pages: int = 2) -> list[RawJob]:
    web, found = _Budget("foundit"), {}
    headers = {"Accept": "application/json, text/plain, */*", "Referer": "https://www.foundit.in/", "Origin": "https://www.foundit.in"}
    for q in queries:
        for city in cities[:3]:
            for page in range(pages):
                data = web.get(
                    "https://www.foundit.in/middleware/jobsearch",
                    params={"start": page * 15, "limit": 15, "query": q, "locations": city, "sort": 1},
                    headers=headers,
                ).json()
                batch = parse_foundit(data)
                for job in batch:
                    found.setdefault(job.external_id, job)
                if len(batch) < 15:
                    break
    return list(found.values())


# ---- The Muse and Remotive (documented public APIs) -----------------------------------------
def parse_muse(payload: dict) -> list[RawJob]:
    out = []
    for j in payload.get("results") or []:
        company = ((j.get("company") or {}).get("name") or "").strip()
        link = (j.get("refs") or {}).get("landing_page", "")
        if not (j.get("id") and j.get("name") and company and link):
            continue
        places = ", ".join(l.get("name", "") for l in j.get("locations") or [])
        out.append(
            RawJob(
                external_id=f"muse-{j['id']}",
                title=j["name"].strip(),
                location=places,
                description=html_to_text(j.get("contents", "")),
                url=link,
                posted_at=str(j.get("publication_date", ""))[:10],
                remote="remote" in places.lower(),
                employer=company,
            )
        )
    return out


def fetch_muse(pages: int = 3) -> list[RawJob]:
    web, found = _Budget("muse"), {}
    for page in range(1, pages + 1):
        data = web.get(
            "https://www.themuse.com/api/public/jobs",
            params={"page": page, "location": "India", "level": "Entry Level"},
            headers={"Accept": "application/json"},
        ).json()
        for job in parse_muse(data):
            found.setdefault(job.external_id, job)
        if page >= int(data.get("page_count", 1)):
            break
    return list(found.values())


def parse_remotive(payload: dict) -> list[RawJob]:
    out = []
    for j in payload.get("jobs") or []:
        company = (j.get("company_name") or "").strip()
        if not (j.get("id") and j.get("title") and company and j.get("url")):
            continue
        where = (j.get("candidate_required_location") or "Worldwide").strip()
        out.append(
            RawJob(
                external_id=f"remotive-{j['id']}",
                title=j["title"].strip(),
                location=f"Remote - {where}",
                description=html_to_text(j.get("description", "")),
                url=j["url"],
                posted_at=str(j.get("publication_date", ""))[:10],
                remote=True,
                employer=company,
            )
        )
    return out


def fetch_remotive() -> list[RawJob]:
    data = _Budget("remotive").get(
        "https://remotive.com/api/remote-jobs", params={"category": "software-dev", "limit": 100}, headers={"Accept": "application/json"}
    ).json()
    return parse_remotive(data)


# ---- all of them -------------------------------------------------------------------------------
def fetch_all(cities: list[str], queries: list[str], enabled: set[str]) -> tuple[list[RawJob], list[str]]:
    """Read every enabled portal. Returns the jobs and one message per portal that failed or was skipped."""
    jobs: list[RawJob] = []
    problems: list[str] = []
    cities = cities or ["Bengaluru"]
    plan = {
        "internshala": lambda: fetch_internshala([c for c in cities if c.lower() not in {"delhi ncr", "ncr"}][:6]),
        "unstop": lambda: fetch_unstop(queries[:2]),
        "instahyre": fetch_instahyre,
        "foundit": lambda: fetch_foundit(queries[:2], cities),
        "muse": fetch_muse,
        "remotive": fetch_remotive,
    }
    for name, run in plan.items():
        if name not in enabled:
            continue
        try:
            jobs += run()
        except PermissionError:
            continue  # today's allowance is already used: not a failure
        except Exception as exc:
            problems.append(f"{name.title()}: {type(exc).__name__}: {str(exc)[:120]}")
    return jobs, problems
