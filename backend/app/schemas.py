"""Structured shapes the LLM must return. They double as the JSON schemas given to the model."""
from typing import Literal

from pydantic import BaseModel, Field

Seniority = Literal["intern", "entry", "mid", "senior", "staff"]
Level = Literal["intern", "entry", "mid", "senior"]
JobType = Literal["full_time", "intern", "contract", "any"]

# Signal weights. The model scores each signal; the total is summed in code.
SIGNAL_MAX = {"role": 25, "profile": 30, "skills": 20, "location": 15, "seniority": 10}


class Experience(BaseModel):
    company: str = ""
    title: str = ""
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str = ""
    description: str = ""
    tech: list[str] = Field(default_factory=list)


class ProfileData(BaseModel):
    name: str = ""
    headline: str = ""
    seniority: Seniority = "entry"
    years_experience: float = 0
    skills: list[str] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)


class BriefData(BaseModel):
    roles: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    level: Level = "entry"
    job_type: JobType = "full_time"
    keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    title_keywords: list[str] = Field(default_factory=list)  # words a matching posting's title contains
    avoid_titles: list[str] = Field(default_factory=list)  # title words that mean it is not the wanted kind of job


class BriefReply(BaseModel):
    brief: BriefData
    reply: str


class Signal(BaseModel):
    score: int
    reason: str


class ScoreResult(BaseModel):
    role: Signal
    profile: Signal
    skills: Signal
    location: Signal
    seniority: Signal


class RankedPerson(BaseModel):
    index: int
    relevance: int = Field(ge=0, le=100)
    role_type: Literal["recruiter", "hiring_manager", "teammate", "skip"]
    why: str


class PeopleRanking(BaseModel):
    ranked: list[RankedPerson]


class DraftSentence(BaseModel):
    text: str
    # about_me = a claim about the sender (must cite a resume fact); about_job = about the role or company (posting fact);
    # ask = a question or polite line (no fact, no claims)
    kind: Literal["about_me", "about_job", "ask"]
    fact_id: str | None = None


class DraftResult(BaseModel):
    subject: str
    greeting: str
    sentences: list[DraftSentence]
    closing: str
