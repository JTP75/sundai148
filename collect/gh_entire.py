"""Find public GitHub repos with Entire.io checkpoint branches and probe them for Claude Code skill usage.

Usage: python3 -I collect/gh_entire.py OUT_JSONL [--days 14] [--sample 2]
Phase A: enumerate repos from commits carrying the "Entire-Checkpoint" trailer, one search slice per day, newest first.
Phase B: for each new repo, read the tree of branch entire/checkpoints/v1, then sample full.jsonl transcripts
and count Skill tool calls. Records counts and names only. Uses the gh CLI (its auth and rate limits).
"""
import base64, datetime as D, json, os, random, subprocess, sys, time


def gh(*args):
    for _ in range(5):
        p = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
        if p.returncode == 0: return json.loads(p.stdout)
        if "rate limit" in p.stderr.lower() or "secondary" in p.stderr.lower():
            time.sleep(60); continue
        return None
    return None


def repos_for_day(day):
    found, page = {}, 1
    while page <= 10:
        r = gh("-X", "GET", "search/commits", "-f", f'q="Entire-Checkpoint" committer-date:{day}',
               "-f", "per_page=100", "-f", f"page={page}", "-f", "sort=committer-date")
        time.sleep(2.2)  # search API: 30 req/min
        if not r or not r.get("items"): break
        for it in r["items"]:
            found[it["repository"]["full_name"]] = day
        if len(r["items"]) < 100: break
        page += 1
    return found


def probe(repo, k, rnd):
    rec = {"repo": repo}
    br = gh(f"repos/{repo}/branches/entire/checkpoints/v1")
    if not br:
        rec["branch"] = False; return rec
    tree = gh(f"repos/{repo}/git/trees/{br['commit']['commit']['tree']['sha']}?recursive=1") or {}
    blobs = [t for t in tree.get("tree", []) if t["type"] == "blob"]
    tx = [t for t in blobs if t["path"].endswith("full.jsonl")]
    rec.update(branch=True, n_transcripts=len(tx), bytes=sum(t.get("size", 0) for t in tx),
               truncated=tree.get("truncated"))
    skill, names, cc, maxts = 0, set(), 0, ""
    for t in rnd.sample(tx, min(k, len(tx))):
        if t.get("size", 0) > 30_000_000: continue
        b = gh(f"repos/{repo}/git/blobs/{t['sha']}")
        if not b: continue
        text = base64.b64decode(b["content"]).decode("utf8", "ignore")
        for line in text.splitlines():
            try: j = json.loads(line)
            except Exception: continue
            if not isinstance(j, dict): continue
            if "sessionId" in j: cc = 1
            ts = j.get("timestamp")
            if isinstance(ts, str): maxts = max(maxts, ts[:10])
            m = j.get("message")
            if isinstance(m, dict) and isinstance(m.get("content"), list):
                for it in m["content"]:
                    if isinstance(it, dict) and it.get("type") == "tool_use" and it.get("name") == "Skill":
                        skill += 1; names.add(str((it.get("input") or {}).get("skill")))
    rec.update(claude_code=bool(cc), sampled_skill=skill, skill_names=sorted(names)[:20], max_ts=maxts)
    return rec


def main():
    out = sys.argv[1]
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 14
    k = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else 2
    done = {json.loads(l)["repo"] for l in open(out)} if os.path.exists(out) else set()
    rnd, today = random.Random(0), D.date.today()
    for d in range(days):
        day = (today - D.timedelta(days=d)).isoformat()
        repos = repos_for_day(day)
        print(f"# {day}: {len(repos)} repos", flush=True)
        for repo in repos:
            if repo in done: continue
            rec = probe(repo, k, rnd); rec["first_seen_day"] = day; done.add(repo)
            with open(out, "a") as fh: fh.write(json.dumps(rec) + "\n")
            print(repo, {x: rec.get(x) for x in ("n_transcripts", "claude_code", "sampled_skill", "max_ts")}, flush=True)


if __name__ == "__main__":
    main()
