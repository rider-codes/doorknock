"""PDF text extraction: packed letters must not collapse a resume into 'Builtafinanceappwherepeople...'."""
from pathlib import Path

import pytest

from app.services import resume_parser as rp

GOOD = "Built a finance app where people upload a CSV file and get a dashboard showing where they spend their money. " * 3
MERGED = GOOD.replace(" ", "")
SHATTERED = " ".join(GOOD.replace(" ", ""))


def test_space_score_ranks_good_text_best():
    assert rp.space_score(GOOD) < 0.5 < rp.space_score(MERGED)
    assert rp.space_score(GOOD) < rp.space_score(SHATTERED)
    assert rp.space_score("") == 99.0


def test_default_reading_is_kept_when_it_looks_fine():
    calls = []

    def extract(**kw):
        calls.append(kw)
        return GOOD

    assert rp.best_extraction(extract) == GOOD
    assert calls == [{}]  # no wasted retries


def test_tighter_settings_are_tried_when_words_run_together():
    def extract(**kw):
        return GOOD if kw.get("x_tolerance", 3) <= 2 or "x_tolerance_ratio" in kw else MERGED

    out = rp.best_extraction(extract)
    assert " " in out and out == GOOD


def test_the_best_of_several_bad_readings_wins():
    def extract(**kw):
        if not kw:
            return MERGED
        return SHATTERED if kw.get("x_tolerance") == 1 else GOOD if kw.get("x_tolerance") == 1.5 else MERGED

    assert rp.best_extraction(extract) == GOOD


REAL = Path(r"C:\Users\rahul\Downloads\Rahul_Srivastava_Resume_Agentic_AI_Engineer.pdf")


@pytest.mark.skipif(not REAL.exists(), reason="the real resume that exposed the bug is only on the developer's machine")
def test_the_real_resume_reads_with_spaces():
    text = rp.extract_text(REAL.name, REAL.read_bytes())
    assert "Built a finance app" in text and rp.space_score(text) < 1.0
