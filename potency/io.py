"""Deterministic, cross-platform file I/O (design D17). Stdlib only."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Iterable

from potency import schema

FLOAT_DIGITS = 6


def _clean(o):
    """Round floats and sort nested dict keys so output is byte-identical across platforms."""
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
        r = round(o, FLOAT_DIGITS)
        return 0.0 if r == 0 else r
    if isinstance(o, dict):
        return {str(k): _clean(o[k]) for k in sorted(o, key=str)}
    if isinstance(o, (list, tuple)):
        return [_clean(x) for x in o]
    return o


def dumps(obj) -> str:
    return json.dumps(_clean(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_jsonl(path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(dumps(row) + "\n")
            n += 1
    return n


def read_jsonl(path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_json(path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(_clean(obj), ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def fmt_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        s = f"{v:.{FLOAT_DIGITS}f}"
        return "0.000000" if s in ("-0.000000",) else s
    if isinstance(v, (list, tuple)):
        return " ".join(str(x) for x in v)
    return str(v)


def write_csv(path, rows: Iterable[dict], columns: list[str]) -> int:
    """Write rows with a fixed column order, fixed float format and LF line endings."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for row in rows:
            w.writerow([fmt_cell(row.get(c)) for c in columns])
            n += 1
    return n


def read_csv(path) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_output_csv(path, rows: Iterable[dict], name: str | None = None) -> int:
    """Write one of the schema.OUTPUT_COLUMNS files (name defaults to the file name)."""
    name = name or Path(path).name
    return write_csv(path, rows, schema.OUTPUT_COLUMNS[name])


def write_table(corpus_dir, table: str, rows: list[dict], validate: bool = True) -> int:
    if validate:
        schema.validate_rows(table, rows)
    return write_jsonl(Path(corpus_dir) / f"{table}.jsonl", rows)


def read_table(corpus_dir, table: str) -> list[dict]:
    p = Path(corpus_dir) / f"{table}.jsonl"
    return read_jsonl(p) if p.exists() else []


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_checksums(directory, names: Iterable[str]) -> Path:
    """Write <directory>/checksums.sha256 in `sha256sum` format for the given relative names."""
    directory = Path(directory)
    lines = [f"{sha256_file(directory / n)}  {n}" for n in sorted(names)]
    out = directory / schema.CHECKSUMS_FILE
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return out


def verify_checksums(directory) -> None:
    """Raise ValueError naming the first file whose checksum does not match."""
    directory = Path(directory)
    path = directory / schema.CHECKSUMS_FILE
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            digest, name = line.rstrip("\n").split("  ", 1)
            target = directory / name
            if not target.exists():
                raise ValueError(f"checksum: missing file {name}")
            if sha256_file(target) != digest:
                raise ValueError(f"checksum mismatch: {name}")


def resolve_data_dir(arg: str | None) -> Path:
    """CLI --data value, else $POTENCY_DATA_DIR, else ./data."""
    return Path(arg or os.environ.get("POTENCY_DATA_DIR") or "data")


def corpus_dirs(data_dir, corpus: str | None = None) -> list[Path]:
    """Corpus directories under data_dir (those holding a sessions.jsonl), sorted."""
    data_dir = Path(data_dir)
    if corpus:
        return [data_dir / corpus]
    return sorted(p for p in data_dir.iterdir() if (p / "sessions.jsonl").exists())
