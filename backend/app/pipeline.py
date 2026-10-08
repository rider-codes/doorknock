"""Stages: fetch -> filter -> hydrate -> rank -> relevance -> score. Each stage is idempotent and re-runnable on its own."""
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, db, demo, llm, store, usage
from .db import session_scope
from .models import Company, Draft, Job, Run, Score
from .services import filters, jev, portals, ranker, scorer, sources

log = logging.getLogger("doorknock.pipeline")
STAGES = ["fetch", "filter", "hydrate", "rank", "relevance", "score"]
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(workspace: str) -> threading.Lock:
    """One search at a time per workspace (on a public site, visitors do not block each other)."""
    with _locks_guard:
        return _locks.setdefault(workspace, threading.Lock())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# These systems list every opening on every call, so a job missing from the list has been taken down. The others return a
# capped or searched slice, so there a job is only treated as gone once it has not been seen for STALE_DAYS.
COMPLETE_LISTS = {"greenhouse", "lever", "ashby"}
STALE_DAYS = 21
RECENT_DAYS = 14


def posted_key(job: Job) -> str:
    """The date a job went up (or, when the board does not say, the day we first saw it), as YYYY-MM-DD."""
    return (job.posted_at or "")[:10] or (job.first_seen.date().isoformat() if job.first_seen else "")


def _current_score(job: Job, profile_version: int, brief_version: int) -> Score | None:
    for sc in sorted(job.scores, key=lambda x: x.id, reverse=True):
        if sc.profile_version == profile_version and sc.brief_version == brief_version:
            return sc
    return None


# ---- fetch --------------------------------------------------------------------
def search_hints(brief: dict) -> dict:
    """What the brief tells a job system to narrow its own search: your roles and countries."""
    return {"countries": brief.get("countries", []), "queries": [r for r in brief.get("roles", []) if r.strip()]}


def search_queries(brief: dict) -> list[str]:
    """What to type into a search box: the roles, then their best synonyms, then skills."""
    out = []
    for q in [*brief.get("roles", []), *brief.get("title_keywords", [])[:3], *brief.get("keywords", [])[:2]]:
        if q.strip() and q.strip().lower() not in {x.lower() for x in out}:
            out.append(q.strip())
    return out


def fetch_stage(s: Session, progress) -> dict:
    companies = s.execute(select(Company).where(Company.enabled.is_(True))).scalars().all()
    hints = search_hints(store.latest_brief(s).data)
    results: dict[int, tuple[list[sources.RawJob] | None, str]] = {}

    def work(c: Company):
        try:
            return c.id, sources.fetch(c.ats, c.slug, hints), ""
        except sources.Paused as exc:  # the board asked us to wait; try again next search, and do not call it a problem
            return c.id, None, f"paused: {exc}"
        except Exception as exc:  # one broken board must not stop the run
            return c.id, None, f"{type(exc).__name__}: {exc}"[:200]

    with ThreadPoolExecutor(max_workers=8) as pool:
        for cid, jobs, err in pool.map(db.in_context(work), companies):
            results[cid] = (jobs, err)
    found = new = 0
    errors = []
    for c in companies:
        jobs, err = results[c.id]
        c.last_error = err
        if jobs is None:
            if not err.startswith("paused:"):
                errors.append(f"{c.name}: {err}")
            continue
        existing = {j.external_id: j for j in s.execute(select(Job).where(Job.company_id == c.id)).scalars()}
        listed = {r.external_id for r in jobs}
        for ext, old in existing.items():
            if old.status in ("dismissed",) or old.drafts:
                continue
            if ext in listed and old.status == "closed":
                old.status, old.filter_reason = "new", ""  # it is back on the board
            elif ext not in listed and c.ats in COMPLETE_LISTS and old.status != "closed":
                old.status, old.filter_reason = "closed", "No longer on the employer's job board"
        for raw in jobs:
            found += 1
            job = existing.get(raw.external_id)
            if job is None:
                s.add(
                    Job(
                        company_id=c.id,
                        external_id=raw.external_id,
                        title=raw.title,
                        location=raw.location,
                        remote=raw.remote,
                        description=raw.description,
                        url=raw.url,
                        posted_at=raw.posted_at,
                        detail_ref=raw.detail_ref,
                        needs_detail=raw.needs_detail,
                    )
                )
                new += 1
            else:
                job.title, job.remote, job.url, job.last_seen = raw.title, raw.remote, raw.url, _now()
                if not job.needs_detail:  # text already fetched earlier: keep it
                    job.location = raw.location
                    if raw.description:
                        job.description = raw.description
    _close_stale(s)
    agg_found, agg_new, agg_error = _aggregator(s, hints, store.latest_brief(s).data, store.latest_profile(s))
    if agg_error:
        errors.append(agg_error)
    found, new = found + agg_found, new + agg_new
    progress(fetched=found, new=new, boards=len(companies), board_errors=errors, fetched_at=_now().isoformat())
    return {"fetched": found, "new": new, "errors": errors}


def _close_stale(s: Session) -> None:
    """Close jobs no search has returned for STALE_DAYS (and that have no draft), so old postings stop showing up."""
    cutoff = _now() - timedelta(days=STALE_DAYS)
    drafted = select(Draft.job_id)
    for job in s.execute(select(Job).where(Job.status.notin_(["dismissed", "closed"]), Job.last_seen < cutoff, Job.id.notin_(drafted))).scalars():
        job.status, job.filter_reason = "closed", f"Not seen on any board for {STALE_DAYS} days"


_NCR_PLACES = ["Noida", "Delhi", "Gurgaon"]


def _aggregator(s: Session, hints: dict, brief: dict, profile) -> tuple[int, int, str]:
    """Jobs from aggregators (Adzuna, Jooble), filed under the employer that posted each one. Each is skipped without its key."""
    (adz_id, adz_key), jooble_key = config.adzuna_keys(), config.jooble_key()
    if config.public_mode() and not (jooble_key or (adz_id and adz_key)):
        return 0, 0, ""  # a visitor with no feed key of their own gets employer boards only
    cities = [c for c in brief.get("cities", []) if c.strip()]
    places = []
    for c in cities:
        places += _NCR_PLACES if c.strip().lower() in filters._NCR else [c]  # one search covers the NCR cities
    queries = search_queries(brief) or ["software engineer", "software developer"]
    raw: list[sources.RawJob] = []
    problems = []
    if adz_id and adz_key:
        try:
            raw += sources.fetch_adzuna(adz_id, adz_key, queries[:3], list(dict.fromkeys(places))[:10], pages=2)
        except Exception as exc:
            problems.append(f"Adzuna: {type(exc).__name__}: {exc}"[:200])
    if jooble_key:
        daily, total = int(config.env("JOOBLE_DAILY_REQUESTS", "40")), int(config.env("JOOBLE_TOTAL_LIMIT", "480"))
        budget = f"jooble-{config.key_id(jooble_key)}" if config.public_mode() else "jooble"  # one budget per key
        try:
            raw += sources.fetch_jooble(
                jooble_key, queries[:3], (brief.get("countries") or ["India"])[0], 2,
                allow=lambda: usage.allow(budget, daily, total), spend=lambda: usage.spend(budget),
            )
        except Exception as exc:
            problems.append(f"Jooble: {type(exc).__name__}: {exc}"[:200])
    configured = os.environ.get("PORTAL_SOURCES")  # an empty value means "none", unlike an unset one
    portals_on = {p.strip() for p in (portals.DEFAULT_ON if configured is None else configured).split(",") if p.strip()}
    if config.public_mode():
        portals_on = set()  # reading job portals is done from the owner's own machine, never on behalf of visitors
    if portals_on:
        jobs, issues = portals.fetch_all(list(dict.fromkeys(places)), queries, portals_on)
        raw += jobs
        problems += issues
    error = "; ".join(problems)
    employers: dict[str, Company] = {}
    for c in s.execute(select(Company).where(Company.ats == "aggregator")).scalars():
        employers[c.slug] = c
    new = 0
    for r in raw:
        slug = re.sub(r"[^a-z0-9]+", "-", r.employer.lower()).strip("-")[:80]
        if slug not in employers:
            employers[slug] = Company(name=r.employer, ats="aggregator", slug=slug, domain="", enabled=False)  # not a board of its own
            s.add(employers[slug])
            s.flush()
        co = employers[slug]
        seen = s.execute(select(Job).where(Job.company_id == co.id, Job.external_id == r.external_id)).scalar_one_or_none()
        if seen is not None:
            seen.last_seen = _now()
            if seen.status == "closed" and not seen.drafts:
                seen.status, seen.filter_reason = "new", ""
            continue
        s.add(Job(company_id=co.id, external_id=r.external_id, title=r.title, location=r.location, remote=r.remote,
                  description=r.description, url=r.url, posted_at=r.posted_at))
        new += 1
    return len(raw), new, error


# ---- filter -------------------------------------------------------------------
def filter_stage(s: Session, progress) -> dict:
    profile, brief = store.latest_profile(s), store.latest_brief(s)
    jobs = s.execute(select(Job).where(Job.status.notin_(["dismissed", "closed"]))).scalars().all()
    kept = dropped = 0
    for job in jobs:
        verdict = filters.evaluate(job.title, job.location, job.remote, job.description, brief.data)
        if not verdict.ok:
            job.status, job.filter_reason = "filtered", verdict.reason
            dropped += 1
            continue
        job.filter_reason = ""
        kept += 1
        if job.drafts:
            job.status = "drafted"
        elif profile and _current_score(job, profile.version, brief.version):
            job.status = "scored"
        else:
            job.status = "ranked"
    progress(kept=kept, filtered=dropped)
    return {"kept": kept, "filtered": dropped}


# ---- hydrate ------------------------------------------------------------------
HYDRATE_LIMIT = 150  # most full texts fetched per run


def _title_relevance(title: str, brief: dict) -> int:
    words = {w for w in " ".join([*brief.get("roles", []), *brief.get("keywords", [])]).lower().split() if len(w) > 2}
    return sum(1 for w in words if w in title.lower())


def hydrate_stage(s: Session, progress) -> dict:
    """Some job systems list jobs without their text. Fetch the text only for jobs that already passed the cheap
    filters, best title match first, then run the filters again now that the text (for example '5+ years') is known."""
    brief = store.latest_brief(s)
    todo = s.execute(select(Job).where(Job.needs_detail.is_(True), Job.status.in_(["ranked", "scored", "drafted"]))).scalars().all()
    recent = (_now() - timedelta(days=RECENT_DAYS)).date().isoformat()
    todo.sort(key=lambda j: (posted_key(j) < recent, -_title_relevance(j.title, brief.data)))  # fresh postings first, then best title match
    todo = todo[:HYDRATE_LIMIT]
    work_items = [(j.id, j.company.ats, j.company.slug, j.detail_ref) for j in todo]

    def fetch_one(item):
        jid, ats, slug, ref = item
        try:
            return jid, sources.hydrate(ats, slug, ref), ""
        except Exception as exc:
            return jid, None, f"{type(exc).__name__}: {exc}"[:120]

    by_id = {j.id: j for j in todo}
    done = failed = 0
    s.commit()  # release the write lock before the slow network phase
    with ThreadPoolExecutor(max_workers=6) as pool:
        for jid, data, err in pool.map(db.in_context(fetch_one), work_items):
            job = by_id[jid]
            if data is None:
                failed += 1
                continue
            if data.get("description"):
                job.description = data["description"]
            if data.get("location"):
                job.location = data["location"]
            if data.get("posted_at"):
                job.posted_at = data["posted_at"]
            job.needs_detail = not data.get("description")  # retry next run if the text came back empty
            job.emb = None  # the text changed, so the cached embedding is stale
            done += 1
    result = {"hydrated": done, "hydrate_failed": failed}
    progress(**result)
    filter_stage(s, progress)  # re-apply the rules with the real text
    return result


# ---- rank ---------------------------------------------------------------------
def rank_stage(s: Session, progress) -> dict:
    profile, brief = store.latest_profile(s), store.latest_brief(s)
    if profile is None:
        raise ValueError("Upload a resume before ranking.")
    jobs = s.execute(select(Job).where(Job.status.in_(["ranked", "scored", "drafted"]))).scalars().all()
    if not jobs:
        return {"ranked": 0}
    (pvec,), backend = ranker.embed([ranker.profile_text(profile.data, brief.data)])
    stale = [j for j in jobs if j.emb is None or j.emb_backend != backend]
    for i in range(0, len(stale), 64):
        chunk = stale[i : i + 64]
        vecs, _ = ranker.embed([ranker.job_text(j.title, j.company.name, j.description) for j in chunk])
        for job, vec in zip(chunk, vecs):
            job.emb, job.emb_backend = vec, backend
    for job in jobs:
        job.sim = round(ranker.cosine(pvec, job.emb), 4)
    progress(ranked=len(jobs), embeddings=backend)
    return {"ranked": len(jobs), "embeddings": backend}


# ---- relevance (Jev) -----------------------------------------------------------
def relevance_stage(s: Session, progress) -> dict:
    """Ask Jev how close a match each unscored job is, and set aside the clearly irrelevant ones so the (slower, costlier)
    scoring model only sees jobs worth scoring. Skipped without a TYPESAFE_API_KEY. Answers are cached per profile+brief."""
    if not jev.configured():
        progress(relevance_skipped="No key for Jev (set OPENROUTER_API_KEY or TYPESAFE_API_KEY), so every ranked job goes on to scoring.")
        return {"assessed": 0, "skipped": True}
    profile, brief = store.latest_profile(s), store.latest_brief(s)
    if profile is None:
        raise ValueError("Upload a resume before ranking.")
    versions = f"{profile.version}:{brief.version}"
    jobs = s.execute(select(Job).where(Job.status == "ranked", Job.needs_detail.is_(False))).scalars().all()
    todo = [j for j in jobs if j.rel_versions != versions]
    cand = jev.candidate_state(dict(profile.data), dict(brief.data))
    items = [
        (j.id, {"title": j.title, "company": j.company.name, "location": j.location, "description": j.description})
        for j in todo
    ]

    def work(item):
        jid, job = item
        try:
            return jid, jev.assess(cand, job), None
        except (jev.JevAuthError, jev.JevCreditError) as exc:
            return jid, None, exc
        except jev.JevError as exc:
            return jid, None, exc

    by_id = {j.id: j for j in todo}
    done = failed = 0
    cost = 0.0
    fatal: Exception | None = None
    s.commit()  # release the write lock before the slow network phase
    with ThreadPoolExecutor(max_workers=12) as pool:
        for jid, result, err in pool.map(db.in_context(work), items):
            if err is not None:
                failed += 1
                if isinstance(err, (jev.JevAuthError, jev.JevCreditError)):
                    fatal = err
                continue
            job = by_id[jid]
            job.relevance, job.relevance_detail, job.rel_versions = result["relevance"], result["parts"], versions
            cost += result.get("cost", 0.0)
            done += 1
    floor = config.jev_min_relevance()
    dropped = 0
    for job in jobs:
        if job.relevance is not None and job.rel_versions == versions and job.relevance < floor:
            parts = job.relevance_detail or {}
            job.status = "irrelevant"
            job.filter_reason = (
                f"Not a close match (relevance {round(job.relevance * 100)}%: role {round(parts.get('role', 0) * 100)}%, "
                f"skills {round(parts.get('skills', 0) * 100)}%, level {round(parts.get('level', 0) * 100)}%)"
            )
            dropped += 1
    result = {"assessed": done, "relevance_failed": failed, "set_aside": dropped, "jev_cost_usd": round(cost, 5)}
    progress(**result)
    if isinstance(fatal, jev.JevCreditError):
        # no credit for Jev: carry on, so scoring still sees every ranked job instead of the whole search failing
        progress(relevance_skipped=f"{fatal} Jobs were not pre-filtered for relevance.")
        return result
    if fatal is not None:
        raise ValueError(str(fatal))
    return result


# ---- score --------------------------------------------------------------------
def score_stage(s: Session, progress, limit: int = 25) -> dict:
    profile, brief = store.latest_profile(s), store.latest_brief(s)
    if profile is None:
        raise ValueError("Upload a resume before scoring.")
    todo = (
        s.execute(
            select(Job)
            .where(Job.status == "ranked", Job.needs_detail.is_(False))
            .order_by(func.coalesce(Job.relevance, 0.5).desc(), Job.sim.desc())  # Jev's relevance first, then text similarity
            .limit(max(limit * 8, 200))
        ).scalars().all()
    )
    recent = (_now() - timedelta(days=RECENT_DAYS)).date().isoformat()
    todo = sorted(todo, key=lambda j: posted_key(j) < recent)[:limit]  # fresh postings first; the sort keeps relevance order within each group
    payloads = [
        (j.id, j.title, j.company.name, j.location, j.description) for j in todo
    ]  # plain data, so worker threads never touch the session
    pdata, bdata = dict(profile.data), dict(brief.data)

    def work(p):
        jid, title, company, location, desc = p
        try:
            return jid, scorer.score_job(pdata, bdata, title, company, location, desc), ""
        except llm.LLMError as exc:
            return jid, None, str(exc)
        except Exception as exc:
            return jid, None, f"{type(exc).__name__}: {exc}"[:200]

    done = failed = 0
    errors: list[str] = []
    by_id = {j.id: j for j in todo}
    s.commit()  # release the write lock: the worker threads below write their own AI-usage rows
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(db.in_context(work), payloads))  # finish all the slow calls first, then write every result in one go
    model = config.model_chain("score")[0]
    for jid, result, err in results:
        if result is None:
            failed += 1
            errors.append(f"{by_id[jid].title}: {err}")
            continue
        s.add(
            Score(
                job_id=jid,
                profile_version=profile.version,
                brief_version=brief.version,
                total=result["total"],
                signals=result["signals"],
                model=model,
            )
        )
        by_id[jid].status = "scored"
        done += 1
    progress(scored=done)
    return {"scored": done, "failed": failed, "errors": errors[:5]}


# ---- orchestration ------------------------------------------------------------
def _check_cooldown() -> None:
    """On a public site a visitor cannot start searches back to back: every search reads many job boards."""
    if not config.public_mode():
        return
    wait = int(config.env("PUBLIC_RUN_COOLDOWN_SECONDS", "300"))
    with session_scope() as s:
        last = s.execute(select(Run).order_by(Run.id.desc()).limit(1)).scalar_one_or_none()
    if last and last.started_at:
        started = last.started_at if last.started_at.tzinfo else last.started_at.replace(tzinfo=timezone.utc)
        left = wait - (datetime.now(timezone.utc) - started).total_seconds()
        if left > 0:
            raise RuntimeError(f"Please wait {int(left)} seconds before searching again.")


def run_pipeline(stages: list[str], score_limit: int = 25) -> int:
    """Create the Run row and do the work on a background thread. Returns the run id."""
    lock = _lock_for(db.current())
    if not lock.acquire(blocking=False):
        raise RuntimeError("A run is already in progress.")
    try:
        with session_scope() as s:
            sample = demo.is_demo(s)  # a sample workspace never reads the internet
        if not sample:
            _check_cooldown()
        with session_scope() as s:
            run = Run(status="running", stage=stages[0], detail={})
            s.add(run)
            s.flush()
            run_id = run.id
    except Exception:
        lock.release()
        raise

    def go():
        try:
            for stage in stages:
                with session_scope() as s:
                    run = s.get(Run, run_id)
                    run.stage = stage
                    s.commit()  # do not hold SQLite's single write lock for the whole stage: worker threads log their own AI calls

                    def progress(**kw):
                        run.detail = {**(run.detail or {}), **kw}

                    if sample:
                        demo.fake_stage(stage, s, progress, score_limit)
                    elif stage == "fetch":
                        fetch_stage(s, progress)
                    elif stage == "filter":
                        filter_stage(s, progress)
                    elif stage == "hydrate":
                        hydrate_stage(s, progress)
                    elif stage == "rank":
                        rank_stage(s, progress)
                    elif stage == "relevance":
                        relevance_stage(s, progress)
                    elif stage == "score":
                        res = score_stage(s, progress, score_limit)
                        run.detail = {**(run.detail or {}), **res}
            with session_scope() as s:
                run = s.get(Run, run_id)
                run.status, run.stage, run.finished_at = "done", "done", _now()
        except Exception as exc:
            log.exception("pipeline failed")
            with session_scope() as s:
                run = s.get(Run, run_id)
                run.status, run.finished_at = "error", _now()
                run.detail = {**(run.detail or {}), "error": str(exc)[:300]}
        finally:
            lock.release()

    threading.Thread(target=db.in_context(go), daemon=True, name=f"run-{run_id}").start()
    return run_id

