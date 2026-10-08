"""LLM scores each job on five signals; the total is added up here, never taken from the model."""
import json

from .. import llm
from ..schemas import SIGNAL_MAX, ScoreResult

SYSTEM = f"""You score how well one job fits one person. Be strict and specific.
Score five signals as integers, each from 0 up to its maximum:
- role (max {SIGNAL_MAX['role']}): does the job's day-to-day work match the roles in the brief?
- profile (max {SIGNAL_MAX['profile']}): does the person's experience and projects match what this job needs?
- skills (max {SIGNAL_MAX['skills']}): how many of the posting's required skills appear in the profile?
- location (max {SIGNAL_MAX['location']}): does the location or remote policy fit the brief?
- seniority (max {SIGNAL_MAX['seniority']}): does the level asked match the person's level and years?
Each signal needs ONE short reason (under 12 words) that names concrete evidence from the posting or the profile.
Never credit a skill that is not in the profile. Do not add a total."""


def clamp(result: ScoreResult) -> dict:
    """Clamp every signal to its weight and sum the total in code."""
    signals = {}
    for name, maximum in SIGNAL_MAX.items():
        sig = getattr(result, name)
        signals[name] = {"score": max(0, min(int(sig.score), maximum)), "max": maximum, "reason": sig.reason.strip()}
    total = sum(s["score"] for s in signals.values())
    return {"total": total, "signals": signals}


def verdict(total: int) -> str:
    if total >= 80:
        return "Strong fit"
    if total >= 65:
        return "Good fit"
    return "Stretch"


def score_job(profile: dict, brief: dict, title: str, company: str, location: str, description: str) -> dict:
    user = (
        f"PERSON PROFILE:\n{json.dumps(profile)[:7000]}\n\n"
        f"WHAT THEY WANT (brief):\n{json.dumps(brief)}\n\n"
        f"JOB:\nTitle: {title}\nCompany: {company}\nLocation: {location}\n\n{description[:6000]}"
    )
    result = llm.structured_model(ScoreResult, purpose="score", system=SYSTEM, user=user, max_tokens=4000)  # room for models that think before they answer
    return clamp(result)
