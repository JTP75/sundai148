"""Probe HF agent-trace repos for Claude Code skill usage without downloading them.

Usage: python3 -I collect/probe.py SHORTLIST_JSON OUT_JSONL [--per-repo 3] [--rps 1]
SHORTLIST_JSON: list of [date, repo_id, ...] (newest first). OUT_JSONL is appended; repos already in it are skipped.
Per repo: one tree call (file oids kept for dedupe), then the first 2 MB of up to N sampled .jsonl files.
Prints/records counts and names only, never message text.
"""
import json, os, random, sys, time, urllib.error, urllib.request

TOK = open(os.path.expanduser("~/.cache/huggingface/token")).read().strip()
RANGE = 2_000_000


class Pacer:
    def __init__(self, rps): self.gap, self.t = 1.0 / rps, 0.0

    def wait(self):
        d = self.t + self.gap - time.time()
        if d > 0: time.sleep(d)
        self.t = time.time()


def get(url, pacer, raw=False, rng=False):
    h = {"Authorization": f"Bearer {TOK}"}
    if rng: h["Range"] = f"bytes=0-{RANGE - 1}"
    for _ in range(8):
        pacer.wait()
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=90).read()
            return b if raw else json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(min(int(e.headers.get("Retry-After") or 30), 120)); continue
            raise
    raise RuntimeError("429 persisted")


def scan(text, st, names):
    fmt = None
    for line in text.splitlines():
        try: j = json.loads(line)
        except Exception: continue
        if not isinstance(j, dict): continue
        if "sessionId" in j and j.get("type") in ("user", "assistant"): fmt = "claude_code"
        elif j.get("type") in ("session_meta", "response_item", "turn_context"): fmt = fmt or "codex"
        ts = j.get("timestamp")
        if isinstance(ts, str) and ts[:4].isdigit(): st["max_ts"] = max(st.get("max_ts", ""), ts[:10])
        if "attributionSkill" in j: st["attrib"] = st.get("attrib", 0) + 1
        a = j.get("attachment")
        if isinstance(a, dict) and a.get("type") == "skill_listing": st["listing"] = st.get("listing", 0) + 1
        m = j.get("message")
        if isinstance(m, dict) and isinstance(m.get("content"), list):
            for it in m["content"]:
                if isinstance(it, dict) and it.get("type") == "tool_use":
                    st["tool_use"] = st.get("tool_use", 0) + 1
                    if it.get("name") == "Skill":
                        st["skill"] = st.get("skill", 0) + 1
                        names[str((it.get("input") or {}).get("skill"))] = 1
    return fmt


def main():
    short, out = sys.argv[1], sys.argv[2]
    per = int(sys.argv[sys.argv.index("--per-repo") + 1]) if "--per-repo" in sys.argv else 3
    rps = float(sys.argv[sys.argv.index("--rps") + 1]) if "--rps" in sys.argv else 1.0
    done = set()
    if os.path.exists(out):
        done = {json.loads(l)["repo"] for l in open(out) if l.strip()}
    pacer, rnd = Pacer(rps), random.Random(0)
    for row in json.load(open(short)):
        repo = row[1]
        if repo in done: continue
        rec = {"repo": repo, "last_modified": row[0]}
        try:
            tree = get(f"https://huggingface.co/api/datasets/{repo}/tree/main?recursive=1", pacer)
            files = [x for x in tree if x.get("type") == "file" and x["path"].endswith(".jsonl")]
            rec["n_jsonl"] = len(files)
            rec["bytes"] = sum(x.get("size", 0) for x in files)
            rec["oids"] = [(x.get("lfs") or {}).get("oid") or x.get("oid") for x in files]
            st, names, fmts, wskill = {}, {}, {}, 0
            for f in rnd.sample(files, min(per, len(files))):
                before = st.get("skill", 0)
                b = get(f"https://huggingface.co/datasets/{repo}/resolve/main/{f['path']}", pacer, raw=True, rng=True)
                fm = scan(b.decode("utf8", "ignore"), st, names)
                fmts[str(fm)] = fmts.get(str(fm), 0) + 1
                wskill += st.get("skill", 0) > before
            rec.update(st); rec["formats"] = fmts; rec["sampled"] = sum(fmts.values())
            rec["files_with_skill"] = wskill; rec["skill_names"] = sorted(names)[:20]
        except Exception as e:
            rec["error"] = str(e)[:80]
        with open(out, "a") as fh: fh.write(json.dumps(rec) + "\n")
        print(repo, {k: rec.get(k) for k in ("n_jsonl", "formats", "skill", "files_with_skill", "max_ts", "error")}, flush=True)


if __name__ == "__main__":
    main()
