# Doorknock

Find the right person. Knock with a real reason.

A personal job-search assistant for one user. Upload a resume, describe the job you want in a chat, and Doorknock:

1. reads your resume into a structured profile,
2. turns your chat into a search brief (roles, cities, level, keywords, job type),
3. reads employers' own job boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable and Workday),
4. drops jobs in the wrong city or above your level with hard rules,
5. ranks the rest with text embeddings so the best fits are scored first, then asks Jev (a fast classifier from TypeSafe AI that returns probabilities; it runs on your OpenRouter key, model `~typesafe/jev-latest`) how relevant each job is and sets the clearly irrelevant ones aside before the scoring model sees them,
6. scores each job out of 100 on five signals (role 25, profile 30, skills 20, location 15, seniority 10), each with a one-line reason,
7. finds recruiters, hiring managers and teammates, ranked by relevance and verified email,
8. writes an email only from facts quoted from your resume or the posting, checks every quote in code, and saves it as a **Gmail draft**.

**Nothing is ever sent.** The only Gmail scope requested is `gmail.compose` and the only call made is `drafts.create`. A test fails if a send call appears in the code.

## Two pages

- `/` is the overview: what Doorknock does, an interactive example with fixed sample data (no setup, no API calls, nothing sent), and the three promises the code keeps.
- `/app` is the workspace: resume, brief, matches, people and draft, wired to the real backend.

There is no sign-in and no paywall.

## Run it

Needs Python 3.12+ and Node 20+.

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

First run installs everything and creates `backend\.env`. Add your `OPENROUTER_API_KEY` (or `ANTHROPIC_API_KEY`), run it again, and open http://localhost:5173.

On a phone (same Wi-Fi): open `http://<your-pc-ip>:5173`, then "Add to Home Screen". The layout is built mobile-first.

Manual start, if you prefer:

```powershell
cd backend;  .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
cd frontend; node node_modules/vite/bin/vite.js --port 5173
```

(`npx` breaks on folder names containing `&`, so the scripts call node directly.)

## Setup you need to do yourself

| What | Why | Where |
| --- | --- | --- |
| `OPENROUTER_API_KEY` (or `ANTHROPIC_API_KEY`) | all the AI steps. With OpenRouter each job uses its own model: a free or cheap one for the resume, a cheap one for scoring, another cheap one for the email, and a strong one to choose the right people. Change them with `MODEL_PARSE`, `MODEL_SCORE`, `MODEL_DRAFT`, `MODEL_PEOPLE` (see `.env.example`). | `backend/.env` |
| `PEOPLE_PROVIDER=hunter` + `HUNTER_API_KEY` | finds people and verifies emails | `backend/.env`. Use `mock` to try the screens with fake contacts. |
| Google OAuth "Desktop app" client | saving drafts to Gmail | save as `backend/data/google_client_secret.json`, enable the Gmail API, then press **Connect Gmail** in the Draft step |
| Optional: `pip install fastembed` | better ranking embeddings | otherwise a built-in hashing fallback is used |

Add job boards by pasting a company's job board link (Greenhouse, Lever, Ashby, SmartRecruiters, Workable or Workday) in the Brief step. SmartRecruiters, Workday and Workable list jobs without their text, so Doorknock searches them for your roles and countries, then reads the full text only for the jobs that pass the first filters. A starter list is seeded; some slugs may be out of date, and a broken board is skipped and reported, never fatal.

## Layout

```
backend/app
  main.py            API routes
  pipeline.py        fetch -> filter -> rank -> score (background, resumable)
  llm.py             Anthropic wrapper: forced tool call, retry, token log, daily cap
  services/
    resume_parser    PDF/DOCX -> text -> profile
    brief_agent      chat -> brief
    sources          Greenhouse / Lever / Ashby adapters
    filters          city, country, level, job type, excluded words
    ranker           embeddings (fastembed or hashing fallback)
    scorer           five signals; total summed in code
    people           Hunter provider + ranking
    outreach         fact extraction, grounded writer, quote verifier
    gmail            OAuth + drafts.create only
frontend/src         React + Vite, five steps, light and dark
backend/tests        pytest
```

## Tests

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest -q
```

Covers the filters, score maths, people ranking, source parsers, the quote verifier (it must reject invented numbers and fabricated quotes), the no-send guarantee, and the whole flow through the API with the model and job boards faked.

## Known limits (v1)

- Scanned PDFs are not read (no OCR). Upload a text PDF or a .docx.
- People lookup works by company website domain, which you confirm per company.
- The Hunter and Google integrations are written to their public docs but need your keys to exercise for real.
- Single user, local SQLite, no sign-in by design.


