# Handoff → pacel-pc session (Sundai Hack 148, 2026-11-08)

## Project in one paragraph
Theme: "Behavioral Models: predict the next action." Sponsor: Unbox AI's BehaviorGPT-v4, which ranks the next action given a history of Search/View/Order events, zero-shot on any catalog. Our idea: treat an agent's tool calls as a behavior history (command run → `View(command signature)`, search query → `Search(query)`, skill load → `View(ExternalItem("skill: <name>"))`). Then measure **skill potency**: how much a skill load raises BehaviorGPT's probability of the command the SKILL.md prescribes, compared with the same history without the load, and whether that command actually followed. The output is a ranking of "loaded but inert" skills. The angle we're pitching is Hermes auto-creating lots of skills that bloat, and this tool shows which ones to prune. Wording rule: say "agreement with prescribed action," never "skill quality." Data goal: one harness for the hack, with a harness-neutral intermediate format so other harnesses can plug in later.

## Already inventoried (read-only, from the Mac). Don't redo these
| Machine | Harness | Sessions | Skill loads | Verdict |
|---|---|---|---|---|
| pacel-orin | **Hermes** `~/.hermes/state.db` | 1,325 (2026-05-26 → 11-08) | **254 `skill_view`, 68 skills, 10 skills with ≥5 loads** | **Only corpus that passes** (bar: ≥100 loads, ≥10 skills with ≥5) |
| Mac + pc + orin | Claude Code | 979 files, ~10.8k tool calls | ~43 total (orca-cli dominates), ~8 skills | Fails. Mostly `/tmp` eval/automation runs |
| pacel-pc | Hermes | 3 | 8 | too small |
| pacel-pc | OpenCode | 610 `session` + 742 `session_v2`, 22k msgs, 3.0 GB | ~64 "skill-ish" rows, **unverified** | candidate second corpus |
| pacel-pc | Qwen / Codex | 50 jsonl / 2 sessions | not measured | probably small |
| pacel-vivobook | all | — | — | ssh timed out; not scanned |

Hermes facts (from orin):
- `messages.tool_calls` is a JSON list of `{function:{name,arguments}}` on assistant rows; `messages.tool_name` is set on role=tool rows; `messages.timestamp` and `sessions.started_at` are epoch REALs.
- A skill load is the `skill_view` tool with `arguments.name`.
- Skill files live at `~/.hermes/skills/<category>/<skill>/SKILL.md` (180 on orin).
- **Provenance:** `~/.hermes/skills/.usage.json` has `created_by` per skill (orin: agent 72, learn 5, installed 1, null 114). It's an opt-in curator flag, so it's not proof of authorship. `~/.hermes/skills/.curator_ledger.jsonl` (actor/action/skill) is the better audit trail; it hasn't been read on orin yet.

## Your tasks (read-only; never modify, move, or copy raw logs off-machine; print only counts/names/timestamps, never message text, since logs may contain secrets)
1. **Validate OpenCode on this PC** (`~/.local/share/opencode/`, both schemas: legacy `session/message/part` and `session_v2/session_message`). Find how a skill load is represented, then count real skill loads, distinct skills, and skills with ≥5 loads. Report the tool-call count and date range, and say whether it passes the bar. Open SQLite only as `file:<path>?mode=ro`.
2. **Quick Qwen (`~/.qwen/projects`) and Codex (`~/.codex/sessions`) counts:** sessions, date range, skill loads if the format has them. Keep this short.
3. **pacel-orin provenance**, over `ssh -o BatchMode=yes -o ConnectTimeout=10 pacel@pacel-orin`: summarize `~/.hermes/skills/.curator_ledger.jsonl` (count by actor × action). Cross-tab the 68 loaded skills (and the 10 with ≥5 loads) against `created_by` from `.usage.json`. The question is whether there are enough agent-created skills among the loaded ones for an "auto-created vs hand-written" comparison. Avoid walking all of `~/.hermes`, which was very slow last time.
4. **pacel-vivobook:** try once with the same ssh flags. If it's reachable, check Claude Code, Hermes, and OpenCode counts the same way. If it isn't, note it and move on.

## Deliverable
Write `~/log-inventory-pc.md` with a table per task, a one-line verdict for each corpus against the bar, and the provenance cross-tab. Reply with a ≤20-line summary I can paste back to the Mac session.
