"""Order the backlog by how close each job is to the profile, so the best fits are scored first."""
import logging
import re
import zlib

import numpy as np

from .. import config

log = logging.getLogger("doorknock.ranker")
DIM = 2048
_model = None
_model_failed = False


def _fastembed():
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    try:
        from fastembed import TextEmbedding

        _model = TextEmbedding("BAAI/bge-small-en-v1.5")
    except Exception as exc:  # not installed, offline, etc.
        log.warning("fastembed unavailable (%s); using hashing embeddings", exc)
        _model_failed = True
    return _model


def backend_name() -> str:
    choice = config.env("EMBEDDINGS", "auto").lower()
    if choice == "hash":
        return "hash"
    return "fastembed" if _fastembed() is not None else "hash"


def _hash_embed(text: str) -> np.ndarray:
    vec = np.zeros(DIM, dtype=np.float32)
    tokens = re.findall(r"[a-z0-9+#.]{2,}", text.lower())
    counts: dict[int, int] = {}
    for tok in tokens:
        idx = zlib.crc32(tok.encode()) % DIM
        counts[idx] = counts.get(idx, 0) + 1
    for idx, c in counts.items():
        vec[idx] = 1.0 + np.log(c)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def embed(texts: list[str]) -> tuple[list[list[float]], str]:
    """Return unit-length vectors and the backend that made them (vectors from different backends do not mix)."""
    backend = backend_name()
    if backend == "fastembed":
        vecs = [np.asarray(v, dtype=np.float32) for v in _fastembed().embed(texts)]
        vecs = [v / (np.linalg.norm(v) or 1.0) for v in vecs]
    else:
        vecs = [_hash_embed(t) for t in texts]
    return [v.tolist() for v in vecs], backend


def cosine(a: list[float], b: list[float]) -> float:
    return float(np.dot(np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)))


def profile_text(profile: dict, brief: dict) -> str:
    parts = [profile.get("headline", ""), " ".join(profile.get("skills", []))]
    for exp in profile.get("experience", []):
        parts.append(f"{exp.get('title', '')} {exp.get('company', '')} " + " ".join(exp.get("bullets", [])))
    for proj in profile.get("projects", []):
        parts.append(f"{proj.get('name', '')} {proj.get('description', '')} " + " ".join(proj.get("tech", [])))
    parts.append(" ".join(brief.get("roles", [])))
    parts.append(" ".join(brief.get("keywords", [])))
    return "\n".join(p for p in parts if p)


def job_text(title: str, company: str, description: str) -> str:
    return f"{title}\n{company}\n{description[:3000]}"
