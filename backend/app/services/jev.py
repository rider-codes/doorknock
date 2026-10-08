"""Jev (TypeSafe AI): a fast classifier that answers typed yes/no questions with a probability instead of writing text.
Used as a relevance gate: before the scoring model sees a job, Jev says how close a match it is for this person.
It is reached through OpenRouter (same key as the other models, no waitlist) or directly through TypeSafe."""
import time

import httpx

from .. import config

# Three narrow yes/no questions, asked in one call (Jev answers them in parallel and in isolation).
QUESTIONS = {
    "role": {
        "type": "noul",
        "instructions": "Is this job the kind of role the candidate says they are looking for (their target roles and keywords)?",
        "criteria": {
            "true": "The title and day-to-day work match one of the candidate's target roles, or something very close to it.",
            "false": "The role is in a different field or function from what the candidate is looking for.",
        },
    },
    "skills": {
        "type": "noul",
        "instructions": "Does this job mainly need skills and technologies the candidate already has?",
        "criteria": {
            "true": "Most of the required technologies and skills appear in the candidate's skills or experience.",
            "false": "Key required technologies or skills are missing from the candidate's background.",
        },
    },
    "level": {
        "type": "noul",
        "instructions": "Is the seniority and experience this job asks for appropriate for the candidate?",
        "criteria": {
            "true": "The level and years of experience asked are within reach for the candidate.",
            "false": "The job asks for clearly more seniority or experience than the candidate has.",
        },
    },
}
# Combined in code (not by the model): the role matters most.
WEIGHTS = {"role": 0.5, "skills": 0.3, "level": 0.2}


class JevError(RuntimeError):
    pass


class JevCreditError(JevError):
    """The account is out of credit. Unlike a rejected key this is not a setup mistake, so a search can carry on without Jev."""


class JevAuthError(JevError):
    """The key is missing or rejected, or the account is out of credit. Retrying other jobs would fail the same way."""


def configured() -> bool:
    return config.jev_backend() is not None


def candidate_state(profile: dict, brief: dict) -> dict:
    return {
        "headline": profile.get("headline", ""),
        "seniority": profile.get("seniority", ""),
        "years_experience": profile.get("years_experience", 0),
        "skills": (profile.get("skills") or [])[:30],
        "recent_roles": [f"{e.get('title', '')} at {e.get('company', '')}" for e in (profile.get("experience") or [])[:3]],
        "looking_for": {
            "roles": brief.get("roles", []),
            "keywords": brief.get("keywords", []),
            "level": brief.get("level", ""),
        },
    }


def combine(nouls: dict[str, float]) -> float:
    return round(sum(WEIGHTS[k] * float(nouls.get(k, 0.5)) for k in WEIGHTS), 3)


def assess(candidate: dict, job: dict) -> dict:
    """One call, three questions. Returns {'relevance': 0-1, 'parts': {'role':..,'skills':..,'level':..}}."""
    backend = config.jev_backend()
    if backend is None:
        raise JevAuthError("No key for Jev. Set OPENROUTER_API_KEY (preferred) or TYPESAFE_API_KEY.")
    name, endpoint, key, default_model = backend
    body = {
        "model": config.env("JEV_MODEL", default_model),
        "state": {"candidate": candidate, "job": {k: (v[:3000] if isinstance(v, str) else v) for k, v in job.items()}},
        "questions": QUESTIONS,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if name == "openrouter":
        headers.update({"HTTP-Referer": "http://localhost:5173", "X-Title": "Doorknock"})
    key_name = "OPENROUTER_API_KEY" if name == "openrouter" else "TYPESAFE_API_KEY"
    for attempt in range(3):
        try:
            resp = httpx.post(endpoint, json=body, headers=headers, timeout=30)
        except httpx.HTTPError as exc:
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise JevError(f"Network error talking to Jev: {type(exc).__name__}") from exc
        if resp.status_code in (401, 403):
            raise JevAuthError(f"Jev rejected the API key. Check {key_name}.")
        if resp.status_code == 402:
            raise JevCreditError("Out of credit for Jev. Add credit to your OpenRouter account.")
        if resp.status_code in (429, 500, 524, 529) and attempt < 2:
            time.sleep(1.5 * (attempt + 1))  # rate limited, overloaded or timed out: wait and try again
            continue
        if resp.status_code >= 400:
            raise JevError(f"Jev returned HTTP {resp.status_code}")
        data = resp.json()
        answers = data.get("answers") or {}
        try:
            parts = {k: float(answers[k]["noul"]) for k in QUESTIONS}
        except (KeyError, TypeError, ValueError) as exc:
            raise JevError("Jev's answer was missing an expected field.") from exc
        usage = data.get("usage") or {}
        return {
            "relevance": combine(parts),
            "parts": parts,
            "tokens": usage.get("input_tokens", 0),
            "cost": float(usage.get("cost") or 0),  # USD, reported by OpenRouter
        }
    raise JevError("Jev did not answer.")
