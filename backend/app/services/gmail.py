"""Gmail integration. The only scope requested is gmail.compose, and the only call made is drafts.create.
There is deliberately no send path anywhere in this app."""
import base64
from email.message import EmailMessage

from .. import config

SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailError(RuntimeError):
    pass


def _token_path():
    return config.data_dir() / "gmail_token.json"


def is_connected() -> bool:
    return _token_path().exists()


def has_client_secret() -> bool:
    return config.google_client_secret_file().exists()


def connect() -> None:
    """Open the Google consent screen in the browser on this machine and store the token."""
    secret = config.google_client_secret_file()
    if not secret.exists():
        raise GmailError(
            f"Google client secret not found at {secret}. Create an OAuth 'Desktop app' client in Google Cloud Console, "
            "enable the Gmail API, and save the JSON there."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _token_path().write_text(creds.to_json(), encoding="utf-8")


def _service():
    if not is_connected():
        raise GmailError("Gmail is not connected yet. Press 'Connect Gmail' first.")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(_token_path()), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _token_path().write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def build_raw(to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    if to:
        msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft(to: str, subject: str, body: str) -> str:
    """Save a draft in the user's Gmail. Returns the draft id. Nothing is sent."""
    try:
        draft = _service().users().drafts().create(userId="me", body={"message": {"raw": build_raw(to, subject, body)}}).execute()
    except GmailError:
        raise
    except Exception as exc:
        raise GmailError(f"Gmail refused the draft: {exc}") from exc
    return draft["id"]
