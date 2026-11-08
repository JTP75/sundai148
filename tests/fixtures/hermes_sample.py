"""Build a tiny, schema-faithful Hermes home for W1's adapter tests (stdlib only).

    from tests.fixtures.hermes_sample import build, EXPECTED
    paths = build(tmp_path)   # -> {"home", "state_db", "skills", "usage", "ledger", "cron_jobs"}

Mirrors the real layout reported by the data session (design Context): ``~/.hermes/state.db`` with
``sessions`` and ``messages`` tables; assistant rows carry ``tool_calls`` as a JSON list of
``{"id", "function": {"name", "arguments"}}`` (arguments is a JSON string); tool rows carry ``tool_call_id``,
``tool_name`` and ``content``. Skills live at ``skills/<category>/<skill>/SKILL.md``; ``skills/.usage.json`` has
``created_by``; ``skills/.curator_ledger.jsonl`` has before/after as lists of {path, sha256} (no text);
``cron/jobs.json`` lists jobs with ``skills``. Real field names on orin may differ slightly: the adapter must be
tolerant, and the data session validates it against the real database.

Every assistant message text, user prompt and tool output here is synthetic. One command carries a fake secret
that must never reach any exported file.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

T0 = 1780000000.0  # 2026-05-28
FAKE_SECRET = "ghp_FAKEFAKEFAKE1234567890"

SCHEMA_SQL = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY, source TEXT, user_id TEXT, model TEXT, system_prompt_hash TEXT, parent_session_id TEXT,
  started_at REAL, ended_at REAL, end_reason TEXT, message_count INTEGER, tool_call_count INTEGER, title TEXT,
  session_key TEXT, origin_json TEXT
);
CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, tool_call_id TEXT,
  tool_calls TEXT, tool_name TEXT, timestamp REAL, token_count INTEGER, finish_reason TEXT, reasoning TEXT,
  active INTEGER DEFAULT 1, compacted INTEGER DEFAULT 0, message_uid TEXT, tool_call_uid TEXT
);
"""

SKILLS = {
    ("google", "gog-cli"): "# gog CLI\n\n```bash\ngog tasks list --json\ngog auth login\n```\n",
    ("ops", "job-tracker"): "# Job tracker\n\nAlways run `hermes jobs status` first.\n",
    ("meta", "prose-only"): "# Prose\n\nThink carefully and be kind.\n",
}
USAGE = {
    "gog-cli": {"created_by": "agent", "created_at": "2026-05-20T00:00:00Z", "patch_count": 1},
    "job-tracker": {"created_by": None, "created_at": None, "patch_count": 0},
    "prose-only": {"created_by": "learn", "created_at": "2026-05-01T00:00:00Z", "patch_count": 0},
}
CRON_JOBS = {"jobs": [
    {"id": "job-1", "name": "daily tasks", "prompt": "Check today's tasks for 2026-06-01.", "skills": ["gog-cli"]},
    {"id": "job-2", "name": "status", "prompt": "Report job status.", "skills": []},
]}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _DB:
    def __init__(self, conn):
        self.conn, self.ts, self.n = conn, T0, 0

    def session(self, sid, source="cli", title=None, sph=None, start=None):
        self.ts = start or self.ts + 3600
        self.conn.execute("INSERT INTO sessions (id, source, model, system_prompt_hash, started_at, title) VALUES (?,?,?,?,?,?)",
                          (sid, source, "deepseek/deepseek-v4.1-flash", sph, self.ts, title))

    def msg(self, sid, role, content=None, tool_calls=None, tool_call_id=None, tool_name=None):
        self.ts += 5
        self.conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, tool_name, timestamp) VALUES (?,?,?,?,?,?,?)",
            (sid, role, content, json.dumps(tool_calls) if tool_calls else None, tool_call_id, tool_name, self.ts))

    def calls(self, sid, *calls, results=None):
        """One assistant message issuing several tool calls (same batch), then one tool row per call."""
        tcs = []
        for name, args in calls:
            self.n += 1
            tcs.append({"id": f"call_{self.n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}})
        self.msg(sid, "assistant", content="", tool_calls=tcs)
        for i, tc in enumerate(tcs):
            out = (results or {}).get(i, "ok")
            self.msg(sid, "tool", content=out, tool_call_id=tc["id"], tool_name=tc["function"]["name"])


def build(dest) -> dict:
    home = Path(dest) / "hermes_home"
    skills_dir = home / "skills"
    for (cat, name), body in SKILLS.items():
        p = skills_dir / cat / name / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body.encode("utf-8"))  # exact bytes: write_text would emit CRLF on Windows and break hashes
    (skills_dir / ".usage.json").write_bytes((json.dumps(USAGE)).encode("utf-8"))
    ledger = [
        {"id": 1, "ts": "2026-10-02T00:00:00Z", "actor": "curator", "action": "patch", "skill": "gog-cli", "evidence": "x",
         "before": [{"path": "SKILL.md", "sha256": _sha("old")}],
         "after": [{"path": "SKILL.md", "sha256": _sha(SKILLS[("google", "gog-cli")])}]},
    ]
    (skills_dir / ".curator_ledger.jsonl").write_bytes(("\n".join(json.dumps(r) for r in ledger) + "\n").encode("utf-8"))
    (home / "cron").mkdir(parents=True, exist_ok=True)
    (home / "cron" / "jobs.json").write_bytes((json.dumps(CRON_JOBS)).encode("utf-8"))

    db_path = home / "state.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_SQL)
    d = _DB(conn)

    # h1: chosen load of gog-cli, then its command; a secret-bearing curl
    d.session("h1", source="telegram", title="tasks")
    d.msg("h1", "user", content="what are my tasks? token is " + FAKE_SECRET)
    d.calls("h1", ("search_files", {"query": "tasks secret query"}))
    d.calls("h1", ("skill_view", {"name": "gog-cli"}))
    d.calls("h1", ("terminal", {"command": "gog tasks list --json"}))
    d.calls("h1", ("terminal", {"command": f"curl -H 'Authorization: token {FAKE_SECRET}' https://api.github.com"}))
    d.calls("h1", ("read_file", {"path": "/home/pacel/private/notes.md"}))

    # h2: instructed load (prompt names the skill), failed load, parallel batch, maintenance load
    d.session("h2", source="cli")
    d.msg("h2", "user", content="use job-tracker to check status")
    d.calls("h2", ("skill_view", {"name": "job-tracker"}), ("terminal", {"command": "hermes jobs status"}))
    d.calls("h2", ("skill_view", {"name": "does-not-exist"}), results={0: json.dumps({"error": "Skill not found"})})
    d.calls("h2", ("skill_view", {"name": "prose-only"}))
    d.calls("h2", ("skill_manage", {"action": "patch", "name": "prose-only", "content": "# Prose v2"}))
    d.calls("h2", ("terminal", {"command": "ls -la && git status"}))

    # h3: cron session mapped to job-1 by prompt hash -> preloaded gog-cli at step 0; no skill_view
    d.session("h3", source="cron", title="daily tasks", sph="sph-1")
    d.msg("h3", "user", content="Check today's tasks for 2026-06-02.")
    d.calls("h3", ("terminal", {"command": "gog tasks list"}))

    # h4: skill_manage in the `operations` format (no action field); repeat load
    d.session("h4", source="cli")
    d.msg("h4", "user", content="update the tracker")
    d.calls("h4", ("skill_manage", {"name": "job-tracker", "operations": [{"op": "replace", "text": "Run `hermes jobs list`."}]}))
    d.calls("h4", ("skill_view", {"name": "job-tracker"}))
    d.calls("h4", ("terminal", {"command": "hermes jobs list"}))
    d.calls("h4", ("skill_view", {"name": "job-tracker"}))
    conn.commit()
    conn.close()
    return {"home": home, "state_db": db_path, "skills": skills_dir, "usage": skills_dir / ".usage.json",
            "ledger": skills_dir / ".curator_ledger.jsonl", "cron_jobs": home / "cron" / "jobs.json"}


EXPECTED = {
    "sessions": 4,
    "successful_skill_view_loads": 5,  # h1 gog-cli, h2 job-tracker, h2 prose-only, h4 job-tracker x2
    "failed_loads_dropped": 1,  # h2 does-not-exist
    "preloaded": [("h3", "gog-cli")],
    "instructed": [("h2", "job-tracker")],
    "maintenance": [("h2", "prose-only")],
    "repeat": [("h4", "job-tracker")],
    "same_batch_command": ("h2", "terminal: hermes jobs status"),
    "cluster_key_shared": ("h3",),  # task key from prompt hash after stripping digits/dates
    "agent_touched": {"gog-cli": True, "job-tracker": False, "prose-only": True},
    "must_not_appear_anywhere": [FAKE_SECRET, "secret query", "/home/pacel/private", "api.github.com",
                                 "what are my tasks", "Check today's tasks"],
    "signatures_h1": ["search_files", "load: gog-cli", "terminal: gog tasks list", "terminal: curl", "read_file"],
}
