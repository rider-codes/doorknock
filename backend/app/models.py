from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profile"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    filename: Mapped[str] = mapped_column(String, default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Brief(Base):
    __tablename__ = "brief"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    history: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Company(Base):
    __tablename__ = "company"
    __table_args__ = (UniqueConstraint("ats", "slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    ats: Mapped[str] = mapped_column(String)  # greenhouse | lever | ashby
    slug: Mapped[str] = mapped_column(String)
    domain: Mapped[str] = mapped_column(String, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str] = mapped_column(String, default="")
    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (UniqueConstraint("company_id", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"))
    external_id: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String, default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String, default="")
    posted_at: Mapped[str] = mapped_column(String, default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # new | filtered | ranked | scored | drafted | dismissed
    status: Mapped[str] = mapped_column(String, default="new")
    filter_reason: Mapped[str] = mapped_column(String, default="")
    sim: Mapped[float] = mapped_column(Float, default=0.0)
    emb: Mapped[list | None] = mapped_column(JSON, nullable=True)
    emb_backend: Mapped[str] = mapped_column(String, default="")
    detail_ref: Mapped[str] = mapped_column(String, default="")
    needs_detail: Mapped[bool] = mapped_column(Boolean, default=False)
    # Jev's 0-1 relevance for the profile/brief versions in `rel_versions` ("profile:brief"), with the three part scores
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rel_versions: Mapped[str] = mapped_column(String, default="")
    company: Mapped[Company] = relationship(back_populates="jobs")
    scores: Mapped[list["Score"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    people: Mapped[list["Person"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    drafts: Mapped[list["Draft"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Score(Base):
    __tablename__ = "score"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"))
    profile_version: Mapped[int] = mapped_column(Integer)
    brief_version: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    job: Mapped[Job] = relationship(back_populates="scores")


class Person(Base):
    __tablename__ = "person"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"))
    name: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    role_type: Mapped[str] = mapped_column(String, default="teammate")  # recruiter | hiring_manager | teammate
    email: Mapped[str] = mapped_column(String, default="")
    email_status: Mapped[str] = mapped_column(String, default="unknown")  # verified | risky | unknown
    relevance: Mapped[int] = mapped_column(Integer, default=0)
    why: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="")
    job: Mapped[Job] = relationship(back_populates="people")


class Draft(Base):
    __tablename__ = "draft"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"))
    person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    problems: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="verified")  # verified | needs_review | in_gmail
    gmail_draft_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    job: Mapped[Job] = relationship(back_populates="drafts")


class Run(Base):
    __tablename__ = "run"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String, default="running")  # running | done | error
    stage: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LlmCall(Base):
    __tablename__ = "llm_call"
    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
