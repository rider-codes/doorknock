"""Read employers' own job boards directly. One adapter per applicant tracking system."""
import html
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

_board_cache: dict = {}
BOARD_CACHE_SECONDS = 1800


def config_public() -> bool:
    from .. import config

    return config.public_mode()


HEADERS = {"User-Agent": "Doorknock/0.1 (personal job search; reads public job boards)"}
TIMEOUT = 20


@dataclass
class RawJob:
    external_id: str
    title: str
    location: str
    description: str
    url: str
    posted_at: str = ""
    remote: bool = False
    # Some systems list jobs without their text. The text is fetched later, only for jobs that survive the cheap filters.
    detail_ref: str = ""
    needs_detail: bool = False
    employer: str = ""  # only for aggregators, whose jobs come from many employers


def html_to_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


class Paused(RuntimeError):
    """A job board told us to stay away for a long time (a rate limit with a long Retry-After). Not a failure to report."""


def _send(call):
    """Run one request; a rate-limit (429) or a brief server error is waited out and retried a couple of times."""
    for attempt in range(3):
        resp = call()
        if resp.status_code in (429, 502, 503) and attempt < 2:
            wait = float(resp.headers.get("retry-after", 2 * (attempt + 1)) or 2)
            if resp.status_code == 429 and wait > 60:
                raise Paused(f"paused by the board for about {round(wait / 3600)} h")
            time.sleep(min(wait, 8))
            continue
        resp.raise_for_status()
        return resp.json()


def _get_json(url: str, params: dict | None = None):
    return _send(lambda: httpx.get(url, params=params, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True))


# ---- Greenhouse ---------------------------------------------------------------
def parse_greenhouse(payload: dict) -> list[RawJob]:
    jobs = []
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "") or ""
        jobs.append(
            RawJob(
                external_id=str(j["id"]),
                title=j.get("title", ""),
                location=loc,
                description=html_to_text(j.get("content", "")),
                url=j.get("absolute_url", ""),
                posted_at=(j.get("updated_at") or "")[:10],
                remote="remote" in loc.lower(),
            )
        )
    return jobs


def fetch_greenhouse(slug: str) -> list[RawJob]:
    return parse_greenhouse(_get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", {"content": "true"}))


# ---- Lever --------------------------------------------------------------------
def parse_lever(payload: list) -> list[RawJob]:
    jobs = []
    for j in payload:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        created = j.get("createdAt")
        posted = ""
        if isinstance(created, (int, float)):
            posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        workplace = (j.get("workplaceType") or "").lower()
        jobs.append(
            RawJob(
                external_id=str(j["id"]),
                title=j.get("text", ""),
                location=loc,
                description=(j.get("descriptionPlain") or html_to_text(j.get("description", ""))).strip(),
                url=j.get("hostedUrl", ""),
                posted_at=posted,
                remote=workplace == "remote" or "remote" in loc.lower(),
            )
        )
    return jobs


def fetch_lever(slug: str) -> list[RawJob]:
    return parse_lever(_get_json(f"https://api.lever.co/v0/postings/{slug}", {"mode": "json"}))


# ---- Ashby --------------------------------------------------------------------
def parse_ashby(payload: dict) -> list[RawJob]:
    jobs = []
    for j in payload.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        jobs.append(
            RawJob(
                external_id=str(j["id"]),
                title=j.get("title", ""),
                location=loc,
                description=(j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", ""))).strip(),
                url=j.get("jobUrl", ""),
                posted_at=(j.get("publishedAt") or "")[:10],
                remote=bool(j.get("isRemote")) or "remote" in loc.lower(),
            )
        )
    return jobs


def fetch_ashby(slug: str) -> list[RawJob]:
    return parse_ashby(_get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}"))


# ---- shared helpers for the three systems that list jobs without their text -----
COUNTRY_CODES = {
    "india": "in", "united states": "us", "united kingdom": "gb", "germany": "de", "canada": "ca", "france": "fr",
    "netherlands": "nl", "spain": "es", "ireland": "ie", "poland": "pl", "australia": "au", "singapore": "sg",
    "brazil": "br", "mexico": "mx", "japan": "jp", "israel": "il", "sweden": "se", "portugal": "pt",
    "switzerland": "ch", "united arab emirates": "ae",
}
_COUNTRY_ALIASES = {"uae": "united arab emirates", "uk": "united kingdom", "usa": "united states", "us": "united states"}
PAGE_CAP = 400  # most jobs read from one company per run, so a giant employer cannot stall a search


def country_name(raw: str) -> str:
    low = raw.strip().lower()
    return _COUNTRY_ALIASES.get(low, low)


def country_code(raw: str) -> str | None:
    return COUNTRY_CODES.get(country_name(raw))


def _post_json(url: str, body: dict):
    return _send(lambda: httpx.post(url, json=body, headers={**HEADERS, "Accept": "application/json"}, timeout=TIMEOUT, follow_redirects=True))


# ---- SmartRecruiters ------------------------------------------------------------
def parse_smartrecruiters(slug: str, payload: dict) -> list[RawJob]:
    jobs = []
    for j in payload.get("content", []):
        loc = j.get("location") or {}
        full = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x)
        remote = bool(loc.get("remote"))
        jobs.append(
            RawJob(
                external_id=str(j["id"]),
                title=j.get("name", ""),
                location=(f"Remote - {full}" if remote and full else full or ("Remote" if remote else "")),
                description="",
                url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}",
                posted_at=(j.get("releasedDate") or "")[:10],
                remote=remote,
                detail_ref=str(j["id"]),
                needs_detail=True,
            )
        )
    return jobs


def fetch_smartrecruiters(slug: str, hints: dict | None = None) -> list[RawJob]:
    hints = hints or {}
    codes = [c for c in (country_code(x) for x in hints.get("countries", [])) if c]
    queries = (hints.get("queries") or [None])[:3]
    found: dict[str, RawJob] = {}
    for q in queries:
        offset = 0
        while offset < PAGE_CAP:
            params: dict = {"limit": 100, "offset": offset}
            if len(codes) == 1:
                params["country"] = codes[0]
            if q:
                params["q"] = q
            payload = _get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params)
            batch = parse_smartrecruiters(slug, payload)
            for job in batch:
                found.setdefault(job.external_id, job)
            offset += 100
            if not batch or offset >= int(payload.get("totalFound", 0)):
                break
    return list(found.values())


def hydrate_smartrecruiters(slug: str, ref: str) -> dict:
    data = _get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{ref}")
    sections = (data.get("jobAd") or {}).get("sections") or {}
    parts = []
    for key in ("jobDescription", "qualifications", "additionalInformation"):
        sec = sections.get(key) or {}
        if sec.get("text"):
            parts.append(f"{sec.get('title', '')}\n{html_to_text(sec['text'])}".strip())
    return {"description": "\n\n".join(parts)}


# ---- Workday ---------------------------------------------------------------------
# Workday has no official public API, but every employer's careers site is backed by the same JSON endpoint
# the page itself uses. The board id is "tenant/wdN/site", e.g. "nvidia/wd5/NVIDIAExternalCareerSite".
def _wd_base(slug: str) -> str:
    tenant, wd, site = slug.split("/", 2)
    return f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"


def _wd_posted(text: str) -> str:
    from datetime import date, timedelta

    low = (text or "").lower()
    if "today" in low:
        return date.today().isoformat()
    if "yesterday" in low:
        return (date.today() - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*days?", low)
    return (date.today() - timedelta(days=int(m.group(1)))).isoformat() if m else ""


def parse_workday(slug: str, payload: dict) -> list[RawJob]:
    tenant, wd, site = slug.split("/", 2)
    jobs = []
    for j in payload.get("jobPostings", []):
        path = j.get("externalPath") or ""
        if not path:
            continue
        loc = j.get("locationsText") or ""
        req = (j.get("bulletFields") or [""])[0]
        jobs.append(
            RawJob(
                external_id=req or path,
                title=j.get("title", ""),
                location=loc,
                description="",
                url=f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}",
                posted_at=_wd_posted(j.get("postedOn", "")),
                remote="remote" in loc.lower(),
                detail_ref=path,
                needs_detail=True,
            )
        )
    return jobs


def _wd_country_facet(payload: dict, wanted: set[str]) -> tuple[str, str] | None:
    """Find the tenant's own 'filter by country' value so the search itself is limited to the countries you want."""

    def walk(nodes: list, param: str | None):
        for n in nodes:
            p = n.get("facetParameter") or param
            if n.get("id") and p and country_name(n.get("descriptor", "")) in wanted:
                return p, n["id"]
            if n.get("values"):
                hit = walk(n["values"], p)
                if hit:
                    return hit
        return None

    return walk(payload.get("facets") or [], None)


def fetch_workday(slug: str, hints: dict | None = None) -> list[RawJob]:
    hints = hints or {}
    base = _wd_base(slug)
    wanted = {country_name(c) for c in hints.get("countries", []) if c.strip()}
    queries = (hints.get("queries") or [""])[:3]
    found: dict[str, RawJob] = {}
    facet: tuple[str, str] | None | bool = None
    for q in queries:
        applied: dict = {}
        first = _post_json(base + "/jobs", {"appliedFacets": applied, "limit": 20, "offset": 0, "searchText": q})
        if wanted and facet is None:
            facet = _wd_country_facet(first, wanted) or False
        if facet:
            applied = {facet[0]: [facet[1]]}
            first = _post_json(base + "/jobs", {"appliedFacets": applied, "limit": 20, "offset": 0, "searchText": q})
        payload, offset = first, 0
        while True:
            batch = parse_workday(slug, payload)
            for job in batch:
                found.setdefault(job.external_id, job)
            offset += 20
            if not batch or offset >= int(payload.get("total", 0)) or offset >= PAGE_CAP:
                break
            payload = _post_json(base + "/jobs", {"appliedFacets": applied, "limit": 20, "offset": offset, "searchText": q})
    return list(found.values())


def hydrate_workday(slug: str, ref: str) -> dict:
    info = (_get_json(_wd_base(slug) + ref).get("jobPostingInfo")) or {}
    out = {"description": html_to_text(info.get("jobDescription", ""))}
    if info.get("location"):
        extra = info.get("additionalLocations") or []
        out["location"] = ", ".join([info["location"], *extra]) if extra else info["location"]
    if info.get("startDate"):
        out["posted_at"] = str(info["startDate"])[:10]
    return out


# ---- Workable --------------------------------------------------------------------
def parse_workable(slug: str, payload: dict) -> list[RawJob]:
    jobs = []
    for j in payload.get("results", []):
        loc = j.get("location") or {}
        place = ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
        remote = bool(j.get("remote")) or j.get("workplace") == "remote"
        jobs.append(
            RawJob(
                external_id=str(j.get("shortcode") or j.get("id")),
                title=j.get("title", ""),
                location=(f"Remote - {place}" if remote and place else place or ("Remote" if remote else "")),
                description="",
                url=f"https://apply.workable.com/{slug}/j/{j.get('shortcode')}/",
                posted_at=(j.get("published") or "")[:10],
                remote=remote,
                detail_ref=str(j.get("shortcode") or ""),
                needs_detail=True,
            )
        )
    return jobs


def fetch_workable(slug: str, hints: dict | None = None) -> list[RawJob]:
    hints = hints or {}
    url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
    found: dict[str, RawJob] = {}
    for q in (hints.get("queries") or [""])[:3]:
        body: dict = {"query": q, "location": [], "department": [], "worktype": [], "remote": []}
        for _ in range(PAGE_CAP // 10):
            payload = _post_json(url, body)
            for job in parse_workable(slug, payload):
                found.setdefault(job.external_id, job)
            token = payload.get("nextPage")
            if not token or not payload.get("results"):
                break
            body["token"] = token
    return list(found.values())


def hydrate_workable(slug: str, ref: str) -> dict:
    data = _get_json(f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{ref}")
    parts = [html_to_text(data.get(k) or "") for k in ("description", "requirements", "benefits")]
    return {"description": "\n\n".join(p for p in parts if p)}


# Greenhouse, Lever and Ashby return the full text in the list, so they ignore hints and need no detail step.
ADAPTERS = {
    "greenhouse": lambda slug, hints=None: fetch_greenhouse(slug),
    "lever": lambda slug, hints=None: fetch_lever(slug),
    "ashby": lambda slug, hints=None: fetch_ashby(slug),
    "smartrecruiters": fetch_smartrecruiters,
    "workday": fetch_workday,
    "workable": fetch_workable,
}
HYDRATORS = {"smartrecruiters": hydrate_smartrecruiters, "workday": hydrate_workday, "workable": hydrate_workable}

_WD_URL = re.compile(r"https?://([\w\-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w\-]+)", re.I)
_URL_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w\-]+)", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w\-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w\-.%]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w\-.%]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?!api/)([\w\-]+)", re.I)),
]


def parse_board_url(url: str) -> tuple[str, str] | None:
    """'https://boards.greenhouse.io/stripe' -> ('greenhouse', 'stripe').
    Workday links carry three parts, so the slug is 'tenant/wdN/site'."""
    wd = _WD_URL.search(url)
    if wd:
        return "workday", f"{wd.group(1)}/{wd.group(2).lower()}/{wd.group(3)}"
    for ats, pattern in _URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return ats, m.group(1)
    return None


def fetch(ats: str, slug: str, hints: dict | None = None) -> list[RawJob]:
    """`hints` ({'countries': [...], 'queries': [...]}) narrows the search on systems that support it, so a
    company with thousands of openings is searched for your roles and countries instead of read end to end."""
    if ats not in ADAPTERS:
        raise ValueError(f"Unknown job board type: {ats}")
    key = (ats, slug, repr(sorted((hints or {}).items())))
    if config_public():
        hit = _board_cache.get(key)
        if hit and time.time() - hit[0] < BOARD_CACHE_SECONDS:
            return hit[1]  # many visitors, one read of each board
    jobs = ADAPTERS[ats](slug, hints)
    if config_public():
        _board_cache[key] = (time.time(), jobs)
    return jobs


def hydrate(ats: str, slug: str, ref: str) -> dict:
    """Fetch the full text of one job (for systems whose list omits it)."""
    if ats not in HYDRATORS:
        return {}
    return HYDRATORS[ats](slug, ref)


# ---- aggregator (many employers in one feed) ---------------------------------------
def parse_adzuna(payload: dict) -> list[RawJob]:
    out = []
    for j in payload.get("results") or []:
        employer = ((j.get("company") or {}).get("display_name") or "").strip()
        if not j.get("id") or not j.get("title") or not employer:
            continue
        out.append(
            RawJob(
                external_id=f"adzuna-{j['id']}",
                title=html_to_text(j["title"]).strip(),
                location=((j.get("location") or {}).get("display_name") or "").strip(),
                description=html_to_text(j.get("description", "")),  # the feed only gives a summary of the posting
                url=j.get("redirect_url", ""),
                posted_at=str(j.get("created", ""))[:10],
                remote=False,
                employer=employer,
            )
        )
    return out


def fetch_adzuna(app_id: str, app_key: str, queries: list[str], places: list[str], country: str = "in", pages: int = 3) -> list[RawJob]:
    """Search the Adzuna aggregator for each (query, place) pair. Employers' own boards cover few Indian companies; this does."""
    found: dict[str, RawJob] = {}
    for q in queries:
        for place in places or [""]:
            for page in range(1, pages + 1):
                params = {"app_id": app_id, "app_key": app_key, "results_per_page": 50, "what": q, "max_days_old": 30, "sort_by": "date", "content-type": "application/json"}
                if place:
                    params["where"] = place
                payload = _get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}", params)
                batch = parse_adzuna(payload)
                for job in batch:
                    found.setdefault(job.external_id, job)
                if len(batch) < 50:
                    break
    return list(found.values())


def parse_jooble(payload: dict, max_age_days: int = 45) -> list[RawJob]:
    out = []
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).date().isoformat()
    for j in payload.get("jobs") or []:
        employer = (j.get("company") or "").strip()
        posted = str(j.get("updated", ""))[:10]
        if not (j.get("id") and j.get("title") and employer and j.get("link")) or (posted and posted < cutoff):
            continue
        out.append(
            RawJob(
                external_id=f"jooble-{j['id']}",
                title=html_to_text(j["title"]).strip(),
                location=(j.get("location") or "").strip(),
                description=html_to_text(j.get("snippet", "")),  # only a snippet; the link goes through Jooble to the employer
                url=j["link"],
                posted_at=posted,
                employer=employer,
            )
        )
    return out


def fetch_jooble(api_key: str, queries: list[str], location: str, pages: int, allow, spend) -> list[RawJob]:
    """Search Jooble. `allow()` and `spend()` enforce the request budget; Jooble resolves any Indian city to the whole country,
    so one location is searched per query."""
    found: dict[str, RawJob] = {}
    for q in queries:
        for page in range(1, pages + 1):
            if not allow():
                return list(found.values())
            spend()
            resp = httpx.post(f"https://jooble.org/api/{api_key}", json={"keywords": q, "location": location, "page": page}, timeout=TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            batch = parse_jooble(payload)
            for job in batch:
                found.setdefault(job.external_id, job)
            if len(payload.get("jobs") or []) < 30:
                break
    return list(found.values())
