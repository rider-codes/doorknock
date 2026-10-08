"""The core promise: nothing is ever sent. These tests fail if a send path appears."""
import base64
import re
from pathlib import Path

from app.services import gmail

APP = Path(__file__).resolve().parents[1] / "app"


def test_no_send_call_exists_in_source():
    pattern = re.compile(r"\.(send|drafts\(\)\.send|messages\(\)\.send)\s*\(|gmail\.send|\.users\(\)\.messages\(\)")
    offenders = []
    for path in APP.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if pattern.search(line) and "drafts().create" not in line:
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert offenders == [], offenders


def test_only_compose_scope_is_requested():
    assert gmail.SCOPES == ["https://www.googleapis.com/auth/gmail.compose"]


def test_raw_message_is_well_formed():
    raw = gmail.build_raw("jane@example.com", "Hello", "Body text")
    text = base64.urlsafe_b64decode(raw).decode()
    assert "To: jane@example.com" in text and "Subject: Hello" in text and "Body text" in text


def test_draft_without_recipient_is_allowed():
    raw = gmail.build_raw("", "Hello", "Body")
    assert "To:" not in base64.urlsafe_b64decode(raw).decode()
