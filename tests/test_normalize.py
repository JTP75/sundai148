from potency.normalize import extract_commands, program_of, shell_signatures, tool_signatures


def test_shell_with_arguments():
    assert tool_signatures("terminal", {"command": "git rebase -i HEAD~3"}) == ["terminal: git rebase"]


def test_claude_code_bash_is_shell():
    assert tool_signatures("Bash", {"command": "pytest -q tests/"}) == ["terminal: pytest"]


def test_multilevel_cli():
    assert shell_signatures("gh pr create --fill") == ["terminal: gh pr create"]
    assert shell_signatures("gh pr view 12") == ["terminal: gh pr view"]
    assert shell_signatures("gog tasks list --json") == ["terminal: gog tasks list"]


def test_single_level_cli_keeps_one_subcommand():
    assert shell_signatures("git remote add origin x") == ["terminal: git remote"]


def test_compound_command():
    assert shell_signatures("cd repo && pytest -q") == ["terminal: cd", "terminal: pytest"]
    assert shell_signatures("cat a.txt | grep foo; ls") == ["terminal: cat", "terminal: grep", "terminal: ls"]


def test_non_shell_tool_drops_path():
    assert tool_signatures("read_file", {"path": "/home/x/notes.md"}) == ["read_file"]
    assert tool_signatures("Read", {"file_path": "/home/x/notes.md"}) == ["read"]


def test_secret_bearing_command_leaks_nothing():
    cmd = "curl -H 'Authorization: Bearer sk-live-abc123' https://user:pw@example.com/x?token=zzz"
    sigs = shell_signatures(cmd)
    assert sigs == ["terminal: curl"]
    joined = " ".join(sigs)
    for secret in ("sk-live", "abc123", "pw@", "token", "example.com"):
        assert secret not in joined


def test_env_assignments_and_wrappers_skipped():
    assert shell_signatures("FOO=bar sudo -E docker compose up -d") == ["terminal: docker compose up"]
    assert shell_signatures("/usr/bin/git status") == ["terminal: git status"]


def test_uppercase_or_path_tokens_not_subcommands():
    assert shell_signatures("python scripts/run.py --x") == ["terminal: python"]
    assert shell_signatures("make Release") == ["terminal: make"]


def test_heredoc_body_ignored():
    cmd = "cat > f.txt <<'EOF'\nrm -rf /\nsecret stuff\nEOF\nls"
    assert shell_signatures(cmd) == ["terminal: cat", "terminal: ls"]


def test_empty_or_unparseable_shell():
    assert tool_signatures("terminal", {"command": ""}) == ["terminal: unknown"]
    assert shell_signatures("echo 'unbalanced") == ["terminal: echo"]


def test_extract_commands_from_skill_markdown():
    md = """# Skill
Run `gh pr create --fill` when done.

```bash
$ gog tasks list --json
git status
# a comment
```
Use `name` as the key.
"""
    assert extract_commands(md) == ["terminal: gog tasks list", "terminal: git status", "terminal: gh pr create"]


def test_program_of():
    assert program_of("terminal: git rebase") == "git"
    assert program_of("read_file") is None


def test_hashes_never_become_subcommands():
    assert shell_signatures("git show a22d461d99fa266db727519ec6cbc0b0cdb7755a") == ["terminal: git show"]
    assert shell_signatures("commit bdaa7f7b88933b2afb0fd88621ab8a42e248e552") == ["terminal: commit"]
    assert shell_signatures("git checkout 1a2b3c4") == ["terminal: git checkout"]
    assert shell_signatures("gh run view 12345") == ["terminal: gh run view"]
