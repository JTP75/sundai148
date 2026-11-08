# Agents: working in this repo

Planning here uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) (spec-driven schema). The active change is `openspec/changes/behaviorgpt-skill-potency/`: start with its `proposal.md`, then `design.md` and `tasks.md`. Background docs are in `docs/` (handoffs, research); see `README.md` for the layout.

## Install OpenSpec (one time per machine)

```sh
npm install -g @fission-ai/openspec@latest   # needs Node.js ≥20; this repo was set up with 1.16.0
openspec --version
```

## Hook up your agent (only if this repo has no command/skill files for your tool yet)

The repo already has files for Claude Code, OpenCode, Qwen and Hermes (`.claude/`, `.opencode/`, `.qwen/`, `.hermes/`). For another tool:

```sh
openspec init --tools <your-tool>   # e.g. codex, cursor, gemini; `openspec init --help` lists them
```

Do not re-run `init` for tools that are already set up.

## Day-to-day

```sh
openspec list                                   # changes in flight
openspec status --change behaviorgpt-skill-potency
openspec validate behaviorgpt-skill-potency --strict
```

Workflow: propose (`/opsx:propose`) → revise artifacts (`/opsx:update`) → implement (`/opsx:apply`, ticking `- [x]` in `tasks.md`) → archive (`/opsx:archive`). Edit the planning artifacts and re-validate before writing code; don't change scope only in code.
