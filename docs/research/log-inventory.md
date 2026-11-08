# Agent session log inventory (2026-11-08)

Read-only reconnaissance. No logs were modified, moved or copied between machines. Analysis scripts were piped to remote python3 over stdin and only counts, names and dates were returned. All SQLite was opened with `mode=ro`.

## 1. Summary table

| Machine | Harness | Sessions | Date range | Size | Tool calls | Skill loads | Distinct skills |
|---|---|---|---|---|---|---|---|
| Mac (local) | Claude Code | 274 jsonl (266 top-level + 8 subagent) | 2026-10-09 to 2026-11-08 | 147 MB | 3,279 | 8 Skill-tool + 25 slash (non-builtin, 4 of them junk) | 2 + 5 |
| Mac | Hermes | 3 (state.db is tiny) | 2026-11-07 to 11-08 | state.db 5 MB, whole ~/.hermes 4.8 GB | 195 | 1 skill_view | 1 |
| Mac | OpenCode (session_v2 schema) | 37 sessions, 1,348 msgs | not extracted | 79 MB | not counted | ~5 skill-ish rows | n/a |
| Mac | Qwen Code | 44 jsonl | not extracted | 9.6 MB | not counted | not counted | n/a |
| pacel-pc | Claude Code | 703 jsonl (669 top-level + 34 subagent); 540 are in `-tmp` | 2026-09-29 to 2026-11-08 | 288 MB | 7,486 | 14 Skill-tool, 0 slash skills | 4 |
| pacel-pc | Hermes | 3 | 2026-08-24 to 08-26 | ~6.1 GB dir, small DB | 48 | 8 skill_view | 5 |
| pacel-pc | OpenCode | 610 `session` + 742 `session_v2`, 22,363 msgs, 95,887 parts, 29,133 session_message | not extracted | 3.0 GB | not counted | ~64 skill-ish rows in session_message (unverified) | n/a |
| pacel-pc | Qwen Code | 50 jsonl | not extracted | 1.8 GB | not counted | not counted | n/a |
| pacel-pc | Codex | 2 session jsonl (plus sqlite logs) | not extracted | 1.8 GB (mostly non-session) | not counted | not counted | n/a |
| pacel-orin | Claude Code | 2 jsonl | 2026-10-02 to 10-22 | 1.2 MB | 36 | 0 | 0 |
| pacel-orin | **Hermes** | **1,325** | **2026-05-26 to 2026-11-08** | state.db 422 MB | **13,129 parsed (sessions.tool_call_count sum 10,124)** | **254 skill_view** | **68** |
| pacel-vivobook | all | UNREACHABLE | - | - | - | - | - |

## 2. Per machine

### Mac (local), Darwin
- Claude Code: `~/.claude/projects/*/*.jsonl`. 19 project dirs. Top by session count: `-private-tmp` 218, `-Users-pacel` 17, `-Users-pacel-misc-scienceclaw-hack` 9, `-Users-pacel-misc` 5, `-Users-pacel-misc-office-agency` 3. No other claude config dirs found.
- Top tools: Bash 1984, Edit 316, StructuredOutput 237, Read 196, Write 185, WebSearch 55, WebFetch 43, ToolSearch 31, gold_comparer 28, mcp__claude-artifacts__publish_files 26, test_auditor 26, issue_reader 22, history_agent 20, Agent 16, ExitPlanMode 14.
- Skill-tool loads 8: orca-cli 7, openspec-propose 1. Slash-invoked non-builtin: opsx:update 8, frontend-design:frontend-design 5, openspec-propose 5, plus 7 junk matches (`xyz` 5, a regex literal 2). Builtin slash commands: 62 (model 14, branch 11, clear 9, login 8, rename 6, plugin 5, compact 5, config 4).
- Installed skills: 9 in `~/.claude/skills/*/SKILL.md`, 87 SKILL.md under `~/.claude/plugins/`, about 18 project-level `.claude/skills`.
- Subagents: 8 files under `<project>/<session-id>/subagents/*.jsonl`, plus 103 `isSidechain` tool_use lines.
- Other: `~/.hermes` (4.8 GB, mostly hermes-agent source/caches, DB tiny), `~/.local/share/opencode/opencode.db`, `~/.qwen/projects` (44 jsonl). No codex/gemini/cursor.

### pacel-pc, Ubuntu 24.04 Linux x86_64, reachable (key auth)
- Claude Code `/home/pacel/.claude/projects`: 20 project dirs. `-tmp` 540, `-home-pacel-misc-scienceclaw-hack-harness-eval` 54, `-home-pacel-agentic-highway-vettd` 26, `-home-pacel-misc-llama` 16, `-home-pacel` 5, orca-workspaces vettd dirs 5+3, `-home-pacel-misc-scienceclaw-hack` 4, `-home-pacel-misc` 4, `-home-pacel--config-opencode` 2.
- Top tools: Bash 6240, Write 285, Edit 204, Read 160, ScheduleWakeup 107, StructuredOutput 101, AskUserQuestion 93, Monitor 55, WebFetch 54, ToolSearch 46, ExitPlanMode 35, Agent 28, WebSearch 26, TaskStop 24, Skill 14.
- Skill loads 14: orca-cli 10, orchestration 2, code-review 1, workflow-authoring 1. Builtin slash 213 (/loop 149, model 21, usage 17, rename 8, compact 5). Zero non-builtin slash skills.
- Installed skills: 3 user, 96 under plugins, many project-level (find capped at 500).
- Subagents: 34 files in `subagents/` subfolders; 822 sidechain tool_use lines.
- Other harnesses: Hermes DB with 3 sessions; OpenCode (3.0 GB, 610 sessions, the biggest non-Hermes corpus); Qwen 50 jsonl; Codex (`~/.codex`, 2 session files); no python sqlite issues.

### pacel-vivobook, Arch Linux
- First probe (uname) answered; the later full scan timed out: `ssh: connect to host pacel-vivobook port 22: Operation timed out`. Treat as unreachable or asleep; no data collected. Retry later when it is awake.

### pacel-orin, Linux 5.15 tegra aarch64 (Jetson), reachable
- Claude Code `/home/pacel/.claude/projects`: only 2 sessions (`-home-pacel-auricle-engine`, `-home-pacel`), 36 tool calls, no skills. Not useful.
- Hermes is the real corpus (below). No opencode DB, no qwen, codex, or gemini. (The first full scan of this host walked ~100k files and was slow; later light scans were fine.)

## 3. Hermes details

Verified on `pacel-orin:~/.hermes/state.db` (422 MB, live, WAL active): the reported numbers are essentially confirmed and slightly higher because the DB keeps growing.

| Metric | Reported | Measured |
|---|---|---|
| sessions | 1,323 | 1,325 |
| messages | 32,921 | 33,108 (includes 573 `session_meta` rows) |
| skill_view loads | 252 | 254 |
| distinct skills | 68 | 68 |

Session sources: cron 548, telegram 402, auricle 271, subagent 64, cli 28, desktop 9, tui 2, simplex 1. Range 2026-05-26 to 2026-11-08. Roles: assistant 14,922, tool 13,128, user 4,485, session_meta 573.

Schema (Hermes state.db; same on all three machines, with orin lacking a few newer sessions columns):
- `sessions`: id, source, user_id, model, system_prompt_hash, parent_session_id, started_at REAL (epoch), ended_at, end_reason, message_count, tool_call_count, token counts, cwd, git_branch, title, tool_names, and more.
- `messages`: id, session_id, role (user/assistant/tool/session_meta), content, tool_call_id, **tool_calls** (JSON list of OpenAI-style `{function:{name,arguments}}` on assistant rows), **tool_name** (on role=tool rows), timestamp REAL (epoch), token_count, finish_reason, reasoning, active, compacted, message_uid, tool_call_uid.
- Other tables: system_prompts, session_model_usage, messages_fts*, plus many gateway/hosted_room tables.

Skill loads: tool name `skill_view`, with the skill in the assistant `tool_calls[].function.arguments` JSON as `name`. The `tool_name='skill_view'` count on tool rows (254) matches the tool_calls count.

Top skill_view counts (orin): google-workspace 33, manage-google-tasks 28, hermes-agent 27, job-tracker 21, gog-cli 19, vettd 10, cron-job-patterns 6, opencode 5, laptop-ssh 5, competitor-news-monitor 5. Ten skills have 5 or more loads.

Top tools on orin: terminal 6880, web_search 2916, read_file 525, execute_code 474, web_extract 342, search_files 325, patch 309, skill_view 254, write_file 226, tool_call 219, skill_manage 108.

Skill storage: `~/.hermes/skills/<category>/<skill>/SKILL.md` (orin 180 SKILL.md, pc 83, Mac 46). Bundled skills come from `.bundled_manifest`; hub installs from `.hub/lock.json`.

**Provenance finding: FOUND.**
- `~/.hermes/skills/.usage.json` is a per-skill record with a `created_by` field. Values seen on orin: `agent` 72, `learn` 5, `installed` 1, null 114. Mac: agent 1, installed 1, null 2. pc: agent 1, null 81.
- The same record holds created_at, patch_count, patch_generation, use_count, view_count, last_viewed_at, last_used_at, state, pinned and archived_at.
- Caveat from the source (`hermes-agent/tools/skill_usage.py`): `created_by` is a curator opt-in flag set by `skill_manage`, and `hermes curator adopt` can flip it, so it is not proof of authorship. Null most likely means bundled or hand-written.
- `~/.hermes/skills/.curator_ledger.jsonl` (keys id, ts, actor, action, skill, evidence, before, after) logs create/patch/write_file events by actor. The Mac copy has 31 entries (patch 26, write_file 4, create 1). It is the best audit trail for auto-created skills. Not yet read on orin or pc.
- Hermes `skill_manage` calls (108 on orin) in messages also show agent-driven creation or patching.

## 4. Usable for the project (bar: at least 100 loads and at least 10 skills with 5 or more loads each)

- **pacel-orin Hermes: PASSES.** 254 loads, 68 skills, 10 skills with at least 5 loads (exactly at the bar, and the top 5 hold 128 of 254 loads). The only machine/harness combo that qualifies. It also has `created_by` provenance and 13k tool calls with timestamps. Per-skill counts below the top 10 are thin (most 1 to 4).
- Claude Code, all machines combined (vivobook unknown): 274 + 703 + 2 = 979 session files, about 10,800 tool calls, 22 Skill-tool loads (Mac 8, pc 14, orin 0) and about 21 genuine slash-skill loads (opsx:update 8, frontend-design 5, openspec-propose 5, 3 other), for about 43 total loads. Distinct skills about 8. Fails the bar. orca-cli (17 Skill loads) is the only skill with 5 or more Skill-tool loads across machines. Much of this volume is eval or tmp automation (`-tmp`, `-private-tmp`, harness-eval), so these are not organic skill-use sessions.
- pacel-pc OpenCode: large (610 sessions, 95k parts) and it showed about 64 skill-ish rows, but skill extraction was not validated. It is a candidate second corpus to investigate; the Mac OpenCode DB has about 5 such rows.
- Hermes on Mac and pc: too small (1 and 8 loads).
- Qwen and Codex: session counts are small (50 and 2 on pc, 44 on Mac); skill usage not measured.

## 5. Problems and surprises

- pacel-vivobook: SSH timed out on the full scan, so no data. Needs a retry when it is awake.
- The initial combined scan against orin walked `~/.hermes` and was very slow; rerun without the directory walk. An early classifier hiccup caused a few retried commands. No permission-denied errors occurred.
- Surprise: the Mac's `~/.hermes` is 4.8 GB yet its `state.db` holds just 3 sessions. The pc is similar (6.1 GB, 3 sessions). Hermes weight is in source, caches and other files, not sessions.
- Surprise: Claude Code skill usage is very sparse. Most sessions are under `/tmp` (540 on pc, 218 on Mac), apparently eval or automation runs, and builtin `/loop` dominates slash commands on pc.
- Slash-command regex picked up junk (`xyz`, a regex literal) from transcripts that discuss slash commands; those were excluded from the genuine counts above.
- OpenCode has two schemas: legacy `session/message/part` (pc only) and newer `session_v2/session_message`. Skill detection there needs a proper pass.
- Hermes counts are a live snapshot, so numbers will keep drifting upward.
- Date ranges for OpenCode, Qwen and Codex were not extracted. Claude Code dates are from timestamp fields; the Hermes dates are from `sessions.started_at` epoch values.
