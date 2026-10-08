from datetime import datetime, timedelta, timezone

from app import db, refresh
from app.models import Run


def _fetched(hours_ago: float) -> Run:
    stamp = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return Run(status="done", stage="done", detail={"fetched_at": stamp})


def test_a_refresh_is_due_when_the_boards_were_last_read_long_ago(client, monkeypatch):
    monkeypatch.setenv("AUTO_REFRESH_HOURS", "6")
    # no resume yet: nothing to match against, so nothing is due
    with db.session_scope() as s:
        assert refresh.due(s) is False
    with db.session_scope() as s:
        s.add(store_profile_stub())
    with db.session_scope() as s:
        assert refresh.due(s) is True  # never read
        s.add(_fetched(1))
    with db.session_scope() as s:
        assert refresh.due(s) is False  # read an hour ago
        s.add(_fetched(0.1))
    with db.session_scope() as s:
        assert refresh.last_refreshed(s) is not None


def test_an_old_read_makes_it_due_and_zero_hours_turns_it_off(client, monkeypatch):
    with db.session_scope() as s:
        s.add(store_profile_stub())
        s.add(_fetched(30))
    monkeypatch.setenv("AUTO_REFRESH_HOURS", "6")
    with db.session_scope() as s:
        assert refresh.due(s) is True
    monkeypatch.setenv("AUTO_REFRESH_HOURS", "0")
    with db.session_scope() as s:
        assert refresh.due(s) is False


def test_state_reports_freshness(client, monkeypatch):
    monkeypatch.setenv("AUTO_REFRESH_HOURS", "6")
    body = client.get("/api/state").json()
    assert body["freshness"] == {"last_refreshed": None, "auto_hours": 6.0}


def store_profile_stub():
    from app.models import Profile

    return Profile(version=1, filename="cv.docx", raw_text="x", data={})
