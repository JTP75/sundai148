"""Hermes adapter tests (W1): every EXPECTED key from tests/fixtures/hermes_sample.py."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from potency import io, schema
from potency.adapters import hermes
from tests.fixtures.hermes_sample import EXPECTED, FAKE_SECRET, build


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return build(tmp_path_factory.mktemp("hermes"))


@pytest.fixture(scope="module")
def tables(sample):
    return hermes.extract(sample["home"], "hermes-test")


def _by_session(tables, table, session_id):
    return [row for row in tables[table] if row["session_id"] == session_id]


@pytest.mark.parametrize("table", list(schema.TABLES))
def test_every_table_matches_schema(tables, table):
    assert tables[table], table
    schema.validate_rows(table, tables[table])


def test_session_count(tables):
    assert len(tables["sessions"]) == EXPECTED["sessions"]
    assert {row["session_id"] for row in tables["sessions"]} == {"h1", "h2", "h3", "h4"}


def test_h1_signatures_in_source_order(tables):
    assert [row["signature"] for row in _by_session(tables, "steps", "h1")] == EXPECTED["signatures_h1"]


def test_successful_loads_and_failed_load_dropped(tables):
    successful = [row for row in tables["loads"] if row["trigger"] != "preloaded"]
    assert len(successful) == EXPECTED["successful_skill_view_loads"]
    assert "does-not-exist" not in {row["skill"] for row in tables["loads"]}
    failed_steps = [row for row in tables["steps"] if row["kind"] == "load" and row["status"] == "error"]
    assert len(failed_steps) == EXPECTED["failed_loads_dropped"]
    assert failed_steps[0]["signature"] == "load: does-not-exist"


def test_preloaded_and_instructed_triggers(tables):
    preloaded = [(row["session_id"], row["skill"]) for row in tables["loads"] if row["trigger"] == "preloaded"]
    instructed = [(row["session_id"], row["skill"]) for row in tables["loads"] if row["trigger"] == "instructed"]
    assert preloaded == EXPECTED["preloaded"]
    assert instructed == EXPECTED["instructed"]
    chosen = [(row["session_id"], row["skill"]) for row in tables["loads"] if row["trigger"] == "chosen"]
    assert chosen == [("h1", "gog-cli"), ("h2", "prose-only"), ("h4", "job-tracker"), ("h4", "job-tracker")]


def test_maintenance_and_repeat_flags(tables):
    maintenance = [(row["session_id"], row["skill"]) for row in tables["loads"] if "maintenance" in row["flags"]]
    repeat = [(row["session_id"], row["skill"]) for row in tables["loads"] if "repeat" in row["flags"]]
    assert maintenance == EXPECTED["maintenance"]
    assert repeat == EXPECTED["repeat"]


def test_incomplete_and_overlap_flags(tables):
    for row in tables["loads"]:
        assert "incomplete" in row["flags"], row
    overlaps = [(row["session_id"], row["step"]) for row in tables["loads"] if "overlap" in row["flags"]]
    assert overlaps == [("h2", 0), ("h4", 1)]


def test_same_batch_command_shares_the_load_batch(tables):
    session_id, signature = EXPECTED["same_batch_command"]
    load = next(row for row in tables["loads"] if row["session_id"] == session_id and row["skill"] == "job-tracker")
    steps = _by_session(tables, "steps", session_id)
    command = next(row for row in steps if row["signature"] == signature)
    assert command["batch_id"] == steps[load["step"]]["batch_id"]
    assert command["step"] == load["step"] + 1


def test_cluster_key_shared(tables):
    (session_id,) = EXPECTED["cluster_key_shared"]
    session = next(row for row in tables["sessions"] if row["session_id"] == session_id)
    assert session["task_key"] == "job-1"
    assert session["cluster_key"] == session["task_key"]
    assert session["cluster_key"] != session_id
    assert {row["cluster_key"] for row in tables["loads"] if row["session_id"] == session_id} == {"job-1"}


def test_task_key_never_contains_prompt_text(tables):
    keys = {row["session_id"]: row["task_key"] for row in tables["sessions"]}
    assert keys["h3"] == "job-1"  # cron job id, the first source in D15
    for session_id, key in keys.items():
        if session_id == "h3":
            continue
        assert len(key) == 16
        int(key, 16)  # prompt hash: hex only, never the prompt
    blob = json.dumps(tables["sessions"])
    for needle in ("what are my tasks", "Check today's tasks", "use job-tracker"):
        assert needle not in blob


def test_version_sources(tables):
    rows = {(row["session_id"], row["step"]): row for row in tables["loads"]}
    assert rows[("h2", 0)]["version_source"] == "version_core"
    assert rows[("h4", 1)]["version_source"] == "skill_manage"
    assert rows[("h4", 1)]["version_id"] == rows[("h4", 3)]["version_id"]
    # prose-only is loaded before its skill_manage, so the load predates the only replayable text
    assert rows[("h2", 3)]["version_source"] == "version_core"
    versions = {(row["skill"], row["version_source"]) for row in tables["skill_versions"]}
    assert ("prose-only", "skill_manage") in versions
    for row in tables["loads"]:
        assert row["version_id"] is not None
        assert row["version_source"] in schema.VERSION_SOURCES


def test_version_core_marks_removed_commands_outside_core(tables):
    managed = next(row for row in tables["skill_versions"]
                   if row["skill"] == "job-tracker" and row["version_source"] == "skill_manage")
    current = next(row for row in tables["loads"]
                   if row["skill"] == "job-tracker" and row["version_source"] == "version_core")
    managed_rules = [row for row in tables["rules"]
                     if (row["skill"], row["version_id"]) == ("job-tracker", managed["version_id"])]
    core_rules = [row for row in tables["rules"]
                  if (row["skill"], row["version_id"]) == ("job-tracker", current["version_id"])]
    assert [row["observable"] for row in managed_rules] == [["terminal: hermes jobs list"]]
    assert [row["observable"] for row in core_rules] == [["terminal: hermes jobs status"]]
    assert core_rules[0]["in_core"] is False
    assert managed_rules[0]["in_core"] is None
    assert len(tables["rules"]) == 4


def test_rules_are_auto_and_hide_nothing(tables):
    for rule in tables["rules"]:
        assert rule["obligation"] == "required"
        assert rule["applicability"] is None
        assert rule["rule_source"] == "auto"
        assert rule["approved"] is False
        assert rule["observable"] and all(" " not in sig or sig.startswith(("terminal: ", "load: "))
                                          for sig in rule["observable"])


def test_provenance(tables):
    got = {row["skill"]: row["agent_touched"] for row in tables["provenance"]}
    assert got == EXPECTED["agent_touched"]
    by_skill = {row["skill"]: row for row in tables["provenance"]}
    assert by_skill["gog-cli"]["created_by"] == "agent"
    assert by_skill["prose-only"]["created_by"] == "learn"
    assert by_skill["job-tracker"]["created_by"] is None
    assert by_skill["gog-cli"]["created_ts"] is not None
    change = by_skill["gog-cli"]["changes"][0]
    assert change["actor"] == "curator" and change["action"] == "patch"


def test_temporal_split_uses_one_cutoff(tables):
    sessions = tables["sessions"]
    starts = {row["session_id"]: row["start_ts"] for row in sessions}
    train = [sid for sid, row in ((s["session_id"], s) for s in sessions) if row["split"] == "train"]
    test = [sid for sid, row in ((s["session_id"], s) for s in sessions) if row["split"] == "test"]
    assert train and test
    assert max(starts[sid] for sid in train) < min(starts[sid] for sid in test)
    for load in tables["loads"]:
        expected = "train" if load["session_id"] in train else "test"
        assert load["split"] == expected
    assert all(row["split"] in schema.SPLITS for row in sessions)


def test_private_text_never_reaches_a_table(tables):
    blob = json.dumps(tables)
    for needle in EXPECTED["must_not_appear_anywhere"]:
        assert needle not in blob, needle
    assert FAKE_SECRET not in blob


def test_one_readonly_connection_one_transaction(sample, monkeypatch):
    calls = []
    real_connect = sqlite3.connect

    def spy(database, *args, **kwargs):
        calls.append((database, kwargs.get("uri", False)))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(hermes.sqlite3, "connect", spy)
    before = hashlib.sha256(Path(sample["state_db"]).read_bytes()).hexdigest()
    hermes.extract(sample["home"], "hermes-test")
    after = hashlib.sha256(Path(sample["state_db"]).read_bytes()).hexdigest()
    assert len(calls) == 1
    database, uri = calls[0]
    assert uri is True
    assert "mode=ro" in database
    assert before == after


@pytest.mark.parametrize("content,status", [
    (json.dumps({"error": "Skill not found"}), "error"),
    (json.dumps({"success": False}), "error"),
    (json.dumps({"exit_code": 2}), "error"),
    ('{"content": "done"}', "ok"),
    ("Error: something broke", "error"),
    ("Traceback (most recent call last):", "error"),
    ("plain output", "ok"),
    (None, "unknown"),
])
def test_result_status(content, status):
    assert hermes.result_status(content) == status


def test_write_target_skill_matching():
    dirs = {"gog-cli": ("google", "gog-cli"), "job-tracker": ("ops", "job-tracker")}
    assert hermes._write_target_skill({"path": "skills/google/gog-cli/SKILL.md"}, dirs) == "gog-cli"
    assert hermes._write_target_skill({"file_path": "C:\\h\\.hermes\\skills\\ops\\job-tracker\\SKILL.md"}, dirs) \
        == "job-tracker"
    assert hermes._write_target_skill({"path": "skills/notes.md"}, dirs) is None
    assert hermes._write_target_skill({}, dirs) is None


def _append_session(db_path: Path, home: Path, session_id: str, start_ts: float) -> None:
    """A session recorded after the curator ledger begins: load, then a write into the skill dir."""
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO sessions (id, source, model, started_at) VALUES (?,?,?,?)",
                 (session_id, "cli", "m", start_ts))

    def msg(i, role, content=None, tool_calls=None, tool_call_id=None, tool_name=None):
        conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, tool_name, timestamp)"
            " VALUES (?,?,?,?,?,?,?)",
            (session_id, role, content, json.dumps(tool_calls) if tool_calls else None,
             tool_call_id, tool_name, start_ts + i * 5))

    def call(call_id, name, args):
        return [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]

    msg(0, "user", "please use gog-cli")
    msg(1, "assistant", "", call("w1", "skill_view", {"name": "gog-cli"}))
    msg(2, "tool", "ok", tool_call_id="w1", tool_name="skill_view")
    msg(3, "assistant", "", call("w2", "write_file", {"path": str(home / "skills" / "google" / "gog-cli" / "SKILL.md"),
                                                       "content": "body"}))
    msg(4, "tool", "ok", tool_call_id="w2", tool_name="write_file")
    msg(5, "assistant", "", call("w3", "terminal", {"command": "gog tasks list"}))
    msg(6, "tool", "ok", tool_call_id="w3", tool_name="terminal")
    conn.commit()
    conn.close()


def test_write_maintenance_and_ledger_version(tmp_path):
    sample = build(tmp_path)
    ledger_ts = datetime.fromisoformat("2026-10-02T00:00:00+00:00").timestamp()
    start_ts = ledger_ts + 86400
    _append_session(sample["state_db"], sample["home"], "h5", start_ts)
    tables = hermes.extract(sample["home"], "hermes-test")
    load = next(row for row in tables["loads"] if row["session_id"] == "h5")
    assert load["skill"] == "gog-cli"
    assert "maintenance" in load["flags"]  # the write into that skill's dir follows the load
    assert load["flags"] == ["incomplete", "maintenance"]  # short session: window also truncated
    assert load["trigger"] == "instructed"  # the prompt above names the skill
    assert load["version_source"] == "ledger"
    version = next(row for row in tables["skill_versions"] if row["version_id"] == load["version_id"])
    assert version["version_source"] == "ledger"
    assert version["valid_from_ts"] == pytest.approx(ledger_ts)
    assert str(sample["home"]) not in json.dumps(tables)
