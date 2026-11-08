"""Privacy tests (W1): allowlist, regex backstop, and the sample's must-not-appear strings."""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from potency import bundle, extract, io, privacy, schema
from tests.fixtures.hermes_sample import EXPECTED, FAKE_SECRET, build

FORBIDDEN = EXPECTED["must_not_appear_anywhere"]
CORPUS = "hermes-sample"
FREE_TEXT_WORDS = ("content", "prompt", "query", "arguments", "args", "text", "body", "description",
                   "output", "result", "message", "reasoning", "title")


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    base = tmp_path_factory.mktemp("privacy")
    sample = build(base / "src")
    data = base / "data"
    extract.main(["--adapter", "hermes", "--corpus", CORPUS, "--source", str(sample["home"]), "--out", str(data)])
    zip_path = bundle.bundle(data / CORPUS, base / "out", CORPUS)
    return {"corpus_dir": data / CORPUS, "zip": zip_path}


def test_must_not_appear_in_any_exported_file(exported):
    for path in sorted(exported["corpus_dir"].iterdir()):
        if path.suffix.lower() in (".zip", ".png", ".db", ".sqlite"):
            continue
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            assert needle not in text, (path.name, needle)


def test_must_not_appear_in_the_bundle(exported):
    with zipfile.ZipFile(exported["zip"]) as archive:
        for name in archive.namelist():
            data = archive.read(name).decode("utf-8", errors="ignore")
            for needle in FORBIDDEN:
                assert needle not in data, (name, needle)


def test_allowlist_has_no_free_text_columns():
    for table, columns in schema.TABLES.items():
        for column in columns:
            lowered = column.lower()
            assert lowered not in FREE_TEXT_WORDS, (table, column)
            assert not lowered.endswith(("_text", "_body", "_prompt")), (table, column)


def test_extra_column_is_rejected(exported, tmp_path):
    corpus_dir = tmp_path / "corpus"
    shutil.copytree(exported["corpus_dir"], corpus_dir)
    rows = io.read_jsonl(corpus_dir / "steps.jsonl")
    rows[0]["query"] = "a search query"
    io.write_jsonl(corpus_dir / "steps.jsonl", rows)
    with pytest.raises(privacy.PrivacyError, match="steps.jsonl"):
        privacy.check_corpus_dir(corpus_dir)


def test_missing_column_is_rejected(exported, tmp_path):
    corpus_dir = tmp_path / "corpus"
    shutil.copytree(exported["corpus_dir"], corpus_dir)
    rows = io.read_jsonl(corpus_dir / "loads.jsonl")
    rows[0].pop("trigger")
    io.write_jsonl(corpus_dir / "loads.jsonl", rows)
    with pytest.raises(privacy.PrivacyError, match="loads.jsonl"):
        privacy.check_corpus_dir(corpus_dir)


def test_forbidden_string_in_a_json_file_is_rejected(exported, tmp_path):
    corpus_dir = tmp_path / "corpus"
    shutil.copytree(exported["corpus_dir"], corpus_dir)
    manifest = io.read_json(corpus_dir / "manifest.json")
    manifest["note"] = FAKE_SECRET
    io.write_json(corpus_dir / "manifest.json", manifest)
    with pytest.raises(privacy.PrivacyError, match="manifest.json"):
        privacy.check_corpus_dir(corpus_dir)


def test_forbidden_argument_is_rejected(exported, tmp_path):
    corpus_dir = tmp_path / "corpus"
    shutil.copytree(exported["corpus_dir"], corpus_dir)
    with pytest.raises(privacy.PrivacyError, match="forbidden string"):
        privacy.check_corpus_dir(corpus_dir, forbidden=["terminal: gog tasks list"])


@pytest.mark.parametrize("value", [
    "ghp_" + "A" * 24,
    "sk-" + "a" * 24,
    "Bearer abcdefgh12345",
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "xoxb-1234567890-abcdef",
    "https://api.example.com/v1/items",
    "http://localhost:8080/x",
    "/home/pacel/notes.md",
    "C:\\Users\\pacel\\notes.md",
    "~/secrets/token",
    "0123456789abcdef" * 3,
    "abc123ABC" * 6,
    "a note that mentions 2a4f9c1e7b3d5a0c8e6f4b2d9c7a5e3f1b0d8c6a4e2f",
])
def test_secret_like_values_are_rejected(value):
    with pytest.raises(privacy.PrivacyError):
        privacy.scan_string("value", value)


@pytest.mark.parametrize("value", [
    "terminal: git rebase",
    "terminal: gh pr create",
    "load: gog-cli",
    "read_file",
    "job-1",
    "60d400235fd15b10",
    "curator",
    "hash-only",
    "section 1",
])
def test_clean_values_pass(value):
    privacy.scan_string("value", value)


def test_csv_scan(exported, tmp_path):
    corpus_dir = tmp_path / "corpus"
    shutil.copytree(exported["corpus_dir"], corpus_dir)
    io.write_csv(corpus_dir / "extra.csv", [{"skill": "x", "note": "https://example.com/leak"}], ["skill", "note"])
    with pytest.raises(privacy.PrivacyError, match="extra.csv"):
        privacy.check_corpus_dir(corpus_dir)


def test_checksum_file_format(exported, tmp_path):
    corpus_dir = tmp_path / "corpus"
    shutil.copytree(exported["corpus_dir"], corpus_dir)
    (corpus_dir / schema.CHECKSUMS_FILE).write_text("not a checksum line\n", encoding="utf-8")
    with pytest.raises(privacy.PrivacyError, match="malformed"):
        privacy.check_corpus_dir(corpus_dir)
    io.write_checksums(corpus_dir, ["steps.jsonl"])
    privacy.check_corpus_dir(corpus_dir)


def test_missing_corpus_dir_is_rejected(tmp_path):
    with pytest.raises(privacy.PrivacyError):
        privacy.check_corpus_dir(tmp_path / "nope")


def test_private_arguments_are_decoded_nowhere(exported):
    """Every exported step is a signature; the fixture's search query and path must be gone."""
    steps = io.read_table(exported["corpus_dir"], "steps")
    signatures = {row["signature"] for row in steps}
    assert "search_files" in signatures
    assert not any(" " in signature for signature in signatures if not signature.startswith(("terminal: ", "load: ")))
    blob = json.dumps(steps)
    for needle in EXPECTED["must_not_appear_anywhere"]:
        assert needle not in blob
