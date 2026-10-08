from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, llm, pipeline, refresh, store, usage
from .db import get_session, init_db, session_scope
from .models import Company, Draft, Job, LlmCall, Person, Run, Score
from .schemas import BriefData, ProfileData
from .services import brief_agent, gmail, jev, outreach, people, resume_parser, scorer, sources


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with session_scope() as s:
        store.seed_companies(s)
        # a run is only ever worked on by this process, so one still marked running died with the last one
        for run in s.execute(select(Run).where(Run.status == "running")).scalars():
            run.status = "error"
            run.detail = {**(run.detail or {}), "error": "The app was restarted while this search was running. Start it again."}
    refresh.start()
    yield


app = FastAPI(title="Doorknock", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _upstream_error(_, exc: Exception):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


for _exc_type in (llm.LLMError, people.PeopleError, gmail.GmailError):
    app.add_exception_handler(_exc_type, _upstream_error)


# ---- serialisation ------------------------------------------------------------
def _current_score(job: Job, profile_version: int, brief_version: int) -> Score | None:
    return pipeline._current_score(job, profile_version, brief_version)


def job_summary(job: Job, pv: int, bv: int) -> dict:
    sc = _current_score(job, pv, bv)
    network = max((p.relevance for p in job.people), default=0)  # how good the best known contact is; 0 until someone is found
    return {
        "id": job.id,
        "title": job.title,
        "network": network,
        "posted_key": pipeline.posted_key(job),
        "source": job.external_id.split("-")[0] if job.company.ats == "aggregator" else job.company.ats,
        "aggregated": job.company.ats == "aggregator",
        "last_seen": job.last_seen.isoformat() if job.last_seen else "",
        "people_count": len(job.people),
        "signals": sc.signals if sc else None,
        "opportunity": round(0.65 * sc.total + 0.35 * network) if sc else None,
        "company": job.company.name,
        "company_id": job.company_id,
        "domain": job.company.domain,
        "location": job.location,
        "url": job.url,
        "posted_at": job.posted_at,
        "status": job.status,
        "filter_reason": job.filter_reason,
        "sim": job.sim,
        "relevance": job.relevance,
        "score": sc.total if sc else None,
        "verdict": scorer.verdict(sc.total) if sc else None,
        "has_people": bool(job.people),
        "has_draft": bool(job.drafts),
    }


def person_dict(p: Person) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "title": p.title,
        "role_type": p.role_type,
        "email": p.email,
        "email_status": p.email_status,
        "relevance": p.relevance,
        "why": p.why,
        "source": p.source,
    }


def draft_dict(d: Draft, to: str = "") -> dict:
    return {
        "id": d.id,
        "job_id": d.job_id,
        "person_id": d.person_id,
        "to": to,
        "subject": d.subject,
        "body": d.body,
        "evidence": d.evidence,
        "problems": d.problems,
        "status": d.status,
        "in_gmail": bool(d.gmail_draft_id),
    }


def _versions(s: Session) -> tuple[int, int]:
    profile = store.latest_profile(s)
    return (profile.version if profile else 0), store.latest_brief(s).version


# ---- state --------------------------------------------------------------------
@app.get("/api/state")
def get_state(s: Session = Depends(get_session)):
    profile, brief = store.latest_profile(s), store.latest_brief(s)
    counts = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    run = s.execute(select(Run).order_by(Run.id.desc()).limit(1)).scalar_one_or_none()
    return {
        "profile": {"filename": profile.filename, "version": profile.version, "data": profile.data} if profile else None,
        "brief": {"version": brief.version, "data": brief.data, "history": brief.history},
        "counts": {
            "found": sum(v for k, v in counts.items() if k != "closed"),
            "filtered": counts.get("filtered", 0) + counts.get("irrelevant", 0),
            "waiting": counts.get("ranked", 0),
            "scored": counts.get("scored", 0) + counts.get("drafted", 0),
            "drafts": s.execute(select(func.count(Draft.id))).scalar_one(),
        },
        "setup": {
            "llm": config.llm_ready(),
            "jev": jev.configured(),
            "people_provider": people.provider_name(),
            "aggregator": bool(config.env("ADZUNA_APP_ID") and config.env("ADZUNA_APP_KEY")) or bool(config.env("JOOBLE_API_KEY")),
            "gmail_client_secret": gmail.has_client_secret(),
            "gmail_connected": gmail.is_connected(),
        },
        "allowances": _allowances(s, run),
        "freshness": {"last_refreshed": (lambda t: t.isoformat() if t else None)(refresh.last_refreshed(s)), "auto_hours": refresh.hours()},
        "run": _run_dict(run),
    }


def _allowances(s: Session, run: Run | None) -> list[dict]:
    """What is limited, and how much is left, so the screen can show it before an action spends it."""
    out: list[dict] = []
    if people.provider_name() == "hunter":
        q = people.hunter_quota()
        if q:
            out.append({"key": "hunter", "label": "Contact tokens", "detail": "1 per Find contacts", "left": max(0, q["available"] - q["used"]),
                        "limit": q["available"], "unit": "tokens", "period": "this month"})
    if config.env("JOOBLE_API_KEY"):
        _, spent = usage.used("jooble")
        cap = int(config.env("JOOBLE_TOTAL_LIMIT", "480"))
        out.append({"key": "jooble", "label": "Jooble job feed", "detail": "key allows 500 requests in all", "left": max(0, cap - spent),
                    "limit": cap, "unit": "requests", "period": "in total"})
    if any(m.endswith(":free") for m in config.model_chain("score")):
        cap = int(config.env("FREE_MODEL_DAILY_CAP", "50"))
        day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        spent = s.execute(select(func.count(LlmCall.id)).where(LlmCall.purpose == "score", LlmCall.created_at >= day)).scalar_one()
        limited = any("429" in e for e in ((run.detail or {}).get("errors") or [])) if run else False
        out.append({"key": "scoring", "label": "Scoring jobs", "detail": "free models" + ("; rate-limited in the last search" if limited else ""),
                    "left": max(0, cap - spent), "limit": cap, "unit": "calls", "period": "today"})
    return out


def _run_dict(run: Run | None) -> dict | None:
    if run is None:
        return None
    return {"id": run.id, "status": run.status, "stage": run.stage, "detail": run.detail or {}}


# ---- resume + profile ---------------------------------------------------------
MAX_UPLOAD = 8 * 1024 * 1024


@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...), s: Session = Depends(get_session)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "That file is over 8 MB.")
    try:
        text = resume_parser.extract_text(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    parsed = resume_parser.parse_profile(text)
    profile = store.save_profile(s, file.filename or "resume", text, parsed.model_dump())
    return {"filename": profile.filename, "version": profile.version, "data": profile.data}


class ProfileBody(BaseModel):
    data: dict


@app.put("/api/profile")
def edit_profile(body: ProfileBody, s: Session = Depends(get_session)):
    try:
        data = ProfileData.model_validate(body.data).model_dump()
        profile = store.update_profile_data(s, data)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"filename": profile.filename, "version": profile.version, "data": profile.data}


# ---- brief --------------------------------------------------------------------
class ChatBody(BaseModel):
    message: str


@app.post("/api/brief/chat")
def brief_chat(body: ChatBody, s: Session = Depends(get_session)):
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Say something about the job you want.")
    brief, profile = store.latest_brief(s), store.latest_profile(s)
    s.commit()  # release the write lock before the AI call, which logs its own usage row from another connection
    result = brief_agent.chat(brief.data, brief.history, message, profile.data if profile else None)
    history = [*brief.history, {"role": "user", "content": message}, {"role": "assistant", "content": result.reply}]
    saved = store.save_brief(s, result.brief.model_dump(), history)
    return {"reply": result.reply, "brief": {"version": saved.version, "data": saved.data, "history": saved.history}}


class BriefBody(BaseModel):
    data: dict


@app.put("/api/brief")
def edit_brief(body: BriefBody, s: Session = Depends(get_session)):
    try:
        data = BriefData.model_validate(body.data).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    saved = store.save_brief(s, data, store.latest_brief(s).history)
    return {"version": saved.version, "data": saved.data, "history": saved.history}


# ---- companies ----------------------------------------------------------------
class CompanyBody(BaseModel):
    url: str = ""
    name: str = ""
    ats: str = ""
    slug: str = ""
    domain: str = ""


@app.get("/api/companies")
def list_companies(s: Session = Depends(get_session)):
    rows = s.execute(select(Company).where(Company.ats != "aggregator").order_by(Company.name)).scalars().all()
    return [
        {"id": c.id, "name": c.name, "ats": c.ats, "slug": c.slug, "domain": c.domain, "enabled": c.enabled, "last_error": c.last_error}
        for c in rows
    ]


@app.post("/api/companies")
def add_company(body: CompanyBody, s: Session = Depends(get_session)):
    ats, slug = body.ats, body.slug
    if body.url:
        parsed = sources.parse_board_url(body.url)
        if not parsed:
            raise HTTPException(422, "Paste a job board link from Greenhouse, Lever, Ashby, SmartRecruiters, Workable or Workday, e.g. https://boards.greenhouse.io/stripe")
        ats, slug = parsed
    if ats not in sources.ADAPTERS or not slug:
        raise HTTPException(422, "Give a job board link, or an ats (greenhouse, lever, ashby, smartrecruiters, workable, workday) and slug.")
    exists = s.execute(select(Company).where(Company.ats == ats, Company.slug == slug)).scalar_one_or_none()
    if exists:
        return {"id": exists.id, "name": exists.name, "duplicate": True}
    label = slug.split("/")[0] if ats == "workday" else slug
    company = Company(name=body.name or label.replace("-", " ").title(), ats=ats, slug=slug, domain=body.domain)
    s.add(company)
    s.flush()
    return {"id": company.id, "name": company.name, "duplicate": False}


class DomainBody(BaseModel):
    domain: str


@app.patch("/api/companies/{company_id}")
def set_company_domain(company_id: int, body: DomainBody, s: Session = Depends(get_session)):
    company = s.get(Company, company_id)
    if not company:
        raise HTTPException(404, "No such company.")
    domain = body.domain.strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]
    if domain and "." not in domain:
        raise HTTPException(422, "Enter a website domain like stripe.com.")
    company.domain = domain
    return {"id": company.id, "domain": company.domain}


@app.delete("/api/companies/{company_id}")
def remove_company(company_id: int, s: Session = Depends(get_session)):
    company = s.get(Company, company_id)
    if not company:
        raise HTTPException(404, "No such company.")
    company.enabled = False
    return {"ok": True}


# ---- runs ---------------------------------------------------------------------
class RunBody(BaseModel):
    stages: list[str] = ["fetch", "filter", "hydrate", "rank", "relevance", "score"]
    score_limit: int = 25


@app.post("/api/runs")
def start_run(body: RunBody, s: Session = Depends(get_session)):
    stages = [x for x in body.stages if x in pipeline.STAGES]
    if not stages:
        raise HTTPException(422, "No valid stages.")
    if not store.latest_profile(s):
        raise HTTPException(422, "Upload your resume first.")
    s.commit()  # release the write lock before the worker thread starts
    try:
        run_id = pipeline.run_pipeline(stages, max(1, min(body.score_limit, 100)))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id}


@app.get("/api/runs/latest")
def latest_run(s: Session = Depends(get_session)):
    run = s.execute(select(Run).order_by(Run.id.desc()).limit(1)).scalar_one_or_none()
    return _run_dict(run)


# ---- jobs ---------------------------------------------------------------------
@app.get("/api/jobs")
def list_jobs(view: str = "scored", limit: int = 100, sort: str = "newest", s: Session = Depends(get_session)):
    pv, bv = _versions(s)
    if view == "filtered":
        rows = s.execute(
            select(Job).where(Job.status.in_(["filtered", "irrelevant"])).order_by(Job.id.desc()).limit(limit)
        ).scalars().all()
    elif view == "waiting":
        rows = s.execute(select(Job).where(Job.status == "ranked").order_by(Job.sim.desc())).scalars().all()
        if sort == "newest":
            rows = sorted(rows, key=pipeline.posted_key, reverse=True)
        rows = rows[:limit]
    else:
        rows = s.execute(select(Job).where(Job.status.in_(["scored", "drafted"]))).scalars().all()
    items = [job_summary(j, pv, bv) for j in rows]
    if view == "scored":
        by_best = sorted(items, key=lambda j: (j["score"] is None, -(j["opportunity"] or 0), -(j["score"] or 0)))
        items = by_best if sort == "best" else sorted(by_best, key=lambda j: j["posted_key"], reverse=True)  # stable: best first within a day
        items = items[:limit]
    return items


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: int, s: Session = Depends(get_session)):
    job = s.get(Job, job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    pv, bv = _versions(s)
    sc = _current_score(job, pv, bv)
    ppl = sorted(job.people, key=lambda p: -p.relevance)
    drafts = sorted(job.drafts, key=lambda d: -d.id)
    by_person = {p.id: p.email for p in ppl}
    return {
        **job_summary(job, pv, bv),
        "description": job.description,
        "people": [person_dict(p) for p in ppl],
        "draft": draft_dict(drafts[0], by_person.get(drafts[0].person_id, "")) if drafts else None,
    }


@app.post("/api/jobs/{job_id}/dismiss")
def dismiss(job_id: int, s: Session = Depends(get_session)):
    job = s.get(Job, job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    job.status = "dismissed"
    return {"ok": True}


@app.post("/api/jobs/{job_id}/people")
def find_people(job_id: int, s: Session = Depends(get_session)):
    job = s.get(Job, job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    domain = job.company.domain
    if not domain:
        raise HTTPException(422, f"Add a website domain for {job.company.name} first (e.g. stripe.com).")
    found = people.find(
        domain,
        job.title,
        {"title": job.title, "company": job.company.name, "location": job.location, "description": job.description},
    )
    people.invalidate_quota()  # a search was spent: read the new count next time
    for old in list(job.people):
        if old.source.startswith("You added"):
            continue  # people added by hand survive a new search
        if not any(d.person_id == old.id for d in job.drafts):
            s.delete(old)
    s.flush()
    for row in found:
        s.add(Person(job_id=job.id, **row))
    s.flush()
    s.refresh(job)
    return [person_dict(p) for p in sorted(job.people, key=lambda p: -p.relevance)]


class ManualPerson(BaseModel):
    name: str
    title: str = ""
    email: str = ""


@app.post("/api/jobs/{job_id}/people/manual")
def add_person(job_id: int, body: ManualPerson, s: Session = Depends(get_session)):
    job = s.get(Job, job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    row = people.add_manual(body.name, body.title, body.email, job.company.domain or "", job.title)
    person = Person(job_id=job.id, **row)
    s.add(person)
    s.flush()
    return person_dict(person)


class DraftBody(BaseModel):
    person_id: int | None = None


@app.post("/api/jobs/{job_id}/draft")
def write_draft(job_id: int, body: DraftBody, s: Session = Depends(get_session)):
    job = s.get(Job, job_id)
    profile = store.latest_profile(s)
    if not job:
        raise HTTPException(404, "No such job.")
    if not profile:
        raise HTTPException(422, "Upload your resume first.")
    person = s.get(Person, body.person_id) if body.person_id else None
    if body.person_id and (person is None or person.job_id != job.id):
        raise HTTPException(404, "No such person for this job.")
    result = outreach.write(
        profile=profile.data,
        resume_text=profile.raw_text,
        job={"title": job.title, "company": job.company.name, "location": job.location, "description": job.description},
        person=person_dict(person) if person else None,
    )
    draft = Draft(
        job_id=job.id,
        person_id=person.id if person else None,
        subject=result["subject"],
        body=result["body"],
        evidence=result["evidence"],
        problems=result["problems"],
        status="needs_review" if result["problems"] else "verified",
    )
    s.add(draft)
    job.status = "drafted"
    s.flush()
    return draft_dict(draft, person.email if person else "")


class DraftEdit(BaseModel):
    subject: str
    body: str


@app.put("/api/drafts/{draft_id}")
def edit_draft(draft_id: int, body: DraftEdit, s: Session = Depends(get_session)):
    draft = s.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "No such draft.")
    draft.subject, draft.body = body.subject, body.body
    draft.status = "needs_review"  # hand edits are no longer checked against quotes
    note = "Edited by hand after verification."
    if note not in draft.problems:
        draft.problems = [*draft.problems, note]
    person = s.get(Person, draft.person_id) if draft.person_id else None
    return draft_dict(draft, person.email if person else "")


@app.post("/api/gmail/connect")
def gmail_connect():
    gmail.connect()  # blocks until the user finishes the Google consent screen
    return {"connected": gmail.is_connected()}


@app.post("/api/drafts/{draft_id}/gmail")
def save_to_gmail(draft_id: int, s: Session = Depends(get_session)):
    draft = s.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "No such draft.")
    person = s.get(Person, draft.person_id) if draft.person_id else None
    to = person.email if person and not person.email.endswith(".invalid") else ""
    draft.gmail_draft_id = gmail.create_draft(to, draft.subject, draft.body)
    draft.status = "in_gmail" if draft.status != "needs_review" else "needs_review"
    return {"gmail_draft_id": draft.gmail_draft_id, "to": to}


# ---- serve the built frontend (production) ------------------------------------
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (_DIST / path).resolve()
        if path and candidate.is_file() and _DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")

