"""Source machine, stdlib only: draft rule map from versioned skill text (no text exported).

Design D13: an agent drafts, a human approves. The draft carries rule ids, obligation guesses and
observable signatures; skill prose never leaves the machine. A rule is ``example`` when the block is
introduced by "e.g."/"example", ``avoid`` when the command line or its introducing sentence says
never/do not/avoid, and ``required`` otherwise. Every draft rule is ``approved: false``.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from potency import io, normalize, schema

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
EXAMPLE_RE = re.compile(r"(\be\.g\.|\bfor example\b|\bfor instance\b|\bexamples?\b)", re.IGNORECASE)
AVOID_RE = re.compile(r"\b(never|don't|do not|must not|should not|avoid)\b", re.IGNORECASE)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m potency.draft_rules', description='Source machine, stdlib only: draft rule map from versioned skill text (no text exported).')
    p.add_argument('--corpus', required=True, help='corpus name')
    p.add_argument('--skills', required=True, help='dir holding SKILL.md files')
    p.add_argument('--data', default=None, help='data dir')
    return p


def obligation_guess(command_line: str, context: str) -> str:
    """Design D13 obligation guess for one drafted rule."""
    if AVOID_RE.search(command_line):
        return "avoid"
    if AVOID_RE.search(context):
        return "avoid"
    if EXAMPLE_RE.search(context):
        return "example"
    return "required"


def _candidates(text: str):
    """Yield (signature, command_line, introducing_context, section_index) in document order."""
    lines = text.splitlines()
    section = 0
    context = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        heading = HEADING_RE.match(line)
        if heading:
            section += 1
            context = heading.group(2).strip()
            index += 1
            continue
        if line.strip().startswith("```"):
            block = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1  # closing fence
            for body in block:
                command = re.sub(r"^\s*[$>]\s+", "", body).strip()
                if not command or command.startswith("#"):
                    continue
                for signature in normalize.shell_signatures(command):
                    yield signature, command, context, section
            continue
        for inline in re.findall(r"`([^`\n]{2,200})`", line):
            body = normalize.shell_segment_signature(inline)
            if body and " " in body:  # a bare backticked word is usually a name, not a command
                yield normalize.SHELL_PREFIX + body, inline, line.strip(), section
        if line.strip():
            context = line.strip()
        index += 1


def draft_skill(skill: str, version_id: str, text: str) -> list[dict]:
    rules: list[dict] = []
    seen: set[str] = set()
    for signature, command, context, section in _candidates(text):
        if signature in seen:
            continue
        seen.add(signature)
        rules.append({
            "corpus": "",
            "skill": skill,
            "version_id": version_id,
            "rule_id": f"draft-{len(rules) + 1:02d}",
            "obligation": obligation_guess(command, context),
            "applicability": None,
            "observable": [signature],
            "alternatives": [],
            "location": f"section {section}",
            "rule_source": "draft",
            "approved": False,
        })
    return rules


def build_draft(skills_dir, corpus: str) -> dict:
    rules: list[dict] = []
    skipped: list[str] = []
    for path in sorted(Path(skills_dir).rglob("SKILL.md")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        skill = path.parent.name
        skill_rules = draft_skill(skill, schema.content_id(text), text)
        if not skill_rules:
            skipped.append(skill)
        for rule in skill_rules:
            rule["corpus"] = corpus
            rules.append(rule)
    rules.sort(key=lambda r: (r["skill"], r["rule_id"]))
    return {
        "corpus": corpus,
        "generated_by": "potency.draft_rules",
        "approved": False,
        "note": "draft rule map; a human approves or edits each rule before it is scored",
        "rules": rules,
        "skills_without_commands": sorted(skipped),
    }


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    corpus_dir = io.resolve_data_dir(args.data) / args.corpus
    draft = build_draft(args.skills, args.corpus)
    out = corpus_dir / "rules_draft.json"
    io.write_json(out, draft)
    print(f"rules\t{len(draft['rules'])} skills_without_commands\t{len(draft['skills_without_commands'])}")
    print(f"draft\t{out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
