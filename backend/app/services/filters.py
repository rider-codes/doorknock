"""Hard rules. Deterministic, cheap, and every rejection carries a reason the user can read."""
import re
from dataclasses import dataclass

# How many years of required experience each level tolerates.
LEVEL_MAX_YEARS = {"intern": 1, "entry": 2, "mid": 5, "senior": 99}

_SENIOR_ALWAYS = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|head of|director|vp|vice president|distinguished|chief|architect)\b", re.I
)
_SENIOR_MID_OK = re.compile(r"\b(staff|principal|head of|director|vp|vice president|distinguished|chief)\b", re.I)
_INTERN = re.compile(r"\b(intern|internship|working student|co-?op)\b", re.I)
_CONTRACT = re.compile(r"\b(contract|contractor|freelance|part[- ]time|temporary)\b", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:[-–to]+\s*\d{1,2}\s*)?\+?\s*(?:years?|yrs?)\b", re.I)
_REMOTE = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed)\b", re.I)

# alias -> canonical country. Matched on word boundaries; "US" is case-sensitive.
_COUNTRIES = {
    "india": "india",
    "united states": "united states",
    "usa": "united states",
    "u.s.": "united states",
    "united kingdom": "united kingdom",
    "uk": "united kingdom",
    "england": "united kingdom",
    "canada": "canada",
    "germany": "germany",
    "france": "france",
    "netherlands": "netherlands",
    "spain": "spain",
    "ireland": "ireland",
    "poland": "poland",
    "australia": "australia",
    "singapore": "singapore",
    "brazil": "brazil",
    "mexico": "mexico",
    "japan": "japan",
    "israel": "israel",
    "sweden": "sweden",
    "portugal": "portugal",
    "switzerland": "switzerland",
    "united arab emirates": "united arab emirates",
    "uae": "united arab emirates",
}
_MANY_LOCATIONS = re.compile(r"^\d+\s+locations?$", re.I)
_US_UPPER = re.compile(r"\bUS\b")
_EUROPE = re.compile(r"\b(emea|europe|eu)\b", re.I)


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


def required_years(text: str) -> int | None:
    """Smallest 'N years' figure that sits near the word 'experience'. None if the posting names none."""
    found: list[int] = []
    for m in _YEARS.finditer(text):
        window = text[max(0, m.start() - 90) : m.end() + 90].lower()
        if "experience" in window or "exp" in window:
            found.append(int(m.group(1)))
    return min(found) if found else None


def detect_countries(location: str) -> set[str]:
    low = location.lower()
    hits = set()
    for alias, canon in _COUNTRIES.items():
        if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", low):
            hits.add(canon)
    if _US_UPPER.search(location):
        hits.add("united states")
    return hits


def canonical_country(name: str) -> str:
    low = name.strip().lower()
    return _COUNTRIES.get(low, low)


def level_ok(title: str, description: str, level: str) -> Verdict:
    if level in ("entry", "intern") and _SENIOR_ALWAYS.search(title):
        return Verdict(False, f"Too senior: title says '{_SENIOR_ALWAYS.search(title).group(0)}'")
    if level == "mid" and _SENIOR_MID_OK.search(title):
        return Verdict(False, f"Too senior: title says '{_SENIOR_MID_OK.search(title).group(0)}'")
    years = required_years(description)
    cap = LEVEL_MAX_YEARS.get(level, 99)
    if years is not None and years > cap:
        return Verdict(False, f"Asks for {years}+ years of experience (your level allows up to {cap})")
    return Verdict(True)


def type_ok(title: str, job_type: str) -> Verdict:
    if job_type == "any":
        return Verdict(True)
    is_intern = bool(_INTERN.search(title))
    if job_type == "full_time":
        if is_intern:
            return Verdict(False, "Internship (you want full-time)")
        if _CONTRACT.search(title):
            return Verdict(False, "Contract or part-time (you want full-time)")
    if job_type == "intern" and not is_intern:
        return Verdict(False, "Not an internship")
    if job_type == "contract" and not _CONTRACT.search(title):
        return Verdict(False, "Not a contract role")
    return Verdict(True)


# names that mean the same place: asking for any of one group matches all of it
_AREAS = (
    ("noida", "greater noida", "delhi", "new delhi", "gurgaon", "gurugram", "ghaziabad", "faridabad", "ncr", "delhi ncr"),
    ("bengaluru", "bangalore", "bengaluru urban"),
    ("mumbai", "navi mumbai", "thane", "bombay"),
    ("hyderabad", "secunderabad", "hitec city"),
    ("chennai", "madras"),
    ("pune", "pimpri", "pimpri-chinchwad"),
    ("kolkata", "calcutta"),
)
_NCR = _AREAS[0]


def _expand_areas(cities: list[str]) -> list[str]:
    out = [c.strip().lower() for c in cities if c.strip()]
    for group in _AREAS:
        if any(c in group for c in out):
            out += [c for c in group if c not in out]
    return out


def location_ok(location: str, remote: bool, cities: list[str], countries: list[str], remote_ok: bool) -> Verdict:
    loc = (location or "").strip()
    low = loc.lower()
    cities_l = _expand_areas(cities)
    want_countries = {canonical_country(c) for c in countries if c.strip()}
    job_countries = detect_countries(loc)
    # a board's remote flag only counts when the location does not name a real place: 'San Francisco' flagged remote is still San Francisco
    is_remote = bool(_REMOTE.search(loc)) or (remote and not loc)

    if any(c in low for c in cities_l):
        return Verdict(True)
    if is_remote:
        if not remote_ok:
            return Verdict(False, f"Remote role ({loc or 'remote'}); you ruled remote out")
        if want_countries and job_countries and not (job_countries & want_countries):
            return Verdict(False, f"Remote, but limited to {', '.join(sorted(job_countries))}")
        if want_countries and not job_countries and _EUROPE.search(loc) and "india" in want_countries:
            return Verdict(False, f"Remote, but limited to {loc}")
        return Verdict(True)
    if want_countries and low in {c.lower() for c in countries if c.strip()} | want_countries:
        return Verdict(True)  # only a country is given (aggregators do this): the scorer judges the city from the posting
    if not loc or _MANY_LOCATIONS.match(loc):
        return Verdict(True)  # unknown location (or Workday's "3 Locations" placeholder): decided once the full text is read
    if not cities_l and not want_countries:
        return Verdict(True)
    if not cities_l and job_countries & want_countries:
        return Verdict(True)
    return Verdict(False, f"Location '{loc}' is outside your cities and countries")


def keywords_ok(title: str, description: str, exclude: list[str]) -> Verdict:
    hay = f"{title}\n{description[:4000]}".lower()
    for word in exclude:
        w = word.strip().lower()
        if w and re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", hay):
            return Verdict(False, f"Contains '{word}', which you excluded")
    return Verdict(True)


def role_ok(title: str, roles: list[str], title_keywords: list[str], avoid_titles: list[str]) -> Verdict:
    """The posting's title must look like one of the wanted roles. With no role information there is nothing to compare."""
    low = f" {re.sub(r'[^a-z0-9+#]+', ' ', (title or '').lower())} "
    for bad in avoid_titles:
        b = re.sub(r"[^a-z0-9+#]+", " ", bad.lower()).strip()
        if b and f" {b} " in low:
            return Verdict(False, f"Title says '{bad}', which is not the kind of role you want")
    wanted = [re.sub(r"[^a-z0-9+#]+", " ", k.lower()).strip() for k in title_keywords if k.strip()]
    if not wanted:
        return Verdict(True)
    if any(f" {w} " in low for w in wanted):
        return Verdict(True)
    for role in roles:  # every significant word of a wanted role, in any order ("Engineer, Backend")
        words = [w for w in re.findall(r"[a-z0-9+#]+", role.lower()) if w not in {"and", "the", "of", "for"}]
        if len(words) > 1 and all(f" {w} " in low for w in words):
            return Verdict(True)
    return Verdict(False, "Title does not look like the roles you want")


def evaluate(job_title: str, job_location: str, job_remote: bool, job_description: str, brief: dict) -> Verdict:
    for verdict in (
        type_ok(job_title, brief.get("job_type", "full_time")),
        level_ok(job_title, job_description, brief.get("level", "entry")),
        location_ok(
            job_location,
            job_remote,
            brief.get("cities", []),
            brief.get("countries", []),
            brief.get("remote_ok", True),
        ),
        role_ok(job_title, brief.get("roles", []), brief.get("title_keywords", []), brief.get("avoid_titles", [])),
        keywords_ok(job_title, job_description, brief.get("exclude_keywords", [])),
    ):
        if not verdict.ok:
            return verdict
    return Verdict(True)
