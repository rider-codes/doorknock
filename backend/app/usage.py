"""A small request budget for paid or capped APIs, kept in a file so it survives restarts.

Jooble's key allows 500 requests in total. With a refresh every few hours that would be gone in days, so each search
may spend only a few, and the running total is checked before every call."""
import json
from datetime import date

from . import config


def _file():
    return config.data_dir() / "api_usage.json"


def _load() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def used(name: str) -> tuple[int, int]:
    """(requests spent today, requests spent in total)."""
    row = _load().get(name, {})
    today = row.get("today", 0) if row.get("day") == date.today().isoformat() else 0
    return today, row.get("total", 0)


def allow(name: str, daily: int, total: int) -> bool:
    today, spent = used(name)
    return today < daily and spent < total


def spend(name: str, n: int = 1) -> None:
    data = _load()
    row = data.get(name, {})
    today = row.get("today", 0) if row.get("day") == date.today().isoformat() else 0
    data[name] = {"day": date.today().isoformat(), "today": today + n, "total": row.get("total", 0) + n}
    _file().write_text(json.dumps(data), encoding="utf-8")
