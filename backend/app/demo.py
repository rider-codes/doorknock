"""A ready-made workspace so a visitor can see how every step looks without a key or a resume.

Everything here is made up: the candidate, the companies, the postings and the contacts (whose addresses use the reserved
.invalid domain, so nothing can be delivered). The draft's quotes really are lines from the sample resume and posting, so the
evidence view behaves exactly as it does with real data."""
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import store
from .models import Brief, Company, Draft, Job, LlmCall, Person, Profile, Run, Score

DEMO_ATS = "demo"

RESUME_LINES = [
    "Aarav Sharma",
    "B.Tech Computer Science, 2026. Noida, Uttar Pradesh",
    "Skills: Java, Spring Boot, React, Node.js, PostgreSQL, Docker, AWS",
    "Software Engineering Intern, Brightpath Labs (Jun 2025 - Dec 2025)",
    "Built a Spring Boot service that handled order lookups for 3 internal teams",
    "Moved two PostgreSQL reports to indexed queries and cut their run time from 40 seconds to 6",
    "Wrote React dashboards used daily by the support team",
    "Project: Splitwise-style expense tracker with Node.js, React and PostgreSQL, deployed on AWS",
    "Project: Dockerised a Java REST API and added GitHub Actions tests that run on every push",
]
RESUME_TEXT = "\n".join(RESUME_LINES)

PROFILE = {
    "name": "Aarav Sharma",
    "headline": "Final-year computer science graduate, backend and full-stack",
    "seniority": "entry",
    "years_experience": 0.5,
    "skills": ["Java", "Spring Boot", "React", "Node.js", "PostgreSQL", "Docker", "AWS", "GitHub Actions"],
    "experience": [
        {
            "company": "Brightpath Labs",
            "title": "Software Engineering Intern",
            "start": "2025-06",
            "end": "2025-12",
            "bullets": RESUME_LINES[4:7],
        }
    ],
    "projects": [
        {"name": "Expense tracker", "description": RESUME_LINES[7], "tech": ["Node.js", "React", "PostgreSQL", "AWS"]},
        {"name": "Dockerised REST API", "description": RESUME_LINES[8], "tech": ["Java", "Docker", "GitHub Actions"]},
    ],
    "education": ["B.Tech Computer Science, 2026"],
    "locations": ["Noida, Uttar Pradesh"],
}

BRIEF = {
    "roles": ["Backend Engineer", "Full Stack Developer"],
    "cities": ["Noida", "Delhi", "Gurugram", "Bengaluru"],
    "countries": ["India"],
    "remote_ok": True,
    "level": "entry",
    "job_type": "full_time",
    "keywords": ["Java", "Spring Boot", "React"],
    "exclude_keywords": [],
    "title_keywords": ["backend", "back-end", "full stack", "full-stack", "software engineer", "software developer", "sde"],
    "avoid_titles": ["sales", "recruiter", "marketing"],
}

HISTORY = [
    {"role": "user", "content": "I'm a fresher looking for backend or full stack jobs around Delhi NCR or Bengaluru."},
    {"role": "assistant", "content": "Got it: entry-level backend and full-stack roles in Noida, Delhi, Gurugram and Bengaluru, remote is fine too."},
]

POSTING_PAYMENTS = (
    "Backend Engineer, Payments\n"
    "You will build and run REST services in Java and Spring Boot that move money for small businesses.\n"
    "We store everything in PostgreSQL and deploy with Docker on AWS.\n"
    "We hire new graduates and pair every new engineer with a mentor for the first six months.\n"
    "2+ years of experience is nice to have, not required."
)


def _signals(parts):
    """parts: five (score, reason) pairs in the order role, profile, skills, location, seniority."""
    maxima = {"role": 25, "profile": 30, "skills": 20, "location": 15, "seniority": 10}
    out = {}
    for (name, maximum), (score, reason) in zip(maxima.items(), parts):
        out[name] = {"score": min(score, maximum), "max": maximum, "reason": reason}
    return out


# title, company, location, days_ago, description, signal parts (None = not scored yet), status, filter_reason
JOBS = [
    ("Backend Engineer, Payments", "Lumen Payments", "Noida, Uttar Pradesh", 1, POSTING_PAYMENTS,
     [(24, "Backend services in Java and Spring Boot"), (27, "Order-lookup service mirrors this work"), (19, "Java, Spring Boot, PostgreSQL, Docker, AWS all listed"),
      (15, "Noida, your city"), (9, "New graduates welcome")], "drafted", ""),
    ("Full Stack Developer", "Northwind Labs", "Gurugram, Haryana", 2,
     "Full Stack Developer\nBuild customer dashboards in React with a Node.js API.\nPostgreSQL, Docker and AWS in daily use.\nOpen to freshers with strong projects.",
     [(22, "React and Node.js dashboards"), (25, "Dashboards used by support match well"), (17, "React, Node.js, PostgreSQL, AWS"),
      (15, "Gurugram is within Delhi NCR"), (9, "Freshers welcome")], "scored", ""),
    ("Software Engineer I", "Cobalt Systems", "Bengaluru, Karnataka", 3,
     "Software Engineer I\nJava microservices on Spring Boot for a logistics platform.\nYou will own small features end to end.\n0-2 years of experience.",
     [(21, "Java microservices, general SDE title"), (22, "Service work fits, no logistics background"), (16, "Java and Spring Boot match"),
      (11, "Bengaluru is on your list, not your home city"), (9, "0-2 years")], "scored", ""),
    ("Associate Backend Developer", "Pixel Harbor", "Remote - India", 4,
     "Associate Backend Developer\nNode.js APIs for a mobile game studio.\nRemote within India.\nComfort with SQL needed.",
     [(20, "Backend, but Node.js-only"), (21, "Internship work was Java-led"), (13, "Node.js and SQL match, Java unused"),
      (14, "Remote within India"), (9, "Associate level")], "scored", ""),
    ("Frontend Engineer", "Fable Retail", "Noida, Uttar Pradesh", 5,
     "Frontend Engineer\nReact and TypeScript for an e-commerce storefront.\nPixel-perfect UI work is the main job.",
     [(13, "Frontend-focused, you want backend or full stack"), (19, "React dashboards help, no TypeScript shown"), (12, "React matches, TypeScript missing"),
      (15, "Noida, your city"), (8, "Entry level")], "scored", ""),
    ("Data Platform Engineer", "Quanta Metrics", "Hyderabad, Telangana", 6,
     "Data Platform Engineer\nSpark and Airflow pipelines on AWS.\nPython preferred.",
     [(10, "Data pipelines, not your target roles"), (14, "Little overlap with your projects"), (6, "AWS only; Spark, Airflow, Python missing"),
      (4, "Hyderabad is not on your list"), (7, "Level is unclear")], "scored", ""),
    ("Software Developer Trainee", "Greenfield Tech", "Delhi", 1,
     "Software Developer Trainee\nSix-month paid training on Java and Spring Boot, then a placement on a client team.",
     [(19, "Training role, Java and Spring Boot"), (20, "Fresh graduate fit, below your internship level"), (17, "Java and Spring Boot named"),
      (15, "Delhi is within Delhi NCR"), (7, "Trainee, a step below entry")], "scored", ""),
    ("Backend Engineer", "Ironleaf", "Noida, Uttar Pradesh", 1,
     "Backend Engineer\nGo and PostgreSQL services for a healthcare scheduling product.",
     None, "ranked", ""),
    ("Full Stack Engineer", "Marlow & Finch", "Bengaluru, Karnataka", 2,
     "Full Stack Engineer\nReact front end, Java back end, hospital analytics.",
     None, "ranked", ""),
    ("Software Engineer", "Tidewater AI", "Remote - India", 0,
     "Software Engineer\nBuild LLM-powered internal tools in TypeScript and Python.",
     None, "ranked", ""),
    ("Senior Backend Engineer", "Lumen Payments", "Noida, Uttar Pradesh", 7,
     "Senior Backend Engineer\n6+ years of experience building payment systems.", None, "filtered",
     "Too senior: title says 'Senior'"),
    ("Backend Engineer, Platform", "Cobalt Systems", "Bengaluru, Karnataka", 8,
     "Backend Engineer\n5+ years of experience with distributed systems required.", None, "filtered",
     "Asks for 5+ years of experience (your level allows up to 2)"),
    ("Backend Developer", "Skyline Freight", "Chennai, Tamil Nadu", 9,
     "Backend Developer\nJava and Spring Boot for a freight tracker.", None, "filtered",
     "Location 'Chennai, Tamil Nadu' is outside your cities and countries"),
    ("Sales Engineer", "Northwind Labs", "Noida, Uttar Pradesh", 3,
     "Sales Engineer\nPre-sales demos for enterprise customers.", None, "filtered",
     "Title says 'sales', which is not the kind of role you want"),
]

PEOPLE = [
    ("Meera Kapoor", "Technical Recruiter", "recruiter", 90, "Recruiting contact for the company; title overlaps with the job"),
    ("Rohan Iyer", "Engineering Manager, Payments", "hiring_manager", 88, "Likely makes or influences the hiring decision"),
]

DRAFT_SENTENCES = [
    ("I built a Spring Boot service that handled order lookups for 3 internal teams.", "resume", RESUME_LINES[4]),
    ("You are building REST services in Java and Spring Boot that move money for small businesses.", "posting",
     "You will build and run REST services in Java and Spring Boot that move money for small businesses."),
    ("I saw that you pair every new engineer with a mentor, which is how I would like to start.", "posting",
     "We hire new graduates and pair every new engineer with a mentor for the first six months."),
]


# What "Score 25 more" gives the three waiting sample jobs, so pressing it shows something real-looking.
WAITING_PARTS = {
    "Ironleaf": [(17, "Backend work, but Go instead of your Java"), (19, "Related services, different stack"), (11, "PostgreSQL matches; Go is not on your resume"),
                 (15, "Noida, your city"), (8, "Entry-friendly posting")],
    "Marlow & Finch": [(22, "React front end with a Java back end"), (24, "Your dashboards and Spring Boot both match"), (16, "React, Java and Spring Boot"),
                       (11, "Bengaluru is on your list"), (9, "Entry level")],
    "Tidewater AI": [(12, "LLM tools, outside your target roles"), (15, "Little overlap with your projects"), (8, "TypeScript and Python are missing"),
                     (14, "Remote within India"), (7, "Level unclear")],
}

_PAUSE = 0.35  # seconds per step, so the progress is visible but the whole run takes about two seconds


def score_waiting(s: Session, limit: int) -> int:
    """Give the waiting sample jobs their prepared scores. Nothing is called; this is the sample run's 'scoring'."""
    profile, brief = store.latest_profile(s), store.latest_brief(s)
    jobs = s.execute(select(Job).join(Company).where(Company.ats == DEMO_ATS, Job.status == "ranked").order_by(Job.id).limit(limit)).scalars().all()
    done = 0
    for job in jobs:
        parts = WAITING_PARTS.get(job.company.name)
        if not parts or profile is None:
            continue
        signals = _signals(parts)
        s.add(Score(job_id=job.id, profile_version=profile.version, brief_version=brief.version,
                    total=sum(x["score"] for x in signals.values()), signals=signals, model="sample"))
        job.status = "scored"
        done += 1
    s.flush()
    return done


def fake_stage(stage: str, s: Session, progress, limit: int) -> None:
    """One step of a sample search: quick, offline, and it reports plausible numbers."""
    time.sleep(_PAUSE)
    counts = {st: n for st, n in s.execute(select(Job.status, func.count()).group_by(Job.status)).all()}
    if stage == "fetch":
        progress(fetched=sum(counts.values()), new=0, boards=0, board_errors=[], fetched_at=datetime.now(timezone.utc).isoformat())
    elif stage == "filter":
        progress(kept=counts.get("ranked", 0) + counts.get("scored", 0) + counts.get("drafted", 0), filtered=counts.get("filtered", 0))
    elif stage == "score":
        progress(scored=score_waiting(s, limit), failed=0, errors=[])
    else:
        progress(**{stage: "sample"})


def is_demo(s: Session) -> bool:
    return s.execute(select(Company.id).where(Company.ats == DEMO_ATS).limit(1)).first() is not None


def wipe(s: Session) -> None:
    """Remove the visitor's profile, brief, jobs and runs (the shared list of boards to search stays)."""
    for model in (Draft, Person, Score, Job, Profile, Brief, Run, LlmCall):
        s.execute(delete(model))
    s.execute(delete(Company).where(Company.ats == DEMO_ATS))
    s.flush()


def seed(s: Session) -> None:
    wipe(s)
    profile = store.save_profile(s, "sample-resume.pdf", RESUME_TEXT, PROFILE)
    brief = store.save_brief(s, BRIEF, HISTORY)
    now = datetime.now(timezone.utc)
    companies: dict[str, Company] = {}
    drafted_job = None
    for title, company, location, days, text, parts, status, reason in JOBS:
        if company not in companies:
            slug = company.lower().replace(" & ", "-").replace(" ", "-")
            companies[company] = Company(name=company, ats=DEMO_ATS, slug=slug, domain=f"{slug}.example", enabled=False)
            s.add(companies[company])
            s.flush()
        job = Job(
            company_id=companies[company].id,
            external_id=f"demo-{len(companies)}-{title}".lower().replace(" ", "-")[:60],
            title=title,
            location=location,
            remote="remote" in location.lower(),
            description=text,
            url="https://example.invalid/sample-job",
            posted_at=(now - timedelta(days=days)).date().isoformat(),
            status=status if status != "drafted" else "scored",
            filter_reason=reason,
            sim=0.5 if status != "filtered" else 0.1,
            relevance=0.8 if parts else None,
            first_seen=now - timedelta(days=days),
            last_seen=now,
        )
        s.add(job)
        s.flush()
        if parts:
            signals = _signals(parts)
            s.add(Score(job_id=job.id, profile_version=profile.version, brief_version=brief.version,
                        total=sum(x["score"] for x in signals.values()), signals=signals, model="sample"))
        if status == "drafted":
            drafted_job = job
    s.flush()
    if drafted_job is not None:
        people = []
        for name, title, role, relevance, why in PEOPLE:
            person = Person(job_id=drafted_job.id, name=name, title=title, role_type=role, relevance=relevance, why=why,
                            email=f"{name.split()[0].lower()}.{name.split()[1].lower()}@lumen-payments.invalid", email_status="unknown",
                            source="sample")
            s.add(person)
            people.append(person)
        s.flush()
        body = "Hi Meera,\n\n" + " ".join(t for t, _, _ in DRAFT_SENTENCES) + "\n\nThanks for your time,"
        s.add(Draft(
            job_id=drafted_job.id, person_id=people[0].id, subject="Backend Engineer, Payments: a fresher who has built Spring Boot services",
            body=body, status="verified", problems=[],
            evidence=[{"sentence": t, "fact_id": f"{'R' if src == 'resume' else 'P'}{i + 1}", "source": src, "quote": q}
                      for i, (t, src, q) in enumerate(DRAFT_SENTENCES)],
        ))
        drafted_job.status = "drafted"
    s.flush()
