"""Chat -> structured search brief.

The model reads the message; code then checks and tidies what it returned (see `tidy`), because a wrongly read brief
silently shapes every search that follows."""
import json
import re

from .. import llm
from ..schemas import BriefData, BriefReply

SYSTEM = """You turn what a job seeker says into a structured job-search brief, and keep it up to date as they refine it.
You get the current brief, a summary of their resume, and the chat so far. Return the FULL updated brief and a short reply.

FIELDS
- roles: the job titles they want, 1-4 clean titles ("Backend Engineer", "Data Analyst"). Use the person's own words first.
  If they say "anything that fits my resume", "just look at my resume" or similar, or name no role at all, infer 1-3 roles from the
  resume summary (headline, recent titles, skills) and say so in the reply.
- title_keywords: lowercase words or short phrases that a MATCHING job posting's TITLE would contain, so postings can be matched
  on title. Include the role itself and its common synonyms, spellings and abbreviations. 5-12 entries.
  Example for Backend Engineer: backend, back-end, back end, software engineer, software developer, sde, server-side, api engineer.
  Never put generic words alone ("engineer", "developer", "manager") unless the person asked for any of them.
- avoid_titles: title words that mean the posting is NOT what they want ("sales", "recruiter", "marketing", "support"...),
  only for fields clearly unrelated to the roles. Leave empty if unsure.
- level: intern, entry, mid or senior. "fresher", "new grad", "graduate", "junior", "0-2 years", "just starting" = entry.
  "3-5 years" = mid. "Nothing senior" means not senior: pick entry or mid from their experience.
- cities: specific cities only, in their usual English spelling (Bengaluru, Mumbai, Hyderabad, Gurugram, Noida).
  Never put a country, state or "remote" here. A region such as "Delhi NCR" becomes Delhi, Noida, Gurugram.
- countries: full names (India, United States). Add the country of any city they name.
- remote_ok: true unless they say they do not want remote work. "Remote only" keeps it true and leaves cities empty.
- job_type: full_time, intern, contract or any. "Internship" = intern. Default full_time.
- keywords: skills or topics they care about (Python, fintech, startups). exclude_keywords: things they refuse ("gambling", "unpaid").

RULES
- Only change what the latest message affects; keep everything else exactly as it is.
- A new request for a different kind of job REPLACES roles and title_keywords. A refinement ("also data roles") adds to them.
- Never invent a preference the person did not state, except roles/title_keywords inferred from the resume as described above.
- reply: at most 2 short sentences. Say what you understood (role, level, place) so they can correct you.
  If the role or the city is unclear, ask ONE question for it instead of guessing.

EXAMPLES
"backend roles at product companies in Bengaluru or remote in India. nothing senior" ->
  roles ["Backend Engineer"], title_keywords [backend, back-end, back end, software engineer, software developer, sde, server-side],
  level entry, cities ["Bengaluru"], countries ["India"], remote_ok true, keywords ["product companies"].
"i'm a fresher, any data job in pune, no remote" ->
  roles ["Data Analyst", "Data Engineer"], title_keywords [data analyst, data engineer, data scientist, analytics, business intelligence, bi developer],
  level entry, cities ["Pune"], countries ["India"], remote_ok false."""


def profile_summary(profile: dict | None) -> str:
    if not profile:
        return "No resume uploaded yet."
    return json.dumps(
        {
            "headline": profile.get("headline"),
            "seniority": profile.get("seniority"),
            "years_experience": profile.get("years_experience"),
            "recent_titles": [e.get("title") for e in (profile.get("experience") or [])[:3] if e.get("title")],
            "skills": (profile.get("skills") or [])[:20],
            "locations": profile.get("locations"),
        }
    )


# ---- checks in code ---------------------------------------------------------------------------
CITY_NAMES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "bombay": "Mumbai", "madras": "Chennai", "calcutta": "Kolkata",
    "gurgaon": "Gurugram", "gurugram": "Gurugram", "new delhi": "Delhi", "delhi ncr": "Delhi", "ncr": "Delhi",
}
INDIAN_CITIES = {
    "bengaluru", "mumbai", "chennai", "kolkata", "gurugram", "delhi", "noida", "hyderabad", "pune", "ahmedabad", "jaipur",
    "kochi", "indore", "chandigarh", "coimbatore", "lucknow", "nagpur", "ghaziabad", "faridabad", "thiruvananthapuram", "bhubaneswar",
}
COUNTRY_WORDS = {"india": "India", "usa": "United States", "us": "United States", "united states": "United States", "uk": "United Kingdom",
                 "united kingdom": "United Kingdom", "canada": "Canada", "germany": "Germany", "singapore": "Singapore", "uae": "United Arab Emirates"}
_NOT_PLACES = {"remote", "anywhere", "wfh", "work from home", "hybrid", "onsite"}
_NO_REMOTE = re.compile(r"\b(no|not|without|don'?t want|do not want|avoid)\s+(remote|wfh|work from home)\b|\bon-?site only\b|\bin[- ]office only\b", re.I)
_FRESHER = re.compile(r"\b(fresher|freshers|new grad|new graduate|fresh graduate|entry[- ]level|0-?1 years?|just graduated|recent graduate)\b", re.I)


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for item in items:
        item = re.sub(r"\s+", " ", (item or "").strip())
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def tidy(brief: BriefData, message: str, profile: dict | None) -> BriefData:
    """Fix what a model commonly gets wrong, and apply the plain-language cues that are never ambiguous."""
    cities, countries = [], list(brief.countries)
    for raw in brief.cities:
        low = raw.strip().lower()
        if low in _NOT_PLACES:
            continue
        if low in COUNTRY_WORDS:  # a country that landed in the city list
            countries.append(COUNTRY_WORDS[low])
            continue
        cities.append(CITY_NAMES.get(low, raw.strip().title() if raw.islower() else raw.strip()))
    cities = _dedupe(cities)
    countries = _dedupe([COUNTRY_WORDS.get(c.strip().lower(), c.strip()) for c in countries])
    if not countries and cities and all(c.lower() in INDIAN_CITIES for c in cities):
        countries = ["India"]
    brief.cities, brief.countries = cities, countries
    brief.roles = _dedupe(brief.roles)[:4]
    brief.title_keywords = _dedupe([k.lower() for k in brief.title_keywords])[:14]
    brief.avoid_titles = _dedupe([k.lower() for k in brief.avoid_titles])[:10]
    brief.keywords = _dedupe(brief.keywords)
    brief.exclude_keywords = _dedupe(brief.exclude_keywords)
    # a title word the person wants must never also be one they avoid
    brief.avoid_titles = [a for a in brief.avoid_titles if not any(a in k or k in a for k in brief.title_keywords + [r.lower() for r in brief.roles])]
    if _NO_REMOTE.search(message):
        brief.remote_ok = False
    if _FRESHER.search(message) and brief.level in ("mid", "senior"):
        brief.level = "entry"
    if not brief.roles and profile:  # nothing usable came back: fall back to what the resume says
        titles = [e.get("title") for e in (profile.get("experience") or []) if e.get("title")]
        brief.roles = _dedupe(titles[:2] or [profile.get("headline") or ""])
    return brief


def chat(current: dict, history: list[dict], message: str, profile: dict | None) -> BriefReply:
    messages: list[dict] = []
    context = (
        f"Current brief: {json.dumps(current)}\nResume summary: {profile_summary(profile)}\n\n"
        "Conversation follows. Update the brief based on the last user message."
    )
    messages.append({"role": "user", "content": context})
    messages.append({"role": "assistant", "content": "Understood."})
    for turn in history[-12:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})
    # the API needs strictly alternating roles
    merged: list[dict] = []
    for m in messages:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n" + m["content"]
        else:
            merged.append(dict(m))
    result = llm.structured_model(BriefReply, purpose="brief_chat", system=SYSTEM, user=merged)
    result.brief = tidy(BriefData.model_validate(result.brief.model_dump()), message, profile)
    return result
