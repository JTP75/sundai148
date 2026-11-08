"""Claude Code adapter tests (tasks 3.1-3.2): fixture parity, schema contract, meta join, load flags."""
import json
import shutil
from pathlib import Path

import pytest

from potency import io, schema
from potency.adapters import claude_code

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "tests" / "fixtures" / "claude_code_sample"
EXPECTED = json.loads((SAMPLE / "expected.json").read_text(encoding="utf-8"))
CORPUS = "swechat-v1"
TABLES = ("sessions", "steps", "loads", "skill_versions", "rules", "provenance")


@pytest.fixture(scope="module")
def tables():
    return claude_code.extract(SAMPLE, CORPUS)


def _rows(tables, table, **match):
    return [r for r in tables[table] if all(r[k] == v for k, v in match.items())]


# ------------------------------------------------------------------ expected.json parity
def test_returns_exactly_the_six_tables(tables):
    assert set(tables) == set(TABLES)


@pytest.mark.parametrize("table", TABLES)
def test_tables_match_schema(tables, table):
    assert tables[table], table
    schema.validate_rows(table, tables[table])


def test_sessions_match_expected(tables):
    assert len(tables["sessions"]) == EXPECTED["sessions"]
    assert {s["session_id"]: s["cluster_key"] for s in tables["sessions"]} == EXPECTED["cluster_keys"]


def test_temporal_split_by_session_start(tables):
    # one cutoff, ~70% of sessions; no random split (design D8)
    split = {s["session_id"]: s["split"] for s in tables["sessions"]}
    assert split == {"sess-a": "train", "sess-b": "train", "sess-c": "test"}


def test_loads_match_expected(tables):
    got = [(ld["session_id"], ld["skill"], ld["version_source"]) for ld in tables["loads"]]
    want = [(ld["session_id"], ld["skill"], ld["version_source"]) for ld in EXPECTED["loads"]]
    assert got == want
    # expected.json pins the content flags (repeat/maintenance); window flags are asserted separately
    for load, expected in zip(tables["loads"], EXPECTED["loads"]):
        assert set(expected["flags"]) <= set(load["flags"])
        assert sorted(f for f in load["flags"] if f in {"repeat", "maintenance"}) == expected["flags"]


def test_injected_version_and_unknown_version(tables):
    injected = [ld for ld in tables["loads"] if ld["version_source"] == "injected"]
    unknown = [ld for ld in tables["loads"] if ld["version_source"] == "version_unknown"]
    assert {(ld["session_id"], ld["skill"]) for ld in injected} == {("sess-a", "commit"), ("sess-b", "review")}
    assert all(ld["version_id"] for ld in injected)
    assert all(ld["version_id"] is None for ld in unknown)
    assert {(ld["session_id"], ld["skill"]) for ld in unknown} == {("sess-b", "review"), ("sess-b", "commit")}
    # no injected body -> no version row and no rules for a None version id
    assert {v["version_id"] for v in tables["skill_versions"]} == {ld["version_id"] for ld in injected}


def test_signatures_in_source_order(tables):
    steps = _rows(tables, "steps", session_id="sess-a")
    assert [st["step"] for st in steps] == list(range(len(steps)))
    assert [st["signature"] for st in steps] == EXPECTED["signatures_sess_a"]


def test_parallel_calls_share_one_batch(tables):
    batches = {}
    for st in _rows(tables, "steps", session_id="sess-a"):
        batches.setdefault(st["batch_id"], []).append(st)
    parallel = [
        [st["signature"] for st in sts]
        for sts in batches.values()
        if len({st["call_id"] for st in sts}) > 1  # compound expansion shares one call id
    ]
    assert parallel == [EXPECTED["same_batch"]["sess-a"]]


def test_compound_command_expands_with_one_call_id(tables):
    steps = _rows(tables, "steps", session_id="sess-a")
    compound = [st for st in steps if st["signature"] in
                ("terminal: git add", "terminal: git commit", "terminal: git push")]
    assert len(compound) == 3 and len({st["call_id"] for st in compound}) == 1


def test_attribution_skill_is_a_hint_only(tables):
    steps = _rows(tables, "steps", session_id="sess-a")
    hint = EXPECTED["attribution_skill_steps"]["sess-a"]
    assert {st["attribution_skill"] for st in steps if st["attribution_skill"]} == {hint}
    assert [st["step"] for st in steps if st["attribution_skill"]] == [1, 2, 3, 4, 5]
    assert all(st["attribution_skill"] is None for st in _rows(tables, "steps", session_id="sess-b"))


def test_review_rules_are_auto_required(tables):
    rules = [r for r in tables["rules"] if r["skill"] == "review"]
    assert [r["observable"] for r in rules] == [["terminal: gh pr diff"]]
    for rule in rules:
        assert rule["obligation"] == "required"
        assert rule["applicability"] is None
        assert rule["rule_source"] == "auto" and rule["approved"] is False and rule["in_core"] is None


def test_commit_rules_match_expected(tables):
    commit = {v["version_id"] for v in tables["skill_versions"] if v["skill"] == "commit"}
    assert len(commit) == 1
    rules = [r for r in tables["rules"] if r["skill"] == "commit"]
    assert all(r["version_id"] in commit for r in rules)
    assert [r["observable"][0] for r in rules] == EXPECTED["commit_rules_auto"]


def test_provenance_row_per_loaded_skill(tables):
    assert [p["skill"] for p in tables["provenance"]] == ["commit", "review"]
    for row in tables["provenance"]:
        assert row["created_ts"] is None and row["created_by"] is None
        assert row["agent_touched"] is False and row["changes"] == []


def test_triggers_follow_the_user_text(tables):
    assert [ld["trigger"] for ld in tables["loads"]] == ["instructed", "instructed", "instructed", "chosen"]


def test_no_text_or_secret_leaks(tables):
    dumped = "\n".join(io.dumps(row) for table in TABLES for row in tables[table])
    for marker in EXPECTED["must_not_appear_anywhere"]:
        assert marker not in dumped
    assert "/repo/x.py" not in dumped and "please commit my work" not in dumped


def test_task_key_is_prompt_hash_without_digits(tables):
    keys = {s["session_id"]: s["task_key"] for s in tables["sessions"]}
    assert all(len(key) == 16 for key in keys.values())
    assert len(set(keys.values())) == len(keys)


# ------------------------------------------------------------------ metadata join
def test_version_valid_from_is_the_earliest_load(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    body = "# Shared\n\n```bash\nmake test\n```\n"
    # file order ("a-early", "b-late") is not time order, so valid_from must take the minimum
    early = _load_lines("a-early", 0, "alpha", body, None)
    late = _load_lines("b-late", 0, "alpha", body, None)
    early[0]["timestamp"] = "2026-03-01T00:00:00Z"
    late[0]["timestamp"] = "2026-02-01T00:00:00Z"
    _write_session(source, "a-early", early)
    _write_session(source, "b-late", late)
    got = claude_code.extract(source, CORPUS)
    versions = got["skill_versions"]
    assert len(versions) == 1
    assert versions[0]["valid_from_ts"] == 1769904000.0  # 2026-02-01T00:00:00Z


def test_parquet_meta_default_discovery(tmp_path):
    pd = pytest.importorskip("pandas")
    source = tmp_path / "source"
    (source / "transcripts").mkdir(parents=True)
    for path in (SAMPLE / "transcripts").glob("*.jsonl"):
        shutil.copy(path, source / "transcripts" / path.name)
    pd.DataFrame([
        {"session_id": "2026-02-01-dddd-sess-a", "repo_id": "org/parquet-1", "user_id": "u1",
         "agent": "claude-code", "created_at": pd.Timestamp("2026-02-01 10:00:00"), "cli_version": "9.9.9"},
        {"session_id": "2026-02-02-dddd-sess-b", "repo_id": "org/parquet-1", "user_id": "u2",
         "agent": "claude-code", "created_at": pd.Timestamp("2026-02-02 09:00:00"), "cli_version": "9.9.9"},
        {"session_id": "2026-02-03-dddd-sess-c", "repo_id": "org/parquet-2", "user_id": "u1",
         "agent": "claude-code", "created_at": pd.Timestamp("2026-02-03 08:00:00"), "cli_version": "8.0.0"},
    ]).to_parquet(source / "sessions.parquet", index=False)

    got = claude_code.extract(source, CORPUS)  # no sessions_meta: picks up sessions.parquet
    assert {s["session_id"]: s["cluster_key"] for s in got["sessions"]} == {
        "sess-a": "org/parquet-1", "sess-b": "org/parquet-1", "sess-c": "org/parquet-2"}
    assert {(s["session_id"], s["harness_version"]) for s in got["sessions"]} == {
        ("sess-a", "9.9.9"), ("sess-b", "9.9.9"), ("sess-c", "8.0.0")}
    starts = {s["session_id"]: s["start_ts"] for s in got["sessions"]}
    assert starts["sess-a"] == 1769940000.0
    assert all(ld["cluster_key"] == "org/parquet-1" for ld in got["loads"] if ld["session_id"] != "sess-c")


def test_cluster_key_falls_back_to_user_then_session(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _write_session(source, "no-meta", [_call_line("no-meta", 0, "t1", "Bash", {"command": "ls"})])
    got = claude_code.extract(source, CORPUS)
    assert got["sessions"][0]["cluster_key"] == "no-meta"
    assert got["sessions"][0]["source"] is None and got["sessions"][0]["pair_id"] is None


# ------------------------------------------------------------------ window flags
def test_window_flags_repeat_overlap_incomplete_maintenance(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    body = "```bash\nmake test\n```\n"

    # complete window, no flags
    lines = [_user_line("plain", 0, "run the tests")]
    lines += _load_lines("plain", 1, "alpha", body, "make test")
    lines += [_call_line("plain", i, f"c{i}", "Bash", {"command": "ls"}) for i in range(3, 15)]
    _write_session(source, "plain", lines)

    # overlapping loads: beta loads inside alpha's window
    lines = _load_lines("over", 1, "alpha", body, "make test")
    lines += [_call_line("over", i, f"c{i}", "Bash", {"command": "ls"}) for i in range(3, 5)]
    lines += _load_lines("over", 5, "beta", body, "make test")
    lines += [_call_line("over", i, f"d{i}", "Bash", {"command": "ls"}) for i in range(7, 19)]
    _write_session(source, "over", lines)

    # same skill twice: the second load is a repeat
    lines = _load_lines("twice", 1, "alpha", body, "make test")
    lines += [_call_line("twice", i, f"c{i}", "Bash", {"command": "ls"}) for i in range(3, 5)]
    lines += _load_lines("twice", 5, "alpha", None, None)
    lines += [_call_line("twice", i, f"d{i}", "Bash", {"command": "ls"}) for i in range(7, 19)]
    _write_session(source, "twice", lines)

    # a write to the skill shortly after the load: maintenance
    lines = _load_lines("maint", 1, "alpha", body, "make test")
    lines += _tool_line("maint", 3, "m1", "skill_manage", {"action": "patch"})
    lines += [_call_line("maint", i, f"c{i}", "Bash", {"command": "ls"}) for i in range(5, 17)]
    _write_session(source, "maint", lines)

    # session ends a few steps after the load
    lines = _load_lines("short", 1, "alpha", body, "make test")
    lines += [_call_line("short", i, f"c{i}", "Bash", {"command": "ls"}) for i in range(3, 5)]
    _write_session(source, "short", lines)

    got = claude_code.extract(source, CORPUS)
    flags = {(ld["session_id"], ld["skill"], ld["step"]): ld["flags"] for ld in got["loads"]}
    assert flags[("plain", "alpha", 0)] == []
    assert flags[("over", "alpha", 0)] == ["overlap"]
    assert flags[("over", "beta", 3)] == []
    assert flags[("twice", "alpha", 0)] == ["overlap"]
    assert flags[("twice", "alpha", 3)] == ["repeat"]
    assert flags[("maint", "alpha", 0)] == ["maintenance"]
    assert flags[("short", "alpha", 0)] == ["incomplete"]


def test_errored_load_records_no_load_but_keeps_the_step(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    lines = _load_lines("err", 1, "ghost", None, None, ok=False)
    lines += [_call_line("err", 3, "c3", "Bash", {"command": "ls"})]
    _write_session(source, "err", lines)
    got = claude_code.extract(source, CORPUS)
    assert got["loads"] == []
    assert [st["signature"] for st in got["steps"]] == ["load: ghost", "terminal: ls"]
    assert got["steps"][0]["status"] == "error" and got["steps"][0]["kind"] == "load"
    assert got["provenance"] == [] and got["skill_versions"] == [] and got["rules"] == []


def test_skips_non_json_and_noise_records(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    noise = [
        {"type": "progress", "sessionId": "noise", "uuid": "p1", "timestamp": "2026-03-01T00:00:00Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "p1", "name": "Bash", "input": {"command": "rm -rf /"}}]}},
        {"type": "system", "sessionId": "noise", "uuid": "p2", "timestamp": "2026-03-01T00:00:01Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "p2", "name": "Bash", "input": {"command": "curl http://x"}}]}},
        {"type": "file-history-snapshot", "sessionId": "noise", "uuid": "p3"},
        {"type": "queue-operation", "sessionId": "noise", "uuid": "p4"},
        {"type": "custom-title", "sessionId": "noise", "uuid": "p5"},
        {"type": "agent-name", "sessionId": "noise", "uuid": "p6"},
        {"type": "pr-link", "sessionId": "noise", "uuid": "p7"},
        {"type": "attachment", "sessionId": "noise", "uuid": "p8",
         "attachment": {"type": "skill_listing", "skills": ["commit"]}},
        _call_line("noise", 9, "t9", "Bash", {"command": "ls"}),
    ]
    path = source / "noise.jsonl"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"type": "assistant", "sessionId": "noise"\n')  # truncated line
        fh.write("not json at all\n")
        fh.write("\n")
        for record in noise:
            fh.write(io.dumps(record) + "\n")
        fh.write("\n")
    got = claude_code.extract(source, CORPUS)
    assert [st["signature"] for st in got["steps"]] == ["terminal: ls"]
    assert got["loads"] == []
    assert got["sessions"][0]["session_id"] == "noise"


def test_task_key_strips_dates_and_digits(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    prompts = {"k1": "Deploy release 12 on 2026-03-01", "k2": "deploy release on --",
               "k3": "deploy hotfix on --"}
    for sid, prompt in prompts.items():
        _write_session(source, sid, [_user_line(sid, 0, prompt)])
    got = claude_code.extract(source, CORPUS)
    keys = {s["session_id"]: s["task_key"] for s in got["sessions"]}
    assert keys["k1"] == keys["k2"] and keys["k1"] != keys["k3"]


# ------------------------------------------------------------------ corpus registry
def test_registry_has_both_corpora():
    registry = claude_code.load_registry(ROOT / "corpora.yaml")
    assert set(registry) == {"swechat-v1", "hermes-orin"}
    for name, entry in registry.items():
        assert entry["name"] == name
        for field in ("harness", "models", "date_range", "privacy", "source", "adapter", "cluster_key"):
            assert field in entry, (name, field)
    public = registry["swechat-v1"]
    assert public["privacy"] == "public" and public["license"] == "ODC-BY"
    assert public["url"] == "https://huggingface.co/datasets/cfahlgren1/SWE-chat"
    assert public["adapter"] == "claude_code" and public["cluster_key"] == "repo_id"
    private = registry["hermes-orin"]
    assert private["privacy"] == "private" and private["adapter"] == "hermes"
    assert private["cluster_key"] == "task_key"


# ------------------------------------------------------------------ raw transcript builders
def _iso(index: int) -> str:
    return f"2026-03-01T{index // 60:02d}:{index % 60:02d}:00Z"


def _user_line(session_id: str, index: int, text: str) -> dict:
    return {"type": "user", "sessionId": session_id, "uuid": f"{session_id}-u{index}", "timestamp": _iso(index),
            "message": {"role": "user", "content": text}, "version": "2.1.0"}


def _call_line(session_id: str, index: int, tool_id: str, name: str, args: dict) -> dict:
    return {"type": "assistant", "sessionId": session_id, "uuid": f"{session_id}-a{index}", "timestamp": _iso(index),
            "message": {"role": "assistant", "model": "claude-opus-4-6", "content": [
                {"type": "tool_use", "id": tool_id, "name": name, "input": args}]}, "version": "2.1.0"}


def _tool_line(session_id: str, index: int, tool_id: str, name: str, args: dict) -> list[dict]:
    """A call plus its successful result: one step per call for non-shell tools."""
    return [_call_line(session_id, index, tool_id, name, args),
            {"type": "user", "sessionId": session_id, "uuid": f"{session_id}-r{index}", "timestamp": _iso(index),
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]}}]


def _load_lines(session_id: str, index: int, skill: str, body: str | None, _probe: str | None,
                ok: bool = True) -> list[dict]:
    """A Skill call, its result, and (when given) the injected body the harness appends."""
    tool_id = f"{session_id}-skill{index}"
    result = {"type": "tool_result", "tool_use_id": tool_id, "content": f"Launching skill: {skill}"}
    if not ok:
        result["is_error"] = True
    lines = [
        _call_line(session_id, index, tool_id, "Skill", {"skill": skill}),
        {"type": "user", "sessionId": session_id, "uuid": f"{session_id}-r{index}", "timestamp": _iso(index),
         "message": {"role": "user", "content": [result]}},
    ]
    if body is not None:
        lines.append({"type": "user", "sessionId": session_id, "uuid": f"{session_id}-i{index}",
                      "timestamp": _iso(index), "isMeta": True, "sourceToolUseID": tool_id,
                      "message": {"role": "user", "content": [{"type": "text", "text": body}]}})
    return lines


def _write_session(source: Path, session_id: str, lines: list[dict]) -> None:
    io.write_jsonl(source / f"{session_id}.jsonl", lines)