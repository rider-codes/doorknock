"""Cold emails written only from facts quoted out of the resume or the posting, then checked in code."""
import json
import re

from .. import llm
from ..schemas import DraftResult

SYSTEM = """You write a short, specific cold email from a job seeker to one person at a company.
You are given a numbered list of FACTS. Each fact is a verbatim quote from the resume (R...) or the job posting (P...).
Rules:
- Every sentence has a kind:
  - "about_me": says something about the sender. fact_id MUST be a resume fact (R...). Never cite a posting fact for a claim about the sender, even if the posting says the company wants it.
  - "about_job": says something about the role or company. fact_id MUST be a posting fact (P...). Write it about the company ("You are building..."), never as "I have..." or "I've...".
  - "ask": a question or polite line. fact_id is null; it must contain no figures and no claim about the sender's experience or skills.
- A sentence may only say what the quote it cites says. Never add a number, employer, skill, title or achievement that is not in that quote.
- If the resume has nothing relevant to the posting, say so honestly by expressing interest in the role in an "ask" sentence; do not stretch a resume line to match.
- 3 to 5 sentences in total, under 110 words. Plain, warm, no hype, no "I hope this finds you well".
- Use at least one resume fact and at least one posting fact.
- greeting is like "Hi Jane,". closing is like "Thanks for your time," (no name; the sender signs it).
- subject: under 12 words, mentions the job title."""

_NUM = re.compile(r"\d[\d,.]*")
_FIRST_PERSON = re.compile(r"\b(i|i've|i'm|i'd|i'll|my|me|we|our)\b", re.I)
# experience claims that an unsourced "ask" sentence must not smuggle in
_CLAIM = re.compile(
    r"\b(i've|i have|i had|i built|i led|i worked|i developed|i managed|i shipped|i designed|i wrote|i created|i delivered|"
    r"i launched|i operated|i run|my experience|my background|years of|experienced|expert|skilled)\b",
    re.I,
)
_WORDS = {
    "that", "this", "with", "from", "have", "your", "about", "would", "could", "their", "there", "which", "while", "been",
    "being", "into", "also", "than", "then", "them", "they", "were", "will", "what", "when", "where", "like", "more",
}


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9+#]{4,}", text.lower()) if w not in _WORDS}


def _supported(sentence: str, quote: str, need: float = 0.6) -> bool:
    """Most of the sentence's content words must come from the quote it cites (stems, so 'build' matches 'building')."""
    words = _stems(sentence)
    return not words or len(words & _stems(quote)) / len(words) >= need


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def candidate_facts(resume_text: str, posting_text: str, job_title: str, per_source: int = 12) -> list[dict]:
    """Verbatim lines from each source, favouring lines that overlap with the job."""
    stop = {"the", "and", "for", "with", "you", "our", "are", "will", "that", "this", "from", "have", "your"}
    job_tokens = {t for t in re.findall(r"[a-z0-9+#]{3,}", f"{job_title} {posting_text}".lower()) if t not in stop}

    def lines(text: str, lo: int, hi: int) -> list[str]:
        out = []
        for raw in re.split(r"\n+", text):
            line = raw.strip(" \t-•*·–—")
            if lo <= len(line) <= hi:
                out.append(line)
        return out

    def pick(candidates: list[str], prefix: str, other_tokens: set[str]) -> list[dict]:
        scored = []
        for c in candidates:
            toks = {t for t in re.findall(r"[a-z0-9+#]{3,}", c.lower()) if t not in stop}
            scored.append((len(toks & other_tokens), c))
        scored.sort(key=lambda x: -x[0])
        return [
            {"id": f"{prefix}{i + 1}", "source": "resume" if prefix == "R" else "posting", "quote": c}
            for i, (_, c) in enumerate(scored[:per_source])
        ]

    resume_tokens = {t for t in re.findall(r"[a-z0-9+#]{3,}", resume_text.lower()) if t not in stop}
    facts = pick(lines(resume_text, 30, 260), "R", job_tokens)
    facts += pick(lines(posting_text, 30, 260), "P", resume_tokens)
    return facts


def verify(draft: DraftResult, facts: list[dict], resume_text: str, posting_text: str) -> list[str]:
    """Return a list of problems. An empty list means every claim traces to a verbatim quote."""
    problems: list[str] = []
    by_id = {f["id"]: f for f in facts}
    sources = {"resume": _norm(resume_text), "posting": _norm(posting_text)}
    used_resume = used_posting = False
    if not draft.sentences:
        problems.append("The email has no sentences.")
    for s in draft.sentences:
        if s.kind == "ask" or s.fact_id is None:
            if s.kind != "ask":
                problems.append(f"A {s.kind} sentence must cite a fact: {s.text!r}")
            if _NUM.search(s.text):
                problems.append(f"Unsourced sentence contains a figure: {s.text!r}")
            if _CLAIM.search(s.text):
                problems.append(f"Unsourced sentence makes a claim about the sender's experience: {s.text!r}")
            continue
        fact = by_id.get(s.fact_id)
        if not fact:
            problems.append(f"Sentence cites unknown fact {s.fact_id}.")
            continue
        if s.kind == "about_me" and fact["source"] != "resume":
            problems.append(f"A claim about the sender cites a {fact['source']} fact ({s.fact_id}); it must cite the resume: {s.text!r}")
        if s.kind == "about_job" and fact["source"] != "posting":
            problems.append(f"A statement about the job cites a {fact['source']} fact ({s.fact_id}); it must cite the posting: {s.text!r}")
        if s.kind == "about_job" and _FIRST_PERSON.search(s.text):
            problems.append(f"A statement about the job speaks as the sender: {s.text!r}")
        if not _supported(s.text, fact["quote"]):
            problems.append(f"Sentence says more than {s.fact_id} does: {s.text!r}")
        if _norm(fact["quote"]) not in sources[fact["source"]]:
            problems.append(f"Fact {s.fact_id} is not a verbatim quote from the {fact['source']}.")
        quote_nums = {n.strip(".,") for n in _NUM.findall(fact["quote"])}
        for n in _NUM.findall(s.text):
            if n.strip(".,") not in quote_nums:
                problems.append(f"Sentence uses the figure {n!r}, which is not in {s.fact_id}.")
        used_resume |= fact["source"] == "resume"
        used_posting |= fact["source"] == "posting"
    if not used_resume:
        problems.append("No resume fact is used.")
    if not used_posting:
        problems.append("No posting fact is used.")
    return problems


def assemble(draft: DraftResult, facts: list[dict]) -> tuple[str, list[dict]]:
    by_id = {f["id"]: f for f in facts}
    body = draft.greeting.strip() + "\n\n" + " ".join(s.text.strip() for s in draft.sentences) + "\n\n" + draft.closing.strip()
    evidence = []
    for s in draft.sentences:
        if s.fact_id and s.fact_id in by_id:
            f = by_id[s.fact_id]
            evidence.append({"sentence": s.text.strip(), "fact_id": f["id"], "source": f["source"], "quote": f["quote"]})
    return body, evidence


def write(
    *,
    profile: dict,
    resume_text: str,
    job: dict,
    person: dict | None,
) -> dict:
    """Write, verify, and retry once with the problems fed back. Returns subject, body, evidence, problems."""
    facts = candidate_facts(resume_text, job["description"], job["title"])
    if not any(f["source"] == "resume" for f in facts) or not any(f["source"] == "posting" for f in facts):
        raise llm.LLMError("Not enough text in the resume or the posting to ground an email.")
    first = (person or {}).get("name", "").split(" ")[0] or "there"
    base = (
        f"RECIPIENT: {(person or {}).get('name', 'unknown')} ({(person or {}).get('title', '')}) at {job['company']}\n"
        f"JOB: {job['title']} ({job['location']})\n"
        f"SENDER: {profile.get('name', '')}\n"
        f"Greeting should use the first name: {first}.\n\n"
        f"FACTS:\n{json.dumps(facts, indent=1)}"
    )
    problems: list[str] = []
    draft: DraftResult | None = None
    for attempt in range(2):
        prompt = base if not problems else base + "\n\nYour previous draft was rejected for:\n- " + "\n- ".join(problems)
        draft = llm.structured_model(DraftResult, purpose="draft", system=SYSTEM, user=prompt, max_tokens=4000)
        problems = verify(draft, facts, resume_text, job["description"])
        if not problems:
            break
    assert draft is not None
    body, evidence = assemble(draft, facts)
    return {"subject": draft.subject.strip(), "body": body, "evidence": evidence, "problems": problems}
