from app.schemas import DraftResult, DraftSentence
from app.services import outreach

RESUME = """Jane Doe
- Built a double-entry ledger reconciling 40,000 transactions a day at Acme
- Wrote Go services backed by PostgreSQL
Education: BSc Computer Science
"""
POSTING = """Backend Engineer, Payments
You will build ledger services in Go and Postgres.
We ship to production daily.
"""


def _facts():
    return outreach.candidate_facts(RESUME, POSTING, "Backend Engineer, Payments")


def _find(facts, source, needle):
    return next(f for f in facts if f["source"] == source and needle in f["quote"])


def _draft(sentences):
    return DraftResult(subject="s", greeting="Hi,", sentences=sentences, closing="Thanks,")


def test_facts_are_verbatim_lines():
    for f in _facts():
        src = RESUME if f["source"] == "resume" else POSTING
        assert f["quote"] in src


def test_good_draft_passes():
    facts = _facts()
    r = _find(facts, "resume", "ledger")
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I built a double-entry ledger reconciling 40,000 transactions a day.", kind="about_me", fact_id=r["id"]),
            DraftSentence(text="You are building ledger services in Go and Postgres.", kind="about_job", fact_id=p["id"]),
            DraftSentence(text="Worth a short chat?", kind="ask"),
        ]
    )
    assert outreach.verify(d, facts, RESUME, POSTING) == []


def test_invented_number_is_rejected():
    facts = _facts()
    r = _find(facts, "resume", "ledger")
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I reconciled 90,000 transactions a day.", kind="about_me", fact_id=r["id"]),
            DraftSentence(text="You build ledger services.", kind="about_job", fact_id=p["id"]),
        ]
    )
    problems = outreach.verify(d, facts, RESUME, POSTING)
    assert any("90,000" in x for x in problems)


def test_fabricated_quote_is_rejected():
    facts = _facts() + [{"id": "R99", "source": "resume", "quote": "Led a team of 12 engineers at Google"}]
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I led a team of 12 engineers at Google.", kind="about_me", fact_id="R99"),
            DraftSentence(text="You build ledgers.", kind="about_job", fact_id=p["id"]),
        ]
    )
    problems = outreach.verify(d, facts, RESUME, POSTING)
    assert any("not a verbatim quote" in x for x in problems)


def test_unknown_fact_and_unsourced_figure_are_rejected():
    facts = _facts()
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I have 7 years of experience.", kind="ask"),
            DraftSentence(text="Something.", kind="about_me", fact_id="R404"),
            DraftSentence(text="You build ledgers.", kind="about_job", fact_id=p["id"]),
        ]
    )
    problems = outreach.verify(d, facts, RESUME, POSTING)
    assert any("figure" in x for x in problems)
    assert any("unknown fact" in x for x in problems)
    assert any("No resume fact" in x for x in problems)


def test_assemble_builds_evidence():
    facts = _facts()
    r = _find(facts, "resume", "ledger")
    body, evidence = outreach.assemble(_draft([DraftSentence(text="I built a ledger.", kind="about_me", fact_id=r["id"])]), facts)
    assert body.startswith("Hi,") and "I built a ledger." in body
    assert evidence[0]["quote"] == r["quote"]


def test_claim_about_sender_cannot_cite_the_posting():
    facts = _facts()
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I build ledger services in Go and Postgres.", kind="about_me", fact_id=p["id"]),
            DraftSentence(text="You build ledger services in Go and Postgres.", kind="about_job", fact_id=p["id"]),
        ]
    )
    problems = outreach.verify(d, facts, RESUME, POSTING)
    assert any("must cite the resume" in x for x in problems)


def test_unsourced_ask_cannot_claim_experience():
    facts = _facts()
    r = _find(facts, "resume", "ledger")
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I built a double-entry ledger reconciling 40,000 transactions a day.", kind="about_me", fact_id=r["id"]),
            DraftSentence(text="You are building ledger services in Go and Postgres.", kind="about_job", fact_id=p["id"]),
            DraftSentence(text="I've operated production AI systems on top of LLM APIs.", kind="ask"),
        ]
    )
    assert any("claim about the sender" in x for x in outreach.verify(d, facts, RESUME, POSTING))


def test_sentence_must_stay_close_to_its_quote():
    facts = _facts()
    r = _find(facts, "resume", "ledger")
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I architected a distributed machine learning platform serving millions.", kind="about_me", fact_id=r["id"]),
            DraftSentence(text="You are building ledger services in Go and Postgres.", kind="about_job", fact_id=p["id"]),
        ]
    )
    assert any("says more than" in x for x in outreach.verify(d, facts, RESUME, POSTING))


def test_job_statement_cannot_speak_as_the_sender():
    facts = _facts()
    r = _find(facts, "resume", "ledger")
    p = _find(facts, "posting", "ledger")
    d = _draft(
        [
            DraftSentence(text="I built a double-entry ledger reconciling 40,000 transactions a day.", kind="about_me", fact_id=r["id"]),
            DraftSentence(text="I will build ledger services in Go and Postgres.", kind="about_job", fact_id=p["id"]),
        ]
    )
    assert any("speaks as the sender" in x for x in outreach.verify(d, facts, RESUME, POSTING))
