"""Databases: one per workspace.

On your own machine there is a single workspace ("local"). A public site gives every visitor a private one, picked by the
workspace id their browser sends, so nobody sees anyone else's resume, jobs or drafts. The current workspace travels in a
context variable; background threads must run inside a copy of it (see `in_context`)."""
import contextvars
import re
import threading
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

LOCAL = "local"
_ID = re.compile(r"^[a-f0-9]{32}$")


class Base(DeclarativeBase):
    pass


_workspace: contextvars.ContextVar[str] = contextvars.ContextVar("workspace", default=LOCAL)
_engines: dict[str, tuple] = {}
_guard = threading.Lock()


def valid_id(value: str) -> bool:
    return bool(value and _ID.match(value))


def current() -> str:
    return _workspace.get()


def use(workspace_id: str):
    """Make `workspace_id` the current workspace for this context. Returns a token for `release`."""
    return _workspace.set(workspace_id)


def release(token) -> None:
    _workspace.reset(token)


def in_context(fn):
    """Wrap `fn` so a worker thread runs it inside the workspace (and visitor keys) of whoever scheduled it."""
    ctx = contextvars.copy_context()

    def run(*args, **kwargs):
        return ctx.copy().run(fn, *args, **kwargs)

    return run


def path_for(workspace_id: str):
    if workspace_id == LOCAL:
        return config.data_dir() / "doorknock.db"
    folder = config.data_dir() / "workspaces"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{workspace_id}.db"


def _make(workspace_id: str):
    url = f"sqlite:///{path_for(workspace_id).as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        # WAL lets readers work while one writer writes; busy_timeout makes a second writer wait instead of failing
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _entry(workspace_id: str | None = None):
    wid = workspace_id or current()
    with _guard:
        if wid not in _engines:
            fresh = not path_for(wid).exists()
            _engines[wid] = _make(wid)
            if fresh or wid == LOCAL:
                _init(_engines[wid][0])
            else:
                _add_missing_columns(_engines[wid][0])
        return _engines[wid]


def get_engine():
    return _entry()[0]


def reset_engine() -> None:
    """Forget every cached engine (tests point DOORKNOCK_DATA somewhere else)."""
    with _guard:
        for engine, _ in _engines.values():
            engine.dispose()
        _engines.clear()


def _init(engine) -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


def init_db() -> None:
    _init(_entry(LOCAL)[0])


def _add_missing_columns(engine) -> None:
    """create_all never alters an existing table. For a single-user SQLite file, add any column a newer version needs."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                kind = col.type.compile(engine.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "is_scalar", False):
                    val = col.default.arg
                    default = f" DEFAULT {int(val) if isinstance(val, bool) else repr(val)}"
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {kind}{default}'))


@contextmanager
def session_scope():
    session = _entry()[1]()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session():
    """FastAPI dependency."""
    with session_scope() as session:
        yield session


# ---- workspace housekeeping -------------------------------------------------------------------
def workspace_count() -> int:
    folder = config.data_dir() / "workspaces"
    return len(list(folder.glob("*.db"))) if folder.exists() else 0


def exists(workspace_id: str) -> bool:
    return path_for(workspace_id).exists()


def delete_workspace(workspace_id: str) -> None:
    """Remove a visitor's workspace and everything in it."""
    if workspace_id == LOCAL:
        raise ValueError("The local workspace is not deleted this way.")
    with _guard:
        entry = _engines.pop(workspace_id, None)
        if entry:
            entry[0].dispose()
    for suffix in ("", "-wal", "-shm"):
        target = path_for(workspace_id).with_name(f"{workspace_id}.db{suffix}")
        target.unlink(missing_ok=True)


def prune_workspaces(max_idle_days: int) -> int:
    """Delete workspaces nobody has touched for `max_idle_days`. Returns how many were removed."""
    folder = config.data_dir() / "workspaces"
    if not folder.exists():
        return 0
    cutoff = time.time() - max_idle_days * 86400
    removed = 0
    for db_file in folder.glob("*.db"):
        newest = max([db_file.stat().st_mtime, *(p.stat().st_mtime for p in db_file.parent.glob(db_file.name + "-*"))])
        if newest < cutoff:
            delete_workspace(db_file.stem)
            removed += 1
    return removed
