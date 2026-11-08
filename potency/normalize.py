"""Command signature normalizer (design D1). Stdlib only.

A signature keeps only the tool name, and for shell commands the program plus up to one subcommand
(two for programs on KNOWN_MULTILEVEL). Arguments, paths, flags, values and quoted strings are dropped,
so a signature can never carry a secret: every kept token must match TOKEN_RE.
"""
from __future__ import annotations

import re
import shlex

SHELL_PREFIX = "terminal: "
# Tool names (any harness) whose argument is a shell command, with the argument key holding it.
SHELL_TOOLS = {"terminal": "command", "bash": "command", "shell": "command", "execute_command": "command",
               "run_shell_command": "command", "exec_command": "cmd"}
KNOWN_MULTILEVEL = {"gh", "gog", "gcloud", "docker", "kubectl", "hermes", "az", "aws", "npm", "uv", "cargo"}
# Wrappers skipped before the real program.
WRAPPERS = {"sudo", "env", "time", "nohup", "exec", "command", "builtin", "xargs", "timeout", "nice"}
# Plain utilities that never take a subcommand: their first argument is data (a path, pattern, url...).
NO_SUBCOMMAND = {
    "cd", "ls", "cat", "head", "tail", "less", "more", "grep", "rg", "egrep", "fgrep", "find", "fd", "sed", "awk",
    "echo", "printf", "rm", "rmdir", "cp", "mv", "mkdir", "touch", "chmod", "chown", "ln", "wc", "sort", "uniq",
    "cut", "tr", "tee", "diff", "file", "stat", "du", "df", "which", "type", "whereis", "sleep", "kill", "pkill",
    "curl", "wget", "ssh", "scp", "rsync", "tar", "zip", "unzip", "gzip", "gunzip", "jq", "yq", "open", "xdg-open",
    "source", ".", "export", "unset", "set", "alias", "pwd", "true", "false", "test", "date", "basename", "dirname",
    "realpath", "readlink", "python", "python3", "node", "deno", "bun", "ruby", "perl", "bash", "sh", "zsh",
    "pytest", "vim", "nano", "code", "sqlite3", "psql", "ping", "nc", "env", "printenv", "history", "clear",
}
TOKEN_RE = re.compile(r"^[a-z][a-z0-9._+-]{0,39}$")
PROGRAM_RE = re.compile(r"^[A-Za-z0-9._+-]{1,40}$")
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SPLIT_RE = re.compile(r"\|\||&&|;|\||\n|&(?!&)")


HASHLIKE_RE = re.compile(r"^[0-9a-f]{7,}$")


def _hashlike(tok: str) -> bool:
    """Commit SHAs, ids and other opaque values: hex runs of 7+ chars, or long tokens with 3+ digits."""
    return bool(HASHLIKE_RE.match(tok) and any(c.isdigit() for c in tok)) or (
        len(tok) > 20 and sum(c.isdigit() for c in tok) >= 3)


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:  # unbalanced quotes etc.
        return segment.split()


def _program(tok: str) -> str | None:
    base = tok.replace("\\", "/").rsplit("/", 1)[-1]
    if base.endswith(".exe"):
        base = base[:-4]
    base = base.lower()
    return base if PROGRAM_RE.match(base) and TOKEN_RE.match(base) else None


def shell_segment_signature(segment: str) -> str | None:
    """Signature body ("git rebase") for one simple command, or None when nothing usable remains."""
    toks = [t for t in _tokens(segment.strip()) if t]
    i = 0
    while i < len(toks) and (ASSIGN_RE.match(toks[i]) or toks[i] in WRAPPERS or toks[i] in ("(", "{", "!")):
        i += 1
        # skip wrapper options such as `timeout 30` or `env -i`
        while i < len(toks) and toks[i - 1] in ("timeout",) and re.match(r"^\d", toks[i]):
            i += 1
        while i < len(toks) and toks[i - 1] in WRAPPERS and toks[i].startswith("-"):
            i += 1
    if i >= len(toks):
        return None
    prog = _program(toks[i])
    if not prog:
        return None
    parts = [prog]
    depth = 0 if prog in NO_SUBCOMMAND else 2 if prog in KNOWN_MULTILEVEL else 1
    for tok in toks[i + 1:]:
        if len(parts) > depth:
            break
        if tok.startswith("-") or not TOKEN_RE.match(tok) or "." in tok or "/" in tok or _hashlike(tok):
            break
        parts.append(tok)
    return " ".join(parts)


def shell_signatures(command: str) -> list[str]:
    """All signatures ("terminal: git rebase", ...) for a possibly compound shell command, in order."""
    if not isinstance(command, str) or not command.strip():
        return []
    # drop heredoc bodies: everything after a line containing << up to the delimiter is data, not commands
    lines, out_lines, skip_until = command.split("\n"), [], None
    for line in lines:
        if skip_until is not None:
            if line.strip() == skip_until:
                skip_until = None
            continue
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            skip_until = m.group(1)
        out_lines.append(line)
    sigs = []
    for seg in _SPLIT_RE.split("\n".join(out_lines)):
        body = shell_segment_signature(seg)
        if body:
            sigs.append(SHELL_PREFIX + body)
    return sigs


def tool_signatures(tool_name: str, args) -> list[str]:
    """Signatures for one tool call. Shell tools expand to one signature per command segment;
    any other tool is just its (lower-cased) name. Never includes argument values."""
    name = (tool_name or "").strip()
    key = SHELL_TOOLS.get(name.lower())
    if key is not None:
        cmd = args.get(key) if isinstance(args, dict) else None
        sigs = shell_signatures(cmd) if isinstance(cmd, str) else []
        return sigs or [SHELL_PREFIX + "unknown"]
    clean = name.lower()
    return [clean] if re.match(r"^[a-z0-9_.:-]{1,80}$", clean) else ["unknown_tool"]


def extract_commands(markdown: str) -> list[str]:
    """Candidate signatures prescribed by a SKILL.md: shell lines in fenced code blocks and inline
    backticks, normalized with the same rules. Order-preserving, de-duplicated."""
    if not isinstance(markdown, str):
        return []
    found: list[str] = []
    for block in re.findall(r"```[a-zA-Z0-9_-]*\n(.*?)```", markdown, flags=re.S):
        for line in block.splitlines():
            if line.lstrip().startswith("#"):
                continue
            line = re.sub(r"^\s*[$>]\s+", "", line).strip()
            if line:
                found.extend(shell_signatures(line))
    stripped = re.sub(r"```.*?```", "", markdown, flags=re.S)
    for inline in re.findall(r"`([^`\n]{2,200})`", stripped):
        if " " in inline.strip() or re.match(r"^[a-z][a-z0-9_-]+$", inline.strip()):
            body = shell_segment_signature(inline)
            if body and " " in body:  # bare words in backticks are usually names, not commands
                found.append(SHELL_PREFIX + body)
    seen, out = set(), []
    for s in found:
        if s not in seen and s != SHELL_PREFIX + "unknown":
            seen.add(s)
            out.append(s)
    return out


def program_of(signature: str) -> str | None:
    """Program name of a shell signature ("terminal: git rebase" -> "git"), else None."""
    if signature.startswith(SHELL_PREFIX):
        rest = signature[len(SHELL_PREFIX):].split(" ")
        return rest[0] if rest and rest[0] else None
    return None
