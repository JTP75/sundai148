"""Source-machine stage tests (W1): extract, census, draft_rules, bundle, stdlib-only."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest

from potency import bundle, census, draft_rules, extract, io, privacy, schema
from tests.fixtures.hermes_sample import build

ROOT = Path(__file__).resolve().parent.parent
CORPUS = "hermes-sample"
OUTCOME_WORDS = ("adherence", "lift", "follow", "match", "potency", "expect", "score")
STDLIB_BLOCKER = """
import sys
BLOCKED = {"numpy", "pandas", "sklearn", "matplotlib", "yaml", "pyarrow", "scipy", "torch", "requests"}
class _Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ImportError("source stages must be stdlib only; blocked " + fullname)
        return None
sys.meta_path.insert(0, _Block())
sys.path.insert(0, __ROOT__)
try:
    import numpy  # noqa: F401
except ImportError:
    print("blocked")
import potency.extract, potency.census, potency.draft_rules, potency.bundle, potency.privacy
import potency.adapters.hermes
print("ok")
"""


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    base = tmp_path_factory.mktemp("pipeline")
    sample = build(base / "src")
    data, out = base / "data", base / "out"
    extract.main(["--adapter", "hermes", "--corpus", CORPUS, "--source", str(sample["home"]), "--out", str(data)])
    census.main(["--corpus", CORPUS, "--data", str(data)])
    draft_rules.main(["--corpus", CORPUS, "--skills", str(sample["skills"]), "--data", str(data)])
    zip_path = bundle.bundle(data / CORPUS, out, CORPUS)
    return {"base": base, "sample": sample, "data": data, "corpus_dir": data / CORPUS,
            "zip": zip_path, "out": out}


def _tree_keys(obj) -> list[str]:
    keys = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            keys.append(str(key))
            keys.extend(_tree_keys(value))
    elif isinstance(obj, list):
        for value in obj:
            keys.extend(_tree_keys(value))
    return keys


# ---------------------------------------------------------------- extract
def test_extract_writes_every_table(pipeline):
    for table in schema.TABLES:
        path = pipeline["corpus_dir"] / f"{table}.jsonl"
        assert path.is_file(), table
        schema.validate_rows(table, io.read_table(pipeline["corpus_dir"], table))


def test_manifest_records_the_snapshot(pipeline):
    manifest = io.read_json(pipeline["corpus_dir"] / "manifest.json")
    assert manifest["corpus"] == CORPUS and manifest["adapter"] == "hermes"
    assert manifest["max_message_id"] == 35
    assert manifest["max_timestamp"] >= manifest["split_cutoff_ts"] > 0
    assert manifest["row_counts"] == {table: len(io.read_table(pipeline["corpus_dir"], table))
                                      for table in schema.TABLES}
    sha = manifest["extractor_git_sha"]
    assert sha is None or (len(sha) == 40 and int(sha, 16) >= 0)
    assert manifest["split_counts"] == {"train": 2, "test": 2}
    assert manifest["source"]["ledger"]["before_after_content"] == "hash-only"


def test_extract_is_byte_identical_across_runs(pipeline, tmp_path):
    again = tmp_path / "data"
    extract.main(["--adapter", "hermes", "--corpus", CORPUS, "--source", str(pipeline["sample"]["home"]),
                  "--out", str(again)])
    for name in [f"{table}.jsonl" for table in schema.TABLES] + ["manifest.json"]:
        assert io.sha256_file(again / CORPUS / name) == io.sha256_file(pipeline["corpus_dir"] / name), name


def test_extract_runs_the_privacy_backstop(tmp_path, pipeline):
    with pytest.raises(privacy.PrivacyError, match="forbidden string"):
        extract.main(["--adapter", "hermes", "--corpus", CORPUS, "--source", str(pipeline["sample"]["home"]),
                      "--out", str(tmp_path / "data"), "--forbidden", "terminal: gog tasks list"])


def test_extract_does_not_eagerly_import_an_adapter():
    code = ("import sys; sys.path.insert(0, %r); import potency.extract; "
            "print('potency.adapters.hermes' in sys.modules, 'potency.adapters.claude_code' in sys.modules)" % str(ROOT))
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "False False"


def test_extract_dispatches_claude_code_lazily(tmp_path, monkeypatch):
    fake = types.ModuleType("potency.adapters.claude_code")
    calls = []

    def fake_extract(source, corpus):
        calls.append((str(source), corpus))
        return {table: [] for table in schema.TABLES}

    fake.extract = fake_extract
    monkeypatch.setitem(sys.modules, "potency.adapters.claude_code", fake)
    import potency.adapters as adapters_pkg  # the real module may already be bound as a package attribute

    monkeypatch.setattr(adapters_pkg, "claude_code", fake, raising=False)
    source = tmp_path / "transcripts"
    source.mkdir()
    out = tmp_path / "data"
    assert extract.main(["--adapter", "claude_code", "--corpus", "cc-sample",
                         "--source", str(source), "--out", str(out)]) == 0
    assert calls == [(str(source), "cc-sample")]
    manifest = io.read_json(out / "cc-sample" / "manifest.json")
    assert manifest["adapter"] == "claude_code"
    assert manifest["row_counts"] == {table: 0 for table in schema.TABLES}


# ---------------------------------------------------------------- census
def test_census_is_outcome_free(pipeline):
    census_doc = io.read_json(pipeline["corpus_dir"] / "census.json")
    assert census_doc["outcome_free"] is True
    for key in _tree_keys(census_doc):
        lowered = key.lower()
        for word in OUTCOME_WORDS:
            assert word not in lowered, (key, word)


def test_census_counts_loads(pipeline):
    census_doc = io.read_json(pipeline["corpus_dir"] / "census.json")
    assert census_doc["loads"]["total"] == 6
    assert census_doc["loads"]["scorable"] == 4
    assert census_doc["loads"]["excluded_by_reason"] == {"maintenance": 1, "no_rules": 1, "repeat": 1}
    assert census_doc["loads"]["flagged"] == {"incomplete": 6, "overlap": 2}
    assert census_doc["loads"]["triggers"] == {"chosen": 4, "instructed": 1, "preloaded": 1}
    assert census_doc["loads"]["version_sources"] == {"skill_manage": 2, "version_core": 4}


def test_census_reports_skills_clusters_and_preloads(pipeline):
    census_doc = io.read_json(pipeline["corpus_dir"] / "census.json")
    skills = {row["skill"]: row for row in census_doc["skills"]}
    assert set(skills) == {"gog-cli", "job-tracker", "prose-only"}
    assert skills["gog-cli"]["n_sessions"] == 2 and skills["gog-cli"]["n_clusters"] == 2
    assert skills["prose-only"]["scorable_loads"] == 0
    assert skills["job-tracker"]["version_sources"] == {"skill_manage": 2, "version_core": 1}
    assert census_doc["preload"] == {"cron_sessions": 1, "cron_sessions_mapped": 1, "preloaded_loads": 1,
                                     "sessions_with_preload": 1, "skills": ["gog-cli"]}
    assert census_doc["sessions"]["with_task_key"] == 4
    assert census_doc["sessions"]["distinct_clusters"] == 4
    assert census_doc["ledger"]["rows"] == 1
    programs = {row["program"]: row["steps"] for row in census_doc["programs"]}
    assert programs["gog"] == 2 and programs["git"] == 1
    assert {"tool": "search_files", "steps": 1} in census_doc["tools"]
    assert census_doc["eligibility"]["meets_bar"] is False


def test_census_does_not_read_outcomes(pipeline):
    """The census must not depend on any file the analysis stages write."""
    text = (pipeline["corpus_dir"] / "census.json").read_text(encoding="utf-8")
    assert "evidence" not in text
    assert not (pipeline["corpus_dir"] / "out").exists()


def test_census_runs_unchanged_on_another_harness_corpus(tmp_path):
    """The census reads only the intermediate tables, so a Claude Code shaped corpus works as is."""
    corpus_dir = tmp_path / "synth"
    shutil.copytree(Path(__file__).resolve().parent / "fixtures" / "synthetic" / "synth", corpus_dir)
    assert census.main(["--corpus", "synth", "--data", str(tmp_path)]) == 0
    doc = io.read_json(corpus_dir / "census.json")
    assert doc["loads"]["total"] == 290
    assert doc["loads"]["scorable"] == 287
    assert doc["loads"]["excluded_by_reason"] == {"maintenance": 1, "no_rules": 1, "repeat": 1}
    skills = {row["skill"]: row for row in doc["skills"]}
    assert skills["empty-skill"]["scorable_loads"] == 0  # a rule with no observable can never match
    assert doc["sessions"]["distinct_clusters"] == 34


# ---------------------------------------------------------------- draft rules
def test_draft_rules_shape(pipeline):
    draft = io.read_json(pipeline["corpus_dir"] / "rules_draft.json")
    assert draft["approved"] is False
    assert len(draft["rules"]) == 3
    assert draft["skills_without_commands"] == ["prose-only"]
    for rule in draft["rules"]:
        assert rule["approved"] is False and rule["rule_source"] == "draft"
        assert rule["obligation"] in schema.OBLIGATIONS
        assert rule["applicability"] is None and rule["alternatives"] == []
        assert rule["location"].startswith("section ")
        assert rule["observable"]
        assert rule["version_id"] and rule["rule_id"]
    by_skill = {}
    for rule in draft["rules"]:
        by_skill.setdefault(rule["skill"], []).append(rule["observable"][0])
    assert by_skill == {"gog-cli": ["terminal: gog tasks list", "terminal: gog auth login"],
                        "job-tracker": ["terminal: hermes jobs status"]}


def test_draft_rules_export_no_skill_text(pipeline):
    text = (pipeline["corpus_dir"] / "rules_draft.json").read_text(encoding="utf-8")
    for prose in ("gog CLI", "Job tracker", "Prose", "Think carefully", "Always run"):
        assert prose not in text


def test_draft_rules_obligation_guesses(tmp_path):
    skills = tmp_path / "skills"
    (skills / "demo").mkdir(parents=True)
    body = (
        "# Demo\n\n"
        "Run `demo status` first.\n\n"
        "## Inspect\n\n"
        "Use this, e.g. for a quick look:\n\n"
        "```bash\n"
        "demo show --all\n"
        "```\n\n"
        "## Danger\n\n"
        "Never run this:\n\n"
        "```bash\n"
        "demo wipe\n"
        "```\n\n"
        "## Routine\n\n"
        "```bash\n"
        "demo list\n"
        "```\n"
    )
    (skills / "demo" / "SKILL.md").write_text(body, encoding="utf-8")
    draft = draft_rules.build_draft(skills, "demo-corpus")
    got = {rule["observable"][0]: (rule["obligation"], rule["location"]) for rule in draft["rules"]}
    assert got["terminal: demo status"] == ("required", "section 1")
    assert got["terminal: demo show"] == ("example", "section 2")
    assert got["terminal: demo wipe"] == ("avoid", "section 3")
    assert got["terminal: demo list"] == ("required", "section 4")
    assert [rule["rule_id"] for rule in draft["rules"]] == ["draft-01", "draft-02", "draft-03", "draft-04"]


# ---------------------------------------------------------------- bundle
def test_bundle_members_and_checksums(pipeline):
    assert pipeline["zip"].name.startswith(f"derived-{CORPUS}-")
    assert pipeline["zip"].suffix == ".zip"
    manifest_hash = io.sha256_file(pipeline["corpus_dir"] / "manifest.json")[:12]
    assert pipeline["zip"].name == f"derived-{CORPUS}-{manifest_hash}.zip"
    with zipfile.ZipFile(pipeline["zip"]) as archive:
        names = archive.namelist()
        expected = sorted([f"{table}.jsonl" for table in schema.TABLES]
                          + ["manifest.json", "census.json", "rules_draft.json", schema.CHECKSUMS_FILE])
        assert names == expected
        unpacked = pipeline["base"] / "unpacked"
        archive.extractall(unpacked)
    io.verify_checksums(unpacked)
    assert (unpacked / "census.json").is_file()


def test_bundle_is_deterministic(pipeline, tmp_path):
    first = pipeline["zip"].read_bytes()
    again = bundle.bundle(pipeline["corpus_dir"], tmp_path / "out", CORPUS)
    assert again.name == pipeline["zip"].name
    assert again.read_bytes() == first


def test_bundle_verifies_checksums(pipeline, tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    for name in bundle.source_files(pipeline["corpus_dir"]):
        (corpus_dir / name).write_bytes((pipeline["corpus_dir"] / name).read_bytes())
    bundle.bundle(corpus_dir, tmp_path / "out", CORPUS)
    io.write_table(corpus_dir, "sessions", io.read_table(corpus_dir, "sessions")[:3])
    with pytest.raises(ValueError, match="sessions.jsonl"):
        bundle.bundle(corpus_dir, tmp_path / "out2", CORPUS, verify=True)


def test_bundle_refuses_private_text(pipeline, tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    for name in bundle.source_files(pipeline["corpus_dir"]):
        (corpus_dir / name).write_bytes((pipeline["corpus_dir"] / name).read_bytes())
    (corpus_dir / "notes.md").write_text("see https://example.com/private\n", encoding="utf-8")
    with pytest.raises(privacy.PrivacyError, match="notes.md"):
        bundle.bundle(corpus_dir, tmp_path / "out", CORPUS)
    assert not list((tmp_path / "out").glob("*.zip"))


# ---------------------------------------------------------------- stdlib only
def test_source_stages_are_stdlib_only():
    done = subprocess.run([sys.executable, "-I", "-c", STDLIB_BLOCKER.replace("__ROOT__", repr(str(ROOT)))],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["blocked", "ok"]


def test_expected_workflow_is_reproducible_from_the_cli(pipeline):
    """The four stages run as `python -m potency.<stage>` on a source dir (design D11)."""
    data = pipeline["base"] / "cli-data"
    steps = [
        ["-m", "potency.extract", "--adapter", "hermes", "--corpus", CORPUS,
         "--source", str(pipeline["sample"]["home"]), "--out", str(data)],
        ["-m", "potency.census", "--corpus", CORPUS, "--data", str(data)],
        ["-m", "potency.draft_rules", "--corpus", CORPUS, "--skills", str(pipeline["sample"]["skills"]),
         "--data", str(data)],
        ["-m", "potency.bundle", "--corpus", CORPUS, "--data", str(data), "--out", str(pipeline["base"] / "cli-out")],
    ]
    for args in steps:
        done = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
        assert done.returncode == 0, (args, done.stderr)
    zips = sorted((pipeline["base"] / "cli-out").glob("*.zip"))
    assert [path.name for path in zips] == [pipeline["zip"].name]


def test_census_build_matches_written_file(pipeline):
    census_doc = json.loads((pipeline["corpus_dir"] / "census.json").read_text(encoding="utf-8"))
    assert census.build_census(pipeline["corpus_dir"], CORPUS)["loads"] == census_doc["loads"]
    assert census_doc["snapshot"]["max_message_id"] == 35
