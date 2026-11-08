"""Claude Code JSONL adapter: raw transcripts -> the six D12 tables (design D14, D15, D21; tasks 3.1-3.2).

Streams a directory of raw Claude Code transcripts (``<source>/transcripts/*.jsonl``, else
``<source>/*.jsonl``) one file at a time, so a 4,900-file / 9.6 GB corpus never has to fit in memory.
``sessions.parquet``/``sessions.csv`` metadata supplies ``repo_id`` (cluster key), ``user_id``,
``cli_version`` and ``created_at``.

Loads are assistant ``tool_use`` items named ``Skill`` whose ``tool_result`` is not ``is_error``;
``skill_listing`` and ``invoked_skills`` attachments are not loads. The skill body injected on the
following ``isMeta`` user line (``sourceToolUseID`` == the call id) is the version in force, so its
rule set is the auto-extracted one (design D13/D14).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from potency import normalize, schema

#: Record types with no extractable steps (design D8); attachments never hold a load (D21).
SKIP_TYPES = frozenset({
    "progress", "file-history-snapshot", "system", "queue-operation", "custom-title", "agent-name",
    "pr-link", "attachment", "summary",
})
#: Input keys that carry the skill name, in priority order (design D21).
SKILL_INPUT_KEYS = ("skill", "skillName", "skill_name", "name")
#: Signatures that mean the load was opened in order to edit that skill (design D8, generic).
MAINTENANCE_SIGNATURES = frozenset({"skill_manage"})
TASK_KEY_CHARS = 16
_SUFFIX_KEY_LEN = 12
_WS = re.compile(r"\s+")


# ------------------------------------------------------------------ small parsing helpers
def _first_float(*values) -> float:
    """First value that is a real float (missing metadata timestamps can be None or NaT)."""
    for v in values:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            return float(v)
    return 0.0


def _epoch(value) -> float | None:
    """Epoch seconds from a Claude Code timestamp (ISO 8601 string), a number, or a pandas timestamp."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None  # NaN -> None
    if hasattr(value, "to_pydatetime"):  # pandas.Timestamp: replace() below pins the timezone
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        try:
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, OverflowError):  # pandas.NaT and out-of-range values
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _text_of(content) -> str | None:
    """Text of a message content value (a string, or text blocks); None when there is no text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(item.get("text"))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text") is not None
        ]
        return "\n".join(parts) if parts else None
    return None


def _skill_name(args: dict) -> str | None:
    for key in SKILL_INPUT_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _top(counter: Counter) -> str | None:
    """Most common value, ties broken by name so the result is platform-stable."""
    if not counter:
        return None
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _normalize_prompt(text: str) -> str:
    """Lower-case, digits (and therefore dates) stripped, whitespace collapsed (design D15)."""
    return _WS.sub(" ", re.sub(r"\d", "", text.lower())).strip()


def _task_key(prompt: str | None) -> str | None:
    if not prompt:
        return None
    body = _normalize_prompt(prompt)
    if not body:
        return None
    return sha256(body.encode("utf-8")).hexdigest()[:TASK_KEY_CHARS]


def _trigger(skill: str, user_text: str | None) -> str:
    """`instructed` when the latest user text names the skill, else `chosen` (design D7 trigger split)."""
    if user_text and skill.lower() in user_text.lower():
        return "instructed"
    return "chosen"


def _step(corpus: str, session_id: str, step: int, offset: int, call_id: str, batch_id: str,
          ts: float | None, kind: str, signature: str, attribution: str | None) -> dict:
    return {
        "corpus": corpus,
        "session_id": session_id,
        "step": step,
        "source_offset": offset,
        "call_id": call_id,
        "batch_id": batch_id,
        "ts": ts,
        "kind": kind,
        "signature": signature,
        "status": "unknown",
        "attribution_skill": attribution,
    }


# ------------------------------------------------------------------ metadata join
class _Meta:
    """`sessions.parquet`/`sessions.csv` rows, looked up by session id or by id suffix."""

    def __init__(self, rows: dict[str, dict]):
        self.rows = rows
        self._order = sorted(rows)
        self._tail: dict[str, list[str]] = {}
        for sid in self._order:
            self._tail.setdefault(sid[-_SUFFIX_KEY_LEN:], []).append(sid)

    def get(self, session_id: str) -> dict:
        row = self.rows.get(session_id)
        if row is not None:
            return row
        # SWE-chat ids look like "2026-01-05-<uuid>"; the file stem may be the uuid alone.
        for sid in self._tail.get(session_id[-_SUFFIX_KEY_LEN:], ()):
            if sid.endswith(session_id):
                return self.rows[sid]
        for sid in self._order:
            if sid.endswith(session_id):
                return self.rows[sid]
        return {}


def _meta_value(value):
    """Plain-python metadata cell: NaN -> None, timestamps -> ISO text."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _read_meta(path: Path | None) -> _Meta:
    if path is None:
        return _Meta({})
    path = Path(path)
    if not path.is_file():
        return _Meta({})
    rows: dict[str, dict] = {}
    if path.suffix.lower() == ".parquet":
        import pandas as pd

        frame = pd.read_parquet(path)
        for record in frame.to_dict(orient="records"):
            cell = {str(k): _meta_value(v) for k, v in record.items()}
            sid = cell.get("session_id")
            if sid:
                rows[str(sid)] = cell
    else:
        import csv

        with open(path, "r", encoding="utf-8", newline="") as fh:
            for record in csv.DictReader(fh):
                sid = record.get("session_id")
                if sid:
                    rows[str(sid)] = {str(k): v for k, v in record.items()}
    return _Meta(rows)


def _default_meta(source: Path) -> Path | None:
    for name in ("sessions.parquet", "sessions.csv"):
        candidate = source / name
        if candidate.is_file():
            return candidate
    return None


def _transcript_files(source: Path) -> list[Path]:
    nested = source / "transcripts"
    if nested.is_dir():
        return sorted(p for p in nested.glob("*.jsonl") if p.is_file())
    return sorted(p for p in source.glob("*.jsonl") if p.is_file())


# ------------------------------------------------------------------ one transcript
def _parse_transcript(path: Path, corpus: str) -> dict:
    """Stream one JSONL transcript into steps, load candidates and its session facts."""
    session_id = path.stem
    steps: list[dict] = []
    pending: dict[str, list[int]] = {}  # call id -> step indices waiting for a result
    injected: dict[str, str] = {}  # call id -> skill body injected after the call
    loads: list[dict] = []
    models: Counter = Counter()
    versions: Counter = Counter()
    user_text: str | None = None
    first_prompt: str | None = None
    min_ts: float | None = None
    max_ts: float | None = None

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for offset, raw in enumerate(fh):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except (ValueError, TypeError):  # partial or non-JSON line in a truncated transcript
                continue
            if not isinstance(record, dict):
                continue
            typ = record.get("type")
            if typ in SKIP_TYPES:
                continue
            ts = _epoch(record.get("timestamp"))
            if ts is not None:
                min_ts = ts if min_ts is None else min(min_ts, ts)
                max_ts = ts if max_ts is None else max(max_ts, ts)
            version = record.get("version")
            if isinstance(version, str) and version:
                versions[version] += 1
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None

            if typ == "assistant":
                model = message.get("model") if isinstance(message, dict) else None
                if isinstance(model, str) and model:
                    models[model] += 1
                attribution = record.get("attributionSkill")
                attribution = attribution if isinstance(attribution, str) and attribution else None
                batch_id = f"{session_id}:{offset}"
                items = content if isinstance(content, list) else []
                for index, item in enumerate(items):
                    if not isinstance(item, dict) or item.get("type") != "tool_use":
                        continue
                    name = str(item.get("name") or "")
                    call_id = str(item.get("id") or f"{session_id}-c{offset}-{index}")
                    args = item.get("input") if isinstance(item.get("input"), dict) else {}
                    skill = _skill_name(args) if name.strip().lower() == "skill" else None
                    if skill is not None:
                        step = len(steps)
                        steps.append(_step(corpus, session_id, step, offset, call_id, batch_id, ts,
                                           "load", f"load: {skill}", attribution))
                        pending.setdefault(call_id, []).append(step)
                        loads.append({"step": step, "ts": ts, "skill": skill, "call_id": call_id,
                                      "trigger": _trigger(skill, user_text)})
                        continue
                    shell = name.strip().lower() in normalize.SHELL_TOOLS
                    for signature in normalize.tool_signatures(name, args):
                        step = len(steps)
                        steps.append(_step(corpus, session_id, step, offset, call_id, batch_id, ts,
                                           "shell" if shell else "tool", signature, attribution))
                        pending.setdefault(call_id, []).append(step)

            elif typ == "user":
                if record.get("isMeta") is True:
                    source_id = record.get("sourceToolUseID")
                    body = _text_of(content)
                    if isinstance(source_id, str) and body is not None:
                        injected[source_id] = body
                    continue
                results = [it for it in content
                           if isinstance(it, dict) and it.get("type") == "tool_result"] \
                    if isinstance(content, list) else []
                if results:
                    for result in results:
                        status = "error" if result.get("is_error") else "ok"
                        for index in pending.get(str(result.get("tool_use_id") or ""), ()):
                            steps[index]["status"] = status
                    continue
                text = _text_of(content)
                if text:
                    if first_prompt is None:
                        first_prompt = text
                    user_text = text

            elif isinstance(content, list):  # other record types: keep tool calls, never user text
                batch_id = f"{session_id}:{offset}"
                for index, item in enumerate(content):
                    if not isinstance(item, dict) or item.get("type") != "tool_use":
                        continue
                    name = str(item.get("name") or "")
                    call_id = str(item.get("id") or f"{session_id}-c{offset}-{index}")
                    args = item.get("input") if isinstance(item.get("input"), dict) else {}
                    shell = name.strip().lower() in normalize.SHELL_TOOLS
                    for signature in normalize.tool_signatures(name, args):
                        step = len(steps)
                        steps.append(_step(corpus, session_id, step, offset, call_id, batch_id, ts,
                                           "shell" if shell else "tool", signature, None))
                        pending.setdefault(call_id, []).append(step)

    return {
        "session_id": session_id,
        "steps": steps,
        "loads": loads,
        "injected": injected,
        "models": models,
        "versions": versions,
        "task_key": _task_key(first_prompt),
        "start_ts": min_ts if min_ts is not None else 0.0,
    }


# ------------------------------------------------------------------ the adapter
def extract(source: Path, corpus: str, sessions_meta: Path | None = None) -> dict[str, list[dict]]:
    """Extract the six D12 tables from a directory of raw Claude Code transcripts.

    ``source`` holds ``transcripts/*.jsonl`` (or ``*.jsonl``); ``sessions_meta`` defaults to
    ``<source>/sessions.parquet``, then ``<source>/sessions.csv``. Files are read one at a time.
    """
    source = Path(source)
    meta = _read_meta(Path(sessions_meta) if sessions_meta is not None else _default_meta(source))

    sessions: list[dict] = []
    steps: list[dict] = []
    loads: list[dict] = []
    skill_versions: list[dict] = []
    rules: list[dict] = []
    provenance: list[dict] = []
    seen_versions: dict[tuple[str, str], dict] = {}
    loaded_skills: set[str] = set()

    for path in _transcript_files(source):
        parsed = _parse_transcript(path, corpus)
        sid = parsed["session_id"]
        session_steps = parsed["steps"]
        row = meta.get(sid)

        successful = [ld for ld in parsed["loads"] if session_steps[ld["step"]]["status"] != "error"]
        load_steps = {ld["step"] for ld in successful}
        maintenance_steps = {st["step"] for st in session_steps
                             if st["signature"] in MAINTENANCE_SIGNATURES}
        last = len(session_steps) - 1
        seen_skills: set[str] = set()
        session_loads: list[dict] = []
        for ld in successful:
            step, skill = ld["step"], ld["skill"]
            flags: list[str] = []
            if skill in seen_skills:
                flags.append("repeat")
            seen_skills.add(skill)
            if step + schema.WINDOW_N > last:
                flags.append("incomplete")
            window_end = min(step + schema.WINDOW_N, last)
            if any(step < other <= window_end for other in load_steps if other != step):
                flags.append("overlap")
            if any(step < other <= window_end for other in maintenance_steps):
                flags.append("maintenance")

            body = parsed["injected"].get(ld["call_id"])
            if body is not None:
                version_id: str | None = schema.content_id(body)
                version_source = "injected"
            else:
                version_id, version_source = None, "version_unknown"

            loads.append({
                "corpus": corpus,
                "session_id": sid,
                "load_id": schema.episode_id(corpus, sid, step),
                "skill": skill,
                "step": step,
                "ts": ld["ts"],
                "trigger": ld["trigger"],
                "version_id": version_id,
                "version_source": version_source,
                "flags": sorted(flags),
                "cluster_key": "",  # filled in below, once the session row is known
                "split": "",
            })
            session_loads.append(loads[-1])
            loaded_skills.add(skill)

            if body is not None and version_id is not None:
                seen = seen_versions.get((skill, version_id))
                if seen is None:
                    seen_versions[(skill, version_id)] = {
                        "corpus": corpus,
                        "skill": skill,
                        "version_id": version_id,
                        "version_source": "injected",
                        "valid_from_ts": ld["ts"],
                        "content_sha256": sha256(body.encode("utf-8")).hexdigest(),
                        "body": body,
                    }
                elif ld["ts"] is not None:
                    if seen["valid_from_ts"] is None or ld["ts"] < seen["valid_from_ts"]:
                        seen["valid_from_ts"] = ld["ts"]

        cluster_key = str(row.get("repo_id") or row.get("user_id") or sid)
        sessions.append({
            "corpus": corpus,
            "session_id": sid,
            "start_ts": _first_float(_epoch(row.get("created_at")), parsed["start_ts"], 0.0),
            "source": None,  # Claude Code transcripts carry no session source
            "task_key": parsed["task_key"],
            "cluster_key": cluster_key,
            "model": _top(parsed["models"]) or (str(row["model"]) if row.get("model") else None),
            "harness_version": str(row["cli_version"]) if row.get("cli_version") else _top(parsed["versions"]),
            "pair_id": None,
            "pair_arm": None,
            "split": "",
        })
        for load in session_loads:
            load["cluster_key"] = cluster_key
        steps.extend(session_steps)

    # temporal split: ~70% train by session start, one cutoff per corpus (design D8)
    ordered = sorted(sessions, key=lambda s: (s["start_ts"], s["session_id"]))
    cut = int(len(ordered) * schema.TRAIN_SHARE)
    train = {s["session_id"] for s in ordered[:cut]}
    for session in sessions:
        session["split"] = "train" if session["session_id"] in train else "test"
    for load in loads:
        load["split"] = "train" if load["session_id"] in train else "test"

    # injected versions and their auto-extracted rules (design D13/D14)
    for (skill, version_id), version in sorted(seen_versions.items()):
        skill_versions.append({k: v for k, v in version.items() if k != "body"})
        for index, signature in enumerate(normalize.extract_commands(version["body"]), start=1):
            rules.append({
                "corpus": corpus,
                "skill": skill,
                "version_id": version_id,
                "rule_id": f"r{index}",
                "obligation": "required",
                "applicability": None,  # unknown: never a failure, only "insufficient evidence"
                "observable": [signature],
                "alternatives": [],
                "location": None,
                "rule_source": "auto",
                "approved": False,
                "in_core": None,
            })

    for skill in sorted(loaded_skills):
        provenance.append({
            "corpus": corpus,
            "skill": skill,
            "created_ts": None,
            "created_by": None,
            "agent_touched": False,
            "changes": [],
        })

    sessions.sort(key=lambda s: s["session_id"])
    steps.sort(key=lambda s: (s["session_id"], s["step"]))
    loads.sort(key=lambda ld: (ld["session_id"], ld["step"]))
    return {
        "sessions": sessions,
        "steps": steps,
        "loads": loads,
        "skill_versions": skill_versions,
        "rules": rules,
        "provenance": provenance,
    }


# ------------------------------------------------------------------ corpus registry
def load_registry(path) -> dict[str, dict]:
    """Read ``corpora.yaml`` into ``{corpus_name: entry}`` (design D12).

    Accepts a top-level mapping of names to entries, a ``corpora:`` mapping, or a list of entries
    carrying ``name``.
    """
    import yaml

    with open(Path(path), "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if isinstance(data, dict) and "corpora" in data:
        data = data["corpora"]
    if isinstance(data, list):
        return {str(entry["name"]): dict(entry) for entry in data if entry.get("name")}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping of corpus entries")
    return {str(name): dict(entry or {}) for name, entry in sorted(data.items(), key=lambda kv: str(kv[0]))}