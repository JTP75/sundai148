"""Foundation contract tests: schema, deterministic I/O, frozen fixtures, stage entry points."""
import filecmp
import subprocess
import sys
from pathlib import Path

import pytest

from potency import io, schema

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
SYN = FIX / "synthetic" / "synth"
GOLDEN = FIX / "synthetic" / "golden"
STAGES = ["extract", "census", "draft_rules", "bundle", "evidence", "expect", "score", "report", "run_all"]


@pytest.mark.parametrize("table", list(schema.TABLES))
def test_fixture_tables_match_schema(table):
    rows = io.read_table(SYN, table)
    assert rows, table
    schema.validate_rows(table, rows)


def test_fixtures_regenerate_byte_identically(tmp_path):
    sys.path.insert(0, str(ROOT / "tests"))
    import make_fixtures

    make_fixtures.write_synthetic(tmp_path / "synthetic")
    make_fixtures.write_claude_code_sample(tmp_path / "claude_code_sample")
    for sub in ("synthetic", "claude_code_sample"):
        cmp = filecmp.dircmp(FIX / sub, tmp_path / sub)
        stack = [cmp]
        while stack:
            c = stack.pop()
            assert not c.left_only and not c.right_only, (c.left, c.left_only, c.right_only)
            _, mismatch, errors = filecmp.cmpfiles(c.left, c.right, c.common_files, shallow=False)
            assert not mismatch and not errors, (c.left, mismatch, errors)
            stack.extend(c.subdirs.values())


def test_handcrafted_cases_match_golden_evidence():
    cases = io.read_json(GOLDEN / "cases.json")
    ev = io.read_csv(GOLDEN / "evidence.csv")
    for case in cases:
        rows = [r for r in ev if r["session_id"] == case["session_id"] and r["rule_id"] == case["rule_id"]]
        if case["status"] is None:
            assert rows == [], case
            continue
        assert rows, case
        assert (rows[0]["status"], rows[0]["reason"]) == (case["status"], case["reason"]), case


def test_every_status_and_reason_is_covered():
    ev = io.read_csv(GOLDEN / "evidence.csv")
    seen = {(r["status"], r["reason"]) for r in ev}
    for status, reasons in schema.REASONS.items():
        for reason in reasons:
            assert (status, reason) in seen, (status, reason)


def _window_rate(sig: str) -> float:
    """Share of complete no-load windows (N steps after a non-load step) containing sig."""
    steps = io.read_table(SYN, "steps")
    loads = io.read_table(SYN, "loads")
    loaded = {ld["session_id"] for ld in loads}
    by_sid = {}
    for st in steps:
        by_sid.setdefault(st["session_id"], []).append(st)
    hits = total = 0
    for sid, ss in by_sid.items():
        if sid in loaded:
            continue
        sigs = [s["signature"] for s in sorted(ss, key=lambda s: s["step"])]
        for t in range(len(sigs) - schema.WINDOW_N):
            total += 1
            hits += sig in sigs[t + 1: t + 1 + schema.WINDOW_N]
    return hits / total


def test_habit_command_below_ceiling_and_novel_command_unseen():
    assert 0.05 < _window_rate("terminal: git commit") < schema.BASE_RATE_CEILING
    assert _window_rate("terminal: gog tasks list") == 0.0


def test_golden_known_effects():
    k = io.read_json(GOLDEN / "potency_expect.json")
    lift = k["unweighted_mean_lift"]
    assert abs(lift["habit-skill"]) <= k["expect"]["habit-skill"]["abs_max"]
    assert lift["novel-skill"] >= k["expect"]["novel-skill"]["min"]
    assert lift["mid-skill"] >= k["expect"]["mid-skill"]["min"]


def test_paired_runs_present():
    sess = io.read_table(SYN, "sessions")
    arms = {}
    for s in sess:
        if s["pair_id"]:
            arms.setdefault(s["pair_id"], set()).add(s["pair_arm"])
    assert len(arms) == 20 and all(v == {"with_skill", "without_skill"} for v in arms.values())


def test_io_roundtrip_and_checksums(tmp_path):
    rows = [{"b": 1.23456789, "a": "x", "c": [1, 2.0]}, {"a": "y", "b": -0.0000001, "c": []}]
    io.write_jsonl(tmp_path / "t.jsonl", rows)
    text = (tmp_path / "t.jsonl").read_bytes()
    assert b"\r" not in text and text.startswith(b'{"a":"x","b":1.234568')
    io.write_checksums(tmp_path, ["t.jsonl"])
    io.verify_checksums(tmp_path)
    (tmp_path / "t.jsonl").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="t.jsonl"):
        io.verify_checksums(tmp_path)


def test_csv_float_format(tmp_path):
    io.write_csv(tmp_path / "x.csv", [{"a": 0.1, "b": None, "c": True, "d": [3, 4]}], ["a", "b", "c", "d"])
    assert (tmp_path / "x.csv").read_text(encoding="utf-8") == "a,b,c,d\n0.100000,,true,3 4\n"


def test_episode_id_deterministic():
    assert schema.episode_id("c", "s", 3) == schema.episode_id("c", "s", 3)
    assert len(schema.episode_id("c", "s", 3)) == 16


@pytest.mark.parametrize("stage", STAGES)
def test_stage_help(stage):
    r = subprocess.run([sys.executable, "-m", f"potency.{stage}", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
