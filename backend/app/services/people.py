"""Find recruiters, hiring managers and teammates, ranked by relevance and by whether the email is verified."""
import logging
import re
from dataclasses import dataclass

import httpx

from .. import config

log = logging.getLogger("doorknock.people")

_RECRUITER = re.compile(r"\b(recruit\w*|talent|sourcer|people (?:partner|operations|team)|human resources|hr)\b", re.I)
_MANAGER = re.compile(
    r"\b(engineering manager|head of|director|vp|vice president|chief|cto|founder|co-?founder|manager|lead)\b", re.I
)
_STOP = {"the", "and", "for", "of", "to", "in", "a", "an", "at", "engineer", "software", "senior", "junior", "i", "ii"}


@dataclass
class RawPerson:
    name: str
    title: str
    email: str
    email_status: str  # verified | risky | unknown
    source: str


class PeopleError(RuntimeError):
    pass


def classify(title: str) -> str:
    if _RECRUITER.search(title or ""):
        return "recruiter"
    if _MANAGER.search(title or ""):
        return "hiring_manager"
    return "teammate"


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#]{3,}", (text or "").lower()) if t not in _STOP}


def relevance(person: RawPerson, job_title: str) -> tuple[int, str]:
    role = classify(person.title)
    base = {"recruiter": 62, "hiring_manager": 66, "teammate": 42}[role]
    overlap = len(_tokens(person.title) & _tokens(job_title))
    base += min(overlap * 7, 18)
    if person.email_status == "verified":
        base += 10
    elif person.email_status == "risky":
        base += 4
    why = {
        "recruiter": "Recruiting contact for the company",
        "hiring_manager": "Likely makes or influences the hiring decision",
        "teammate": "Works near this role",
    }[role]
    if overlap:
        why = f"{why}; title overlaps with the job"
    return min(base, 99), why


def rank(people: list[RawPerson], job_title: str, limit: int = 6) -> list[dict]:
    seen: set[str] = set()
    rows = []
    for p in people:
        key = (p.email or p.name).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        score, why = relevance(p, job_title)
        rows.append(
            {
                "name": p.name,
                "title": p.title,
                "role_type": classify(p.title),
                "email": p.email,
                "email_status": p.email_status,
                "relevance": score,
                "why": why,
                "source": p.source,
            }
        )
    status_order = {"verified": 0, "risky": 1, "unknown": 2}
    rows.sort(key=lambda r: (-r["relevance"], status_order.get(r["email_status"], 3)))
    return rows[:limit]


# ---- providers ----------------------------------------------------------------
HUNTER_RESERVE = 2  # searches always left unspent
_quota_cache: dict[str, dict] = {}  # per key: on a public site every visitor has their own allowance


def hunter_quota() -> dict | None:
    """{'used', 'available'} searches this month, read from Hunter (free to ask) and remembered for a few minutes."""
    import time

    key = config.hunter_key()
    if not key:
        return None
    slot = _quota_cache.setdefault(config.key_id(key), {"at": 0.0, "value": None})
    if time.time() - slot["at"] < 300:
        return slot["value"]
    value = None
    try:
        resp = httpx.get("https://api.hunter.io/v2/account", params={"api_key": key}, timeout=5)
        if resp.status_code == 200:
            searches = ((resp.json().get("data") or {}).get("requests") or {}).get("searches") or {}
            value = {"used": int(searches.get("used", 0)), "available": int(searches.get("available", 0))}
    except (httpx.HTTPError, ValueError):
        pass
    slot.update(at=time.time() if value else time.time() - 240, value=value)  # a failed look is retried in about a minute
    return value


def invalidate_quota() -> None:
    slot = _quota_cache.get(config.key_id(config.hunter_key()))
    if slot:
        slot["at"] = 0.0


def _hunter_check_quota(key: str) -> None:
    """Hunter's free plan has a small monthly allowance. Asking for the account details costs nothing, so look before spending."""
    try:
        resp = httpx.get("https://api.hunter.io/v2/account", params={"api_key": key}, timeout=15)
        left = ((resp.json().get("data") or {}).get("requests") or {}).get("searches", {}).get("available", 0) - (
            ((resp.json().get("data") or {}).get("requests") or {}).get("searches", {}).get("used", 0)
        )
    except (httpx.HTTPError, ValueError):
        return  # cannot tell: let the search itself report a quota problem
    if resp.status_code == 200 and left <= HUNTER_RESERVE:
        raise PeopleError(f"Hunter's monthly search allowance is nearly used ({max(left, 0)} left). Add the person by hand, or wait for it to reset.")


def _hunter(domain: str) -> list[RawPerson]:
    key = config.hunter_key()
    if not key:
        raise PeopleError("Add your Hunter key above to search for emails." if config.public_mode() else "HUNTER_API_KEY is not set. Add it to backend/.env.")
    _hunter_check_quota(key)
    resp = httpx.get(
        "https://api.hunter.io/v2/domain-search",
        params={"domain": domain, "limit": int(config.env("HUNTER_LIMIT", "10")), "api_key": key},  # the free plan allows 10 per search
        timeout=20,
    )
    if resp.status_code == 401:
        raise PeopleError("Hunter rejected the API key.")
    if resp.status_code == 429:
        raise PeopleError("Hunter rate limit or quota reached.")
    if resp.status_code >= 400:  # say what Hunter said instead of failing with a server error
        try:
            detail = (resp.json().get("errors") or [{}])[0].get("details") or resp.text[:160]
        except ValueError:
            detail = resp.text[:160]
        raise PeopleError(f"Hunter could not search {domain}: {detail}")
    out: list[RawPerson] = []
    for e in (resp.json().get("data") or {}).get("emails", []):
        if e.get("type") != "personal" or not e.get("value"):
            continue
        status = ((e.get("verification") or {}).get("status") or "").lower()
        if status == "invalid":
            continue
        mapped = "verified" if status == "valid" else "risky" if status == "accept_all" else "unknown"
        name = " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x)
        out.append(RawPerson(name or e["value"].split("@")[0], e.get("position") or "", e["value"], mapped, "Hunter"))
    return out


def _mock(domain: str) -> list[RawPerson]:
    """Obvious fakes for demos. Emails use the reserved .invalid TLD so nothing can be delivered."""
    return [
        RawPerson("Sample Recruiter", "Technical Recruiter", f"sample.recruiter@{domain}.invalid", "unknown", "mock"),
        RawPerson("Sample Manager", "Engineering Manager", f"sample.manager@{domain}.invalid", "unknown", "mock"),
        RawPerson("Sample Engineer", "Software Engineer", f"sample.engineer@{domain}.invalid", "unknown", "mock"),
    ]


# ---- the job posting itself -----------------------------------------------------
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_GENERIC = {"careers", "jobs", "job", "hr", "recruiting", "recruitment", "recruiter", "talent", "hiring", "people", "apply", "work"}
_NAME = r"([A-Z][a-z'’-]+(?:\s[A-Z][a-z'’-]+){1,2})"
_NAMED = re.compile(
    r"(?i:hiring manager|recruiter|recruiting contact|talent partner|contact|reach out to|managed by|report(?:s|ing)? to)"
    r"\s*(?:is|:|-|–)?\s*" + _NAME
)
_NOT_NAMES = {"Human Resources", "Equal Opportunity", "The Team", "Our Team", "Talent Acquisition", "Hiring Manager", "Privacy Policy"}


def scan_posting(text: str, domain: str = "") -> list[RawPerson]:
    """Contacts the employer printed in the posting: published emails and 'Recruiter: Jane Doe' style mentions."""
    out: list[RawPerson] = []
    seen: set[str] = set()
    for m in _EMAIL.finditer(text or ""):
        email = m.group(0).strip(".,;:)").lower()
        local, _, host = email.partition("@")
        if email in seen or host.endswith(("example.com", "example.org", "sentry.io")) or local in {"noreply", "no-reply", "privacy", "legal"}:
            continue
        seen.add(email)
        if domain and domain.lower() not in host:
            continue  # an unrelated address (an ATS, a vendor) rather than the employer's
        if local in _GENERIC:
            out.append(RawPerson("Recruiting team", "Careers inbox", email, "unknown", "Job posting"))
        else:
            name = " ".join(w.capitalize() for w in re.split(r"[._-]+", local) if w.isalpha())
            out.append(RawPerson(name or local, "Named in the posting", email, "unknown", "Job posting"))
    for m in _NAMED.finditer(text or ""):
        name = m.group(1).strip()
        if name in _NOT_NAMES or any(name.lower() == (p.name or "").lower() for p in out):
            continue
        label = m.group(0).lower()
        title = "Recruiter" if "recruit" in label or "talent" in label else "Hiring manager" if "hiring" in label or "report" in label else "Named in the posting"
        out.append(RawPerson(name, title, "", "unknown", "Job posting"))
    return out


# ---- a person the user found themselves ----------------------------------------------
def _slug(part: str) -> str:
    return re.sub(r"[^a-z0-9]", "", part.lower())


def _hunter_finder(domain: str, first: str, last: str) -> tuple[str, str] | None:
    key = config.hunter_key()
    if not key:
        return None
    try:
        _hunter_check_quota(key)
    except PeopleError:
        return None  # out of allowance: fall back to a guessed address
    try:
        resp = httpx.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first, "last_name": last, "api_key": key},
            timeout=20,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data") or {}
        if not data.get("email"):
            return None
        v = ((data.get("verification") or {}).get("status") or "").lower()
        return data["email"], ("verified" if v == "valid" else "risky" if v == "accept_all" else "unknown")
    except httpx.HTTPError:
        return None


def add_manual(name: str, title: str, email: str, domain: str, job_title: str) -> dict:
    """Someone found on LinkedIn or elsewhere. Use the email as given; otherwise ask Hunter, otherwise guess the usual pattern."""
    name, title, email = " ".join(name.split()), " ".join(title.split()), email.strip().lower()
    if not name:
        raise PeopleError("Enter the person's name.")
    status, source = "unknown", "You added"
    parts = name.split()
    if email:
        if not _EMAIL.fullmatch(email):
            raise PeopleError("That email address does not look right.")
        how = "Email supplied by you"
    elif domain and len(parts) > 1:
        found = _hunter_finder(domain, parts[0], parts[-1]) if provider_name() == "hunter" else None
        if found:
            email, status = found
            source, how = "You added + Hunter", "Email found by Hunter"
        else:
            email = f"{_slug(parts[0])}.{_slug(parts[-1])}@{domain}"
            how = "Email guessed from the usual first.last pattern; confirm it before sending"
    elif domain:
        how = "No email: add a surname or the address so it can be found"
    else:
        how = "No email: add the company website or the address"
    row = rank([RawPerson(name, title, email, status, source)], job_title)[0]
    row["relevance"] = max(row["relevance"], 80)  # chosen by the user, so it leads the list
    row["why"] = how
    return row


def provider_name() -> str:
    if config.public_mode():
        return "hunter" if config.hunter_key() else "none"  # only if the visitor brought a key
    return config.people_provider()


SYSTEM_RANK = """You help a job seeker decide who to email about one specific job.
You get the job and a numbered list of people found at the company (name, title, whether their email is verified).
Pick the people most likely to be the right contact and rank them:
- recruiter: a recruiter or talent partner who plausibly handles THIS kind of role (match the department, seniority and region when titles show it).
- hiring_manager: the manager, lead or head of the team this job sits in.
- teammate: an engineer or peer on that team who could refer or answer questions.
- skip: everyone unrelated (sales, legal, finance, a different department, assistants, executives far above the team).
relevance is 0-100 for how good a first email to this person would be. Give a one-line reason that names the title match.
Use only the numbers given. Return at most 8 people, best first, and mark the rest skip or leave them out."""


def rank_with_llm(raw: list[RawPerson], job: dict, limit: int = 6) -> list[dict]:
    """Let a strong model choose the right contacts. Raises LLMError if it cannot, so the caller can fall back to rules."""
    from .. import llm
    from ..schemas import PeopleRanking

    cands = raw[:40]
    lines = [f"{i}: {p.name} | {p.title or 'no title listed'} | email {p.email_status}" for i, p in enumerate(cands)]
    prompt = (
        f"JOB: {job.get('title', '')} at {job.get('company', '')} ({job.get('location', '') or 'location not listed'})\n"
        f"{(job.get('description') or '')[:1800]}\n\nPEOPLE:\n" + "\n".join(lines)
    )
    result = llm.structured_model(PeopleRanking, purpose="people_rank", system=SYSTEM_RANK, user=prompt, max_tokens=3000)
    rows, seen = [], set()
    for r in result.ranked:
        if r.role_type == "skip" or not (0 <= r.index < len(cands)) or r.index in seen:
            continue
        seen.add(r.index)
        p = cands[r.index]
        bonus = 10 if p.email_status == "verified" else 4 if p.email_status == "risky" else 0
        rows.append(
            {
                "name": p.name,
                "title": p.title,
                "role_type": r.role_type,
                "email": p.email,
                "email_status": p.email_status,
                "relevance": min(99, r.relevance + bonus),
                "why": r.why.strip() or "Matches the job",
                "source": p.source,
            }
        )
    if not rows:
        raise llm.LLMError("The model did not choose anyone.")
    status_order = {"verified": 0, "risky": 1, "unknown": 2}
    rows.sort(key=lambda r: (-r["relevance"], status_order.get(r["email_status"], 3)))
    return rows[:limit]


def find(domain: str, job_title: str, job: dict | None = None) -> list[dict]:
    """People at the company: contacts printed in the posting plus the provider's list. With an AI key, a strong model picks."""
    scanned = scan_posting((job or {}).get("description", ""), domain) if job else []
    provider = provider_name()
    if provider == "hunter":
        raw = _hunter(domain)
    elif provider == "mock":
        raw = _mock(domain)
    elif scanned:
        raw = []
    else:
        raise PeopleError(
            "Nothing named in the posting, and no people provider is configured. Paste a name below, or set "
            "PEOPLE_PROVIDER=hunter and HUNTER_API_KEY in backend/.env (PEOPLE_PROVIDER=mock shows fake contacts)."
        )
    if job and raw and config.llm_ready():
        try:
            rows = rank_with_llm(raw, job)
            have = {r["email"] or r["name"] for r in rows}
            # contacts the employer printed in the posting always stay in the list
            return rows + [r for r in rank(scanned, job_title) if (r["email"] or r["name"]) not in have]
        except Exception as exc:  # any AI failure: fall back to the rule-based ranking rather than losing the search
            log.warning("AI people ranking failed (%s); using rules", exc)
    return rank(scanned + raw, job_title)
