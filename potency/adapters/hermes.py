"""Hermes corpus adapter (design D12, D14, D15, D16, D21). Stdlib only.

``extract(home, corpus)`` reads a Hermes home -- ``state.db``, ``skills/``, ``skills/.usage.json``,
``skills/.curator_ledger.jsonl``, ``cron/jobs.json`` -- in one read transaction and returns the six D12
tables. Nothing private leaves the module: no prompt text, search query, tool argument, filesystem path
or skill body is written to any table. Only signatures, skill names, labels, flags, hashes, counts and
timestamps are exported.

Real Hermes installs differ slightly by version, so columns and tables are read defensively (see
``_select``), and rows with a role the adapter does not know are ignored.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from potency import normalize, schema

ADAPTER_VERSION = "1"

SKILL_VIEW = "skill_view"
MANAGE_TOOL = "skill_manage"
RESULT_ROLES = {"tool", "tool_result", "function"}
WRITE_TOOLS = {
    "write_file", "edit_file", "create_file", "patch", "apply_patch", "str_replace", "multi_edit", "write",
}
PATH_KEYS = ("path", "file_path", "filePath", "file", "target")
SKILL_NAME_KEYS = ("name", "skill", "skillName", "skill_name")
MANAGE_CONTENT_ACTIONS = {"create", "patch", "replace", "write", "write_file", "update", "edit", "create_file"}
_DATE_RE = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}")
_KEEP_RE = re.compile(r"[^a-z' ]+")


# ---------------------------------------------------------------- small helpers
def _epoch(value) -> float | None:
    """Epoch seconds from a REAL column or an ISO-8601 string; None when unusable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def normalize_prompt(text) -> str:
    """Lowercase, dates and digits stripped, punctuation collapsed (design D15).

    Only ever used on the source machine; the digest is what leaves.
    """
    if not isinstance(text, str):
        return ""
    out = text.lower()
    out = _DATE_RE.sub(" ", out)
    out = _KEEP_RE.sub(" ", out)
    return " ".join(out.split())


def prompt_key(text) -> str | None:
    digest = normalize_prompt(text)
    if not digest:
        return None
    return hashlib.sha256(digest.encode("utf-8")).hexdigest()[:16]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_json_arg(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_str(args: dict, keys) -> str | None:
    if not isinstance(args, dict):
        return None
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _read_json_file(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- result status (D8)
def _dict_status(obj: dict) -> str:
    if obj.get("error") or obj.get("is_error") or obj.get("isError"):
        return "error"
    if obj.get("success") is False or obj.get("ok") is False:
        return "error"
    for key in ("exit_code", "exitCode", "returncode", "return_code"):
        code = obj.get(key)
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            return "error"
    return "ok"


def result_status(content) -> str:
    """Status of a tool result: error / ok / unknown (no result was recorded)."""
    if content is None:
        return "unknown"
    if isinstance(content, dict):
        return _dict_status(content)
    if not isinstance(content, str):
        return "ok"
    text = content.strip()
    if not text:
        return "ok"
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return _dict_status(parsed)
    lowered = text.lower()
    if lowered.startswith(("error", "traceback", "exception")) or "<tool_use_error>" in lowered:
        return "error"
    return "ok"


# ---------------------------------------------------------------- read-only snapshot (D12)
def _open_readonly(db_path: Path) -> sqlite3.Connection:
    # quote() keeps spaces, '#', '?' and unicode in a Windows or macOS home out of the URI syntax
    uri = "file:" + quote(Path(db_path).resolve().as_posix(), safe="/:") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.isolation_level = None  # explicit BEGIN/COMMIT so the snapshot is one read transaction
    conn.execute("BEGIN")
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _select(conn: sqlite3.Connection, table: str, wanted) -> list[dict]:
    available = _columns(conn, table)
    if not available:
        raise ValueError(f"hermes state.db has no {table} table")
    use = [col for col in wanted if col in available]
    if not use:
        raise ValueError(f"hermes {table} table has none of the expected columns")
    sql = f"SELECT {', '.join(use)} FROM {table} ORDER BY rowid"
    return [dict(zip(use, row)) for row in conn.execute(sql)]


# ---------------------------------------------------------------- source files
def _read_skills(skills_root: Path) -> dict[str, dict]:
    """skill name -> {path, text, sha256} for every SKILL.md under the skills root."""
    found: dict[str, dict] = {}
    if not skills_root.is_dir():
        return found
    for path in sorted(skills_root.rglob("SKILL.md")):
        if not path.is_file():
            continue
        name = path.parent.name
        if name in found:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        found[name] = {"path": path, "text": data.decode("utf-8", errors="replace"),
                       "sha256": _sha256_bytes(data)}
    return found


def _read_ledger(path: Path) -> list[dict]:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _read_usage(path: Path) -> dict:
    data = _read_json_file(path)
    return data if isinstance(data, dict) else {}


def _read_cron_jobs(path: Path) -> list[dict]:
    data = _read_json_file(path)
    if isinstance(data, dict):
        data = data.get("jobs") or data.get("cron") or []
    if not isinstance(data, list):
        return []
    return [job for job in data if isinstance(job, dict)]


def _job_skills(job: dict) -> list[str]:
    skills = job.get("skills")
    if isinstance(skills, str):
        skills = [skills]
    if not isinstance(skills, list):
        skills = []
    names = [s for s in skills if isinstance(s, str) and s.strip()]
    single = job.get("skill")
    if isinstance(single, str) and single.strip():
        names.append(single)
    out, seen = [], set()
    for name in names:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _job_id(job: dict) -> str | None:
    for key in ("id", "job_id", "name"):
        value = job.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return prompt_key(job.get("prompt"))


def _job_index(jobs: list[dict]) -> dict:
    by_prompt, by_hash = {}, {}
    for job in jobs:
        key = prompt_key(job.get("prompt") or job.get("message") or job.get("content"))
        if key and key not in by_prompt:
            by_prompt[key] = job
        for field in ("system_prompt_hash", "systemPromptHash"):
            value = job.get(field)
            if isinstance(value, str) and value.strip() and value not in by_hash:
                by_hash[value.strip()] = job
    return {"by_prompt": by_prompt, "by_hash": by_hash}


# ---------------------------------------------------------------- message parsing (D8)
def _parse_calls(raw) -> list[dict]:
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return []
    if isinstance(data, dict):
        data = data.get("tool_calls") or data.get("calls") or []
    if not isinstance(data, list):
        return []
    calls = []
    for item in data:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else item
        name = fn.get("name") or item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        args = fn.get("arguments")
        if args is None:
            args = item.get("arguments")
        call_id = item.get("id") or item.get("tool_call_id") or item.get("tool_use_id")
        calls.append({
            "id": str(call_id) if call_id else "",
            "name": name.strip(),
            "args": _parse_json_arg(args),
        })
    return calls


def _manage_content(args: dict) -> str | None:
    """Skill body after one ``skill_manage`` call, in either recorded format (design D14)."""
    action = args.get("action")
    content = args.get("content")
    if isinstance(action, str) and action.lower() in ("delete", "archive", "remove"):
        return None
    if isinstance(content, dict):
        content = content.get("text") or content.get("content")
    if isinstance(content, str) and content.strip():
        return content
    operations = args.get("operations")
    if isinstance(operations, dict):
        operations = [operations]
    if isinstance(operations, list):
        texts = []
        for op in operations:
            if not isinstance(op, dict):
                continue
            if (op.get("op") or op.get("action") or "").lower() in ("delete", "remove"):
                continue
            for key in ("text", "content", "new_text", "new", "after"):
                value = op.get(key)
                if isinstance(value, str) and value.strip():
                    texts.append(value)
                    break
        if texts:
            return "\n".join(texts)
    return None


# ---------------------------------------------------------------- per-session scan
def _scan_session(session_id: str, msgs: list[dict], preloads: list[str], start_ts: float,
                  skill_dirs: dict[str, tuple[str, ...]] | None = None) -> dict:
    """Turn one session's messages into ordered steps, call records and successful load steps."""
    results: dict[str, object] = {}
    for msg in msgs:
        if (msg.get("role") or "").lower() in RESULT_ROLES:
            call_id = msg.get("tool_call_id") or msg.get("tool_use_id")
            if call_id:
                results[str(call_id)] = msg.get("content")

    steps: list[dict] = []
    calls: list[dict] = []
    for skill in preloads:
        steps.append({
            "source_offset": -1, "call_id": f"preload:{skill}", "batch_id": f"preload:{session_id}",
            "ts": start_ts, "kind": "load", "signature": f"load: {skill}", "status": "ok",
            "attribution_skill": None, "_skill": skill, "_prompt": None, "_preload": True,
        })

    prompt: str | None = None
    for msg in msgs:
        role = (msg.get("role") or "").lower()
        content = msg.get("content")
        if role == "user":
            if isinstance(content, str) and content.strip():
                prompt = content
            continue
        if role != "assistant":
            continue
        batch_id = f"m{msg.get('id')}"
        ts = _epoch(msg.get("timestamp"))
        for index, call in enumerate(_parse_calls(msg.get("tool_calls"))):
            name = call["name"]
            args = call["args"]
            call_id = call["id"] or f"{batch_id}-{index}"
            status = result_status(results.get(call_id))
            lowered = name.lower()
            record = {
                "ts": ts, "msg_id": msg.get("id"), "index": index, "call_id": call_id, "name": lowered,
                "args": args, "skill": _first_str(args, SKILL_NAME_KEYS),
            }
            if lowered == SKILL_VIEW:
                skill = record["skill"] or "unknown"
                steps.append({
                    "source_offset": int(msg.get("id") or 0), "call_id": call_id, "batch_id": batch_id,
                    "ts": ts, "kind": "load", "signature": f"load: {skill}", "status": status,
                    "attribution_skill": None, "_skill": skill if record["skill"] else None, "_prompt": prompt,
                })
                record["step_index"] = len(steps) - 1
                calls.append(record)
                continue
            signatures = normalize.tool_signatures(name, args)
            write_skill = _write_target_skill(args, skill_dirs or {}) if lowered in WRITE_TOOLS else None
            first = len(steps)
            for signature in signatures:
                steps.append({
                    "source_offset": int(msg.get("id") or 0), "call_id": call_id, "batch_id": batch_id,
                    "ts": ts,
                    "kind": "shell" if signature.startswith(normalize.SHELL_PREFIX) else "tool",
                    "signature": signature, "status": status, "attribution_skill": None,
                    "_prompt": prompt, "_call_name": lowered,
                    "_call_skill": record["skill"] if lowered == MANAGE_TOOL else None,
                    "_write_skill": write_skill,
                })
            record["step_index"] = first
            calls.append(record)
    for number, step in enumerate(steps):
        step["step"] = number
    return {"steps": steps, "calls": calls}


def _write_target_skill(args: dict, skill_dirs: dict[str, tuple[str, ...]]) -> str | None:
    """Skill whose files a write tool rewrites, matched from the unexported path argument."""
    raw = _first_str(args, PATH_KEYS)
    if not raw:
        return None
    parts = tuple(p for p in re.split(r"[\\/]+", raw) if p)
    matches = [skill for skill, segments in skill_dirs.items()
               if segments and _is_suffix_window(parts, segments)]
    return matches[0] if len(matches) == 1 else None


def _is_suffix_window(parts: tuple[str, ...], segments: tuple[str, ...]) -> bool:
    n = len(segments)
    return any(parts[i:i + n] == segments for i in range(len(parts) - n + 1))


# ---------------------------------------------------------------- version bookkeeping (D14)
# Same text, different evidence: keep the strongest source (design D14 priority order).
VERSION_PRIORITY = {"injected": 0, "ledger": 1, "skill_manage": 2, "version_core": 3, "version_unknown": 4}


class _Versions:
    """Known skill texts, their ids and the rules extracted from them."""

    def __init__(self, corpus: str):
        self.corpus = corpus
        self.specs: dict[tuple[str, str], dict] = {}
        self.manage: dict[str, list[dict]] = {}

    def add(self, skill: str, content: str, source: str, valid_from_ts: float | None,
            in_core_mode: bool) -> str:
        version_id = schema.content_id(content)
        key = (skill, version_id)
        spec = self.specs.get(key)
        if spec is None:
            self.specs[key] = {
                "skill": skill, "version_id": version_id, "content": content, "source": source,
                "valid_from_ts": valid_from_ts, "in_core_mode": in_core_mode,
            }
        else:
            if VERSION_PRIORITY[source] < VERSION_PRIORITY[spec["source"]]:
                spec["source"] = source
            if spec["valid_from_ts"] is None or (valid_from_ts is not None and valid_from_ts < spec["valid_from_ts"]):
                spec["valid_from_ts"] = valid_from_ts
            spec["in_core_mode"] = spec["in_core_mode"] or in_core_mode
        return version_id

    def add_manage(self, skill: str, content: str, ts: float | None, order) -> str:
        version_id = self.add(skill, content, "skill_manage", ts, in_core_mode=False)
        self.manage.setdefault(skill, []).append({"ts": ts, "order": order, "content": content,
                                                  "version_id": version_id})
        self.manage[skill].sort(key=lambda m: (m["ts"] is None, m["ts"] or 0.0, m["order"]))
        return version_id

    def latest_manage(self, skill: str, ts: float | None) -> dict | None:
        if ts is None:
            return None
        found = None
        for record in self.manage.get(skill, []):
            if record["ts"] is not None and record["ts"] <= ts:
                found = record
        return found

    def earliest_text(self, skill: str, current: str | None) -> str | None:
        texts = [m for m in self.manage.get(skill, []) if m["ts"] is not None]
        if texts:
            return min(texts, key=lambda m: (m["ts"], m["order"]))["content"]
        return current

    def table_rows(self) -> list[dict]:
        rows = []
        for (skill, version_id), spec in sorted(self.specs.items()):
            rows.append({
                "corpus": self.corpus, "skill": skill, "version_id": version_id,
                "version_source": spec["source"], "valid_from_ts": spec["valid_from_ts"],
                "content_sha256": _sha256_bytes(spec["content"].encode("utf-8")),
            })
        return rows

    def rule_rows(self) -> list[dict]:
        rows = []
        for (skill, version_id), spec in sorted(self.specs.items()):
            content = spec["content"]
            commands = normalize.extract_commands(content)
            core = None
            if spec["in_core_mode"]:
                core = set(normalize.extract_commands(self.earliest_text(skill, content) or content))
            for number, signature in enumerate(commands, start=1):
                rows.append({
                    "corpus": self.corpus, "skill": skill, "version_id": version_id,
                    "rule_id": f"auto-{number:02d}", "obligation": "required", "applicability": None,
                    "observable": [signature], "alternatives": [], "location": None,
                    "rule_source": "auto", "approved": False,
                    "in_core": (signature in core) if core is not None else None,
                })
        return rows


def _ledger_confirm(ledger_by_skill: dict[str, list[dict]], skill: str, ts: float | None,
                    text_sha: str | None) -> dict | None:
    """Latest ledger entry that confirms ``text_sha`` was the SKILL.md hash in force (D14)."""
    if ts is None or not text_sha:
        return None
    found = None
    for entry in ledger_by_skill.get(skill, []):
        entry_ts = _epoch(entry.get("ts"))
        if entry_ts is None or entry_ts > ts:
            continue
        if text_sha in _ledger_hashes(entry.get("after")):
            found = {"ts": entry_ts, "actor": entry.get("actor"), "action": entry.get("action")}
    return found


def _ledger_hashes(files) -> list[str]:
    if not isinstance(files, list):
        return []
    out = []
    for item in files:
        if isinstance(item, dict):
            path = item.get("path")
            if isinstance(path, str) and path and not path.replace("\\", "/").endswith("SKILL.md"):
                continue
            digest = item.get("sha256")
            if isinstance(digest, str) and digest:
                out.append(digest)
        elif isinstance(item, str) and item:
            out.append(item)
    return out


def _ledger_skill(entry: dict) -> str | None:
    for key in ("skill", "skill_name", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---------------------------------------------------------------- provenance (D16)
def _provenance_rows(corpus: str, skills: list[str], usage: dict, ledger: list[dict],
                     known_texts_by_sha: dict[str, str]) -> list[dict]:
    ledger_by_skill: dict[str, list[dict]] = {}
    for entry in ledger:
        name = _ledger_skill(entry)
        if name:
            ledger_by_skill.setdefault(name, []).append(entry)

    rows = []
    for skill in sorted(skills):
        info = usage.get(skill)
        info = info if isinstance(info, dict) else {}
        created_ts = _epoch(info.get("created_at") or info.get("createdAt"))
        entries = ledger_by_skill.get(skill, [])
        if created_ts is None:
            creates = [_epoch(e.get("ts")) for e in entries
                       if str(e.get("action") or "").lower() == "create"]
            creates = [ts for ts in creates if ts is not None]
            created_ts = min(creates) if creates else None
        created_by = info.get("created_by")
        if not isinstance(created_by, str) or not created_by.strip():
            created_by = None
        agent_touched = created_by in {"agent", "learn"}
        changes = []
        for entry in entries:
            actor = entry.get("actor") if isinstance(entry.get("actor"), str) else None
            action = entry.get("action") if isinstance(entry.get("action"), str) else None
            if actor in {"agent", "curator"} and (action or "").lower() in {"create", "patch", "write_file"}:
                agent_touched = True
            before = [known_texts_by_sha[h] for h in _ledger_hashes(entry.get("before"))
                      if h in known_texts_by_sha]
            after = [known_texts_by_sha[h] for h in _ledger_hashes(entry.get("after"))
                     if h in known_texts_by_sha]
            added, removed = [], []
            if before and after:
                before_sigs = {sig for text in before for sig in normalize.extract_commands(text)}
                after_sigs = {sig for text in after for sig in normalize.extract_commands(text)}
                added = sorted(after_sigs - before_sigs)
                removed = sorted(before_sigs - after_sigs)
            changes.append({
                "ts": _epoch(entry.get("ts")), "actor": actor, "action": action,
                "added": added, "removed": removed,
            })
        changes.sort(key=lambda c: (c["ts"] is None, c["ts"] or 0.0, str(c["action"]), str(c["actor"])))
        rows.append({
            "corpus": corpus, "skill": skill, "created_ts": created_ts, "created_by": created_by,
            "agent_touched": bool(agent_touched), "changes": changes,
        })
    return rows


# ---------------------------------------------------------------- main entry points
def extract_with_meta(home, corpus: str):
    """Return ``(tables, meta)``; the meta block feeds ``manifest.json`` from the same snapshot."""
    home = Path(home)
    db_path = home / "state.db"
    if not db_path.is_file():
        raise FileNotFoundError(f"hermes home has no state.db: {db_path.name}")
    skills_root = home / "skills"

    conn = _open_readonly(db_path)
    try:
        sessions = _select(conn, "sessions", [
            "id", "source", "model", "system_prompt_hash", "started_at", "ended_at",
        ])
        messages = _select(conn, "messages", [
            "id", "session_id", "role", "content", "tool_call_id", "tool_calls", "timestamp",
        ])
    finally:
        try:
            conn.execute("COMMIT")
        except sqlite3.Error:  # read-only transaction: a rollback is equivalent
            pass
        conn.close()

    skills = _read_skills(skills_root)
    usage = _read_usage(skills_root / ".usage.json")
    ledger = _read_ledger(skills_root / ".curator_ledger.jsonl")
    jobs = _read_cron_jobs(home / "cron" / "jobs.json")
    index = _job_index(jobs)

    grouped: dict[str, list[dict]] = {}
    for msg in messages:
        sid = msg.get("session_id")
        if sid is not None:
            grouped.setdefault(str(sid), []).append(msg)
    for rows in grouped.values():
        rows.sort(key=lambda m: (m.get("id") is None, m.get("id") or 0))

    skill_dirs = {}
    for name, info in skills.items():
        try:
            skill_dirs[name] = info["path"].parent.relative_to(skills_root).parts
        except ValueError:  # a SKILL.md outside the skills root: no path matcher
            continue

    # first user prompt and start time per session
    session_meta = {}
    for row in sessions:
        sid = str(row.get("id"))
        msgs = grouped.get(sid, [])
        first_prompt = None
        first_ts = None
        for msg in msgs:
            if (msg.get("role") or "").lower() == "user" and isinstance(msg.get("content"), str):
                if msg["content"].strip():
                    first_prompt = msg["content"]
                    break
        for msg in msgs:
            ts = _epoch(msg.get("timestamp"))
            if ts is not None:
                first_ts = ts
                break
        started = _epoch(row.get("started_at"))
        if started is None:
            started = first_ts if first_ts is not None else 0.0
        source = row.get("source") if isinstance(row.get("source"), str) else None
        job = None
        if (source or "").lower() == "cron":
            sph = row.get("system_prompt_hash")
            key = prompt_key(first_prompt)
            if isinstance(sph, str) and sph.strip() and sph.strip() in index["by_hash"]:
                job = index["by_hash"][sph.strip()]
            elif key and key in index["by_prompt"]:
                job = index["by_prompt"][key]
        job_id = _job_id(job) if job else None
        preloads = _job_skills(job) if job else []
        task_key = job_id if job_id else prompt_key(first_prompt)
        session_meta[sid] = {
            "row": row,
            "source": source,
            "start_ts": started,
            "first_prompt": first_prompt,
            "first_message_ts": first_ts,
            "job": job,
            "job_id": job_id,
            "preloads": preloads,
            "task_key": task_key,
            "cluster_key": task_key or sid,
        }

    ordered = sorted(session_meta, key=lambda sid: (session_meta[sid]["start_ts"], sid))
    cut = int(len(ordered) * schema.TRAIN_SHARE)
    split_of = {sid: ("train" if i < cut else "test") for i, sid in enumerate(ordered)}
    cutoff_ts = session_meta[ordered[cut]]["start_ts"] if cut < len(ordered) else None

    versions = _Versions(corpus)
    scans = {}
    for sid in ordered:
        meta = session_meta[sid]
        start = meta["first_message_ts"] if meta["first_message_ts"] is not None else meta["start_ts"]
        scans[sid] = _scan_session(sid, grouped.get(sid, []), meta["preloads"], start, skill_dirs)

    # versions from the agent's own skill_manage calls, in source order
    known_texts_by_sha: dict[str, str] = {info["sha256"]: info["text"] for info in skills.values()}
    for sid in ordered:
        for record in scans[sid]["calls"]:
            if record["name"] != MANAGE_TOOL or not record["skill"]:
                continue
            content = _manage_content(record["args"])
            if content is None:
                continue
            known_texts_by_sha.setdefault(_sha256_bytes(content.encode("utf-8")), content)
            versions.add_manage(record["skill"], content, record["ts"],
                                (record["msg_id"] or 0, record["index"]))

    ledger_by_skill: dict[str, list[dict]] = {}
    for entry in ledger:
        name = _ledger_skill(entry)
        if name:
            ledger_by_skill.setdefault(name, []).append(entry)

    def resolve(skill: str, ts: float | None) -> tuple[str | None, str]:
        info = skills.get(skill)
        text = info["text"] if info else None
        text_sha = info["sha256"] if info else None
        confirmed = _ledger_confirm(ledger_by_skill, skill, ts, text_sha)
        if confirmed and text is not None:
            return versions.add(skill, text, "ledger", confirmed["ts"], in_core_mode=False), "ledger"
        managed = versions.latest_manage(skill, ts)
        if managed:
            return managed["version_id"], "skill_manage"
        if text is not None:
            return versions.add(skill, text, "version_core", None, in_core_mode=True), "version_core"
        return None, "version_unknown"

    session_rows, step_rows, load_rows = [], [], []
    for sid in ordered:
        meta = session_meta[sid]
        scan = scans[sid]
        steps = scan["steps"]
        session_rows.append({
            "corpus": corpus, "session_id": sid, "start_ts": meta["start_ts"], "source": meta["source"],
            "task_key": meta["task_key"], "cluster_key": meta["cluster_key"],
            "model": meta["row"].get("model") if isinstance(meta["row"].get("model"), str) else None,
            "harness_version": None, "pair_id": None, "pair_arm": None, "split": split_of[sid],
        })
        for step in steps:
            step_rows.append({
                "corpus": corpus, "session_id": sid, "step": step["step"],
                "source_offset": step["source_offset"], "call_id": step["call_id"],
                "batch_id": step["batch_id"], "ts": step["ts"], "kind": step["kind"],
                "signature": step["signature"], "status": step["status"],
                "attribution_skill": step["attribution_skill"],
            })

        load_steps = [s for s in steps if s["kind"] == "load" and s["status"] == "ok" and s.get("_skill")]
        load_positions = [s["step"] for s in load_steps]
        last_step = len(steps) - 1
        seen: set[str] = set()
        for load in load_steps:
            step_no = load["step"]
            skill = load["_skill"]
            window = [s for s in steps if step_no < s["step"] <= step_no + schema.WINDOW_N]
            flags = []
            if skill in seen:
                flags.append("repeat")
            seen.add(skill)
            if any((s.get("_call_name") == MANAGE_TOOL and s.get("_call_skill") == skill)
                   or (s.get("_write_skill") == skill) for s in window):
                flags.append("maintenance")
            if step_no + schema.WINDOW_N > last_step:
                flags.append("incomplete")
            if any(step_no < other <= step_no + schema.WINDOW_N for other in load_positions if other != step_no):
                flags.append("overlap")
            if load.get("_preload"):
                trigger = "preloaded"
            elif load.get("_prompt") and skill.lower() in str(load["_prompt"]).lower():
                trigger = "instructed"
            else:
                trigger = "chosen"
            version_id, version_source = resolve(skill, load["ts"])
            load_rows.append({
                "corpus": corpus, "session_id": sid,
                "load_id": schema.episode_id(corpus, sid, step_no), "skill": skill, "step": step_no,
                "ts": load["ts"], "trigger": trigger, "version_id": version_id,
                "version_source": version_source, "flags": sorted(flags),
                "cluster_key": meta["cluster_key"], "split": split_of[sid],
            })

    tables = {
        "sessions": sorted(session_rows, key=lambda r: r["session_id"]),
        "steps": sorted(step_rows, key=lambda r: (r["session_id"], r["step"])),
        "loads": sorted(load_rows, key=lambda r: (r["session_id"], r["step"], r["skill"])),
        "skill_versions": versions.table_rows(),
        "rules": versions.rule_rows(),
    }
    tables["provenance"] = _provenance_rows(
        corpus,
        sorted(set(usage) | set(skills) | set(ledger_by_skill)
               | {r["skill"] for r in tables["loads"]} | {r["skill"] for r in tables["skill_versions"]}),
        usage, ledger, known_texts_by_sha,
    )

    max_message_id = max((m.get("id") for m in messages if isinstance(m.get("id"), int)), default=0)
    timestamps = [_epoch(m.get("timestamp")) for m in messages]
    timestamps += [_epoch(row.get("started_at")) for row in sessions]
    timestamps += [_epoch(row.get("ended_at")) for row in sessions]
    timestamps = [ts for ts in timestamps if ts is not None]
    meta_out = {
        "max_message_id": int(max_message_id),
        "max_timestamp": max(timestamps) if timestamps else None,
        "split_cutoff_ts": cutoff_ts,
        "split_counts": {
            "train": sum(1 for sid in ordered if split_of[sid] == "train"),
            "test": sum(1 for sid in ordered if split_of[sid] == "test"),
        },
        "source": {
            "sqlite": {"sessions": len(sessions), "messages": len(messages)},
            "skills_on_disk": len(skills),
            "cron_jobs": len(jobs),
            "cron_sessions": sum(1 for sid in ordered
                                 if (session_meta[sid]["source"] or "").lower() == "cron"),
            "cron_sessions_mapped": sum(1 for sid in ordered if session_meta[sid]["job_id"]),
            "ledger": _ledger_summary(ledger),
        },
    }
    return tables, meta_out


def _ledger_summary(ledger: list[dict]) -> dict:
    by_actor: dict[str, int] = {}
    by_action: dict[str, int] = {}
    before_sizes, after_sizes = [], []
    text_sources = 0
    for entry in ledger:
        actor = entry.get("actor")
        actor = actor if isinstance(actor, str) else "unknown"
        action = entry.get("action")
        action = action if isinstance(action, str) else "unknown"
        by_actor[actor] = by_actor.get(actor, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
        before, after = entry.get("before"), entry.get("after")
        before_sizes.append(len(before) if isinstance(before, list) else 0)
        after_sizes.append(len(after) if isinstance(after, list) else 0)
        for side in (before, after):
            if isinstance(side, dict) or (isinstance(side, str) and len(side) > 200):
                text_sources += 1
    return {
        "rows": len(ledger),
        "by_actor": dict(sorted(by_actor.items())),
        "by_action": dict(sorted(by_action.items())),
        "before_after_content": "text" if text_sources else "hash-only",
        "max_before_entries": max(before_sizes, default=0),
        "max_after_entries": max(after_sizes, default=0),
    }


def extract(home, corpus: str) -> dict[str, list[dict]]:
    """All six D12 tables for one Hermes home (design D12)."""
    tables, _ = extract_with_meta(home, corpus)
    return tables