"""Small helpers for the single-user data: latest profile, latest brief, seeded companies."""
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Brief, Company, Profile
from .schemas import BriefData

SEED = Path(__file__).parent / "data" / "seed_companies.json"


def latest_profile(s: Session) -> Profile | None:
    return s.execute(select(Profile).order_by(Profile.id.desc()).limit(1)).scalar_one_or_none()


def latest_brief(s: Session) -> Brief:
    brief = s.execute(select(Brief).order_by(Brief.id.desc()).limit(1)).scalar_one_or_none()
    if brief is None:
        brief = Brief(version=1, data=BriefData().model_dump(), history=[])
        s.add(brief)
        s.flush()
    return brief


def save_profile(s: Session, filename: str, raw_text: str, data: dict) -> Profile:
    prev = latest_profile(s)
    profile = Profile(version=(prev.version + 1) if prev else 1, filename=filename, raw_text=raw_text, data=data)
    s.add(profile)
    s.flush()
    return profile


def update_profile_data(s: Session, data: dict) -> Profile:
    """User edits to the parsed profile bump the version, so scores are marked stale."""
    prev = latest_profile(s)
    if prev is None:
        raise ValueError("Upload a resume first.")
    profile = Profile(version=prev.version + 1, filename=prev.filename, raw_text=prev.raw_text, data=data)
    s.add(profile)
    s.flush()
    return profile


def save_brief(s: Session, data: dict, history: list) -> Brief:
    prev = latest_brief(s)
    if prev.data == data:  # nothing changed: do not mark every score stale
        prev.history = history
        return prev
    brief = Brief(version=prev.version + 1, data=data, history=history)
    s.add(brief)
    s.flush()
    return brief


def seed_companies(s: Session) -> None:
    """Add any starter company that is not there yet (so new job systems get their examples on upgrade)."""
    have = {(c.ats, c.slug) for c in s.execute(select(Company)).scalars()}
    for row in json.loads(SEED.read_text(encoding="utf-8")):
        if (row["ats"], row["slug"]) not in have:
            s.add(Company(**row))
