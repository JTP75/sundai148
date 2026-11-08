"""Private-field allowlist and regex backstop (design D12; corpus-intake spec). Stdlib only.

``check_corpus_dir`` runs inside every source-machine stage before anything leaves the machine. It

- validates each ``<table>.jsonl`` against ``potency.schema`` (column allowlist, types and enums);
- regex-scans every exported text file for credentials, URLs, absolute paths and caller-supplied
  forbidden strings;
- applies a long-hex / high-entropy backstop to values that are not declared identifiers or hashes.

The regex scan is a backstop, not a guarantee (design Risks): the field allowlist is the primary
control, and sanitization happens in the adapter.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from potency import io, schema

# Columns whose values are opaque ids or hashes. They are still scanned for tokens, URLs, paths
# and forbidden strings; only the long-hex / entropy heuristic is skipped for them.
HASH_COLUMNS = frozenset({
    "load_id", "session_id", "task_key", "cluster_key", "version_id", "content_sha256",
    "call_id", "batch_id",
})
# Non-table JSON keys holding a legitimate hash.
HASH_KEYS = HASH_COLUMNS | {"extractor_git_sha", "manifest_sha256", "sha256"}

TOKEN_PATTERNS = {
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    "provider_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    "bearer_token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    "basic_auth": re.compile(r"(?i)\bauthorization\s*:"),
}
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
ABS_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=(:,])"
    r"(?:~[\\/]|"
    r"/(?:home|Users|root|tmp|var|etc|opt|mnt|srv|usr|private|proc|sys)/|"
    r"[A-Za-z]:[\\/])"
)
HEX_RE = re.compile(r"[0-9a-fA-F]{32,}")
BLOB_RE = re.compile(r"[A-Za-z0-9+/_=-]{40,}")
TEXT_SUFFIXES = frozenset({".jsonl", ".json", ".csv", ".md", ".txt", ".sha256", ".yaml", ".yml"})
BINARY_SUFFIXES = frozenset({".png", ".zip", ".parquet", ".db", ".sqlite", ".gz", ".pdf"})


class PrivacyError(ValueError):
    """An exported file looks like it carries private text, a secret, a URL or an absolute path."""


# ---------------------------------------------------------------- value scans
def _looks_like_blob(text: str) -> bool:
    """Long hex, or a long base64-ish token that is not a plain word (digit + symbol/upper case)."""
    if HEX_RE.fullmatch(text):
        return True
    if BLOB_RE.fullmatch(text):
        return any(ch.isdigit() for ch in text) and any(ch.isupper() or ch in "+/_-=" for ch in text)
    return False


def _blob_token(text: str) -> str | None:
    """First long hex/base64 token inside a longer string (a leaked hash rarely stands alone)."""
    for token in re.split(r"[\s\"',:\[\]{}]+", text):
        if token and _looks_like_blob(token):
            return token
    return None


def scan_string(name: str, text: str, forbidden=(), hex_check: bool = True) -> None:
    """Raise PrivacyError naming ``name`` when one string value fails the backstop."""
    for label, rx in TOKEN_PATTERNS.items():
        if rx.search(text):
            raise PrivacyError(f"{name}: credential pattern {label} in an exported value")
    if URL_RE.search(text):
        raise PrivacyError(f"{name}: URL in an exported value")
    if ABS_PATH_RE.search(text):
        raise PrivacyError(f"{name}: absolute path in an exported value")
    for needle in forbidden:
        if needle and needle in text:
            raise PrivacyError(f"{name}: forbidden string in an exported value")
    if hex_check and (_looks_like_blob(text.strip()) or _blob_token(text)):
        raise PrivacyError(f"{name}: long hex/base64 blob in an exported value")


def scan_text(name: str, text: str, forbidden=(), hex_check: bool = False) -> None:
    """Raw scan of a whole exported file (any format)."""
    scan_string(name, text, forbidden=forbidden, hex_check=False)
    if hex_check and _blob_token(text):
        raise PrivacyError(f"{name}: long hex/base64 blob in an exported file")


def _walk_json(obj, key: str | None = None):
    """Yield (key, string) for every string in a decoded JSON document."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_json(v, str(k))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_json(v, key)
    elif isinstance(obj, str):
        yield key, obj


# ---------------------------------------------------------------- file scans
def _check_table_file(path: Path, forbidden) -> None:
    table = path.stem
    rows = io.read_jsonl(path)
    try:
        schema.validate_rows(table, rows)
    except ValueError as exc:
        raise PrivacyError(f"{path.name}: schema allowlist violation: {exc}") from exc
    for row in rows:
        for col, value in row.items():
            for text in _strings(value):
                scan_string(f"{path.name}[{col}]", text, forbidden=forbidden,
                            hex_check=col not in HASH_COLUMNS)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _check_json_file(path: Path, forbidden) -> None:
    data = io.read_json(path)
    for key, text in _walk_json(data):
        scan_string(path.name, text, forbidden=forbidden, hex_check=key not in HASH_KEYS)


def _check_csv_file(path: Path, forbidden) -> None:
    for row in io.read_csv(path):
        for col, value in row.items():
            if value is None:
                continue
            scan_string(f"{path.name}[{col}]", str(value), forbidden=forbidden,
                        hex_check=col not in HASH_COLUMNS)


def _check_checksums_file(path: Path, forbidden) -> None:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, sep, name = line.partition("  ")
        if not sep or not re.fullmatch(r"[0-9a-f]{64}", digest) or not name:
            raise PrivacyError(f"{path.name}: malformed checksum line")
        scan_text(path.name, name, forbidden=forbidden, hex_check=False)


def _check_free_text_file(path: Path, forbidden) -> None:
    scan_text(path.name, path.read_text(encoding="utf-8"), forbidden=forbidden, hex_check=False)


def check_corpus_dir(path, forbidden=()) -> None:
    """Validate one corpus directory. Raises PrivacyError naming the offending file."""
    root = Path(path)
    if not root.is_dir():
        raise PrivacyError(f"{root.name}: corpus directory not found")
    forbidden = [f for f in forbidden if f]
    known_tables = set(schema.TABLES)
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        if suffix in BINARY_SUFFIXES:
            continue
        if suffix not in TEXT_SUFFIXES:
            continue
        name = file_path.name
        if suffix == ".jsonl" and name[:-6] in known_tables:
            _check_table_file(file_path, forbidden)
        elif name == schema.CHECKSUMS_FILE:
            _check_checksums_file(file_path, forbidden)
        elif suffix == ".json":
            _check_json_file(file_path, forbidden)
        elif suffix == ".csv":
            _check_csv_file(file_path, forbidden)
        elif suffix == ".jsonl":
            # not a schema table: treat as free text with the raw backstop
            _check_free_text_file(file_path, forbidden)
        else:
            _check_free_text_file(file_path, forbidden)