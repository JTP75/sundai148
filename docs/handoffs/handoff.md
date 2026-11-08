# Sundai Hack 148 — handoff (as of 2026-11-08, ~10:50)

Theme: *Behavioral Models: Predict the next action.* MIT, 10:00–22:00. Sponsor: Unbox AI (Rickard Brüel-Gabrielsson), BehaviorGPT-v4 — 12.5B params, 150B human actions (retail/engagement/payments), zero-shot ranking of unseen catalogs.

## Starting idea (from `~/hack-148/skill-usefulness-handoff.md`)
Predict, from static SKILL.md features alone, whether an agent will FOLLOW a skill or load it and ignore it. Corpus verified live on pacel-orin: `~/.hermes/state.db`, 1,323 sessions, 32,921 messages, 252 `skill_view` loads across 68 skills. Original plan: hand-engineered features + LightGBM, feature importances as the demo.

Verdict reached: **that framing is off-theme.** It never touches the sponsor's stack, and n=252 of tabular features is a weak final slide.

## Reframe (the one worth pitching)
Turn it into a behavioral-model question over *agent action sequences*:

- **Catalog** = command signatures mined from `tool_calls` (name = `terminal: git rebase`, categories = tool family, keywords = flags). Alternative: the 68 skills as catalog items.
- **History** = a session's tool calls, mapped by meaning: grep/`search_files` → `Search`, `skill_view`/`read_file` → `View`, `write_file`/command run → `Order`. Unbox's docs explicitly allow this ("map your users' actions by meaning"; the AIC art-wall demo does it with paintings).
- **Label** = behaviorGPT's own surprise. After a load event, is the skill's prescribed command in the model's top-k? In top-k = followed; far outside = the anomaly case, i.e. *loaded and ignored*. Unbox already ships an unlabeled anomaly detector built from these rankings, so the mechanic is theirs, not invented.

## Two results for the final slide
1. Temporal-split top-k next-command accuracy vs. a session n-gram baseline → "does human behavior transfer to agent behavior?"
2. Per-skill potency = mean rank of the prescribed command after each load, over the 252 loads → ranked list of the most-loaded-but-inert skills. That's the Vettd story ("which skills actually change behavior?").

Supporting, not central: static SKILL.md features (trigger specificity, step count, code-block density) as an ablation on top of the model scores.

## Guardrails
- Split by time, never random; CV by skill, never by event (33 google-workspace loads will fake accuracy).
- Command-matching labels are noisy — keep the model small; report precision@k, not raw accuracy.
- Say "agreement with prescribed action," not "skill quality."
- Catalog needs all 15 parquet columns. `image_url` can be null (text-only embedding) — avoid unreliable image hosts, or the embed job fails if none of the first 500 URLs is fetchable.
- Novelty is thin on "we pointed it at agents" alone (Unbox already has *BehaviorGPT at Work*); the differentiator is skills-as-interventions.

## Next actions
1. Extractor: `state.db` → command catalog parquet + labeled event CSV (~150 lines Python, no LLM) on pacel-orin; scp to the Mac.
2. Upload catalog (`client.embed(..., wait=True)`), run `client.complete(...)` over the 252 load positions.
3. Baseline + potency ranking; 3 numbers and one chart by 20:00.

Needs an Unbox AI API key (email sign-in at portal.unboxai.com; key also arrives by email) — not yet obtained. Client: `pip install behaviorgpt`, Python ≥3.11.
