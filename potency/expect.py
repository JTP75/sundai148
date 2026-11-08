"""Analysis: D3 expectation model -> out/expected.csv, out/expect_eval.json.

P(command c runs within the next n steps | context without the skill). One model per corpus, per target
command: L2 logistic regression over the previous ``k`` signatures, session source, task key, the target's
train base rate and the session position; rare targets (few positives) fall back to a bigram estimate with
base-rate backoff. The vocabulary, base rates and models are built from train sessions only, and rows whose
context window contains a load of a skill prescribing c are excluded from training for c.

The evaluation compares the model with a popularity-only baseline (each command's train base rate) on the
same test windows and the same candidate universe: AUC, Brier, a 10-bin calibration curve, and next-command
hit-rate@1/5/10 on first occurrences of a command in a session, overall and per train-frequency decile.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from potency import evidence, io, schema

MIN_POSITIVES = 10
SMOOTH_ALPHA = 2.0
MAX_FIT_ROWS = 20000
N_BINS = 10
HIT_KS = (1, 5, 10)
LOAD_PREFIX = "load: "
# Real corpora have thousands of one-off signatures. Fit per-command models only for the commands that
# matter: every prescribed command (observable or alternative of any rule) plus the most frequent train
# commands. The next-command evaluation ranks this same candidate set for the model and the baseline.
MAX_FREQUENT_TARGETS = 300
# Feature pruning keeps the solver fast and stops one-off values from being memorized: previous signatures
# outside the target set become "<other>", and task keys seen in fewer than MIN_TASK_SESSIONS train sessions
# become "<rare>" (real task keys are per-session prompt hashes, mostly unique).
MIN_TASK_SESSIONS = 5
# Window-level AUC/Brier/calibration pool (test window x target) pairs; on real corpora that is hundreds of
# millions of pairs. Evaluate on at most this many test windows, chosen by a deterministic even stride.
MAX_EVAL_WINDOWS = 20000


def _scale_horizon(p_n: float, n: int, window: int) -> float:
    """P(hit within n) from P(hit within window), assuming a roughly constant per-step hazard."""
    if n <= 0:
        return 0.0
    if n >= window:
        return float(p_n)
    return 1.0 - (1.0 - max(0.0, min(1.0, p_n))) ** (n / window)


def _combine(probs) -> float:
    """P(any of several signatures within the window), independence approximation."""
    miss = 1.0
    for p in probs:
        miss *= 1.0 - max(0.0, min(1.0, p))
    return 1.0 - miss


def _feature_dict(prevs, source, task_key, pos) -> dict:
    d = {f"prev{j}": sig for j, sig in enumerate(prevs)}
    d["source"] = source or "<none>"
    d["task"] = task_key or "<none>"
    d["pos"] = float(pos)
    return d


def _with_base(X, base: float):
    col = sp.csr_matrix(np.full((X.shape[0], 1), float(base)))
    return sp.hstack([X, col], format="csr")


class ExpectationModel:
    """Fits one corpus's no-skill next-command model and evaluates it against popularity."""

    def __init__(self, corpus_dir, window: int = schema.WINDOW_N, rule_map=None):
        self.corpus_dir = Path(corpus_dir)
        self.corpus = evidence.corpus_name(self.corpus_dir)
        self.window = window
        self.k = schema.CONTEXT_K
        self.sessions = {s["session_id"]: s for s in io.read_table(self.corpus_dir, "sessions")}
        self.steps = evidence.steps_by_session(self.corpus_dir)
        self.loads = io.read_table(self.corpus_dir, "loads")
        rules_by_key = evidence.rules_by_key(self.corpus_dir)
        if rule_map:
            rules_by_key = evidence.apply_rule_map(rules_by_key, rule_map, self.corpus)
        self.rules_by_key = rules_by_key
        self._t0 = time.monotonic()
        self._load_events()
        self._windows()
        self._progress(f"windows: {len(self.train_w)} train, {len(self.test_w)} test")
        self._encode()
        self._progress(f"targets: {len(self.vocab)} of {self.full_vocab_size} train signatures")
        self._fit_targets()
        self._progress("fit done")

    def _progress(self, msg: str) -> None:
        """Progress to stderr (never to output files), so long real-data runs are observable."""
        print(f"expect[{self.corpus}] {time.monotonic() - self._t0:7.1f}s {msg}", file=sys.stderr, flush=True)

    # ---------------------------------------------------------------- setup
    def _load_events(self) -> None:
        psets = evidence.prescribed_sets(self.corpus_dir)
        self.load_events: dict[str, list[tuple[int, frozenset]]] = {}
        self.preload_sets: dict[str, frozenset] = {}
        for ld in self.loads:
            pset = psets.get((ld["skill"], ld["version_id"]))
            if pset is None:
                pset = psets.get((ld["skill"], "*"), frozenset())
            if ld["trigger"] == "preloaded":
                self.preload_sets[ld["session_id"]] = self.preload_sets.get(
                    ld["session_id"], frozenset()
                ) | pset
            self.load_events.setdefault(ld["session_id"], []).append((ld["step"], pset))

    def exposed(self, sid: str, t: int, c: str) -> bool:
        """True when a load of a skill prescribing c sits in [t-N+1, t+N] (or was preloaded)."""
        if c in self.preload_sets.get(sid, frozenset()):
            return True
        for step, pset in self.load_events.get(sid, ()):
            if c in pset and t - self.window < step <= t + self.window:
                return True
        return False

    def _session_meta(self, sid: str):
        s = self.sessions.get(sid) or {}
        return s.get("source"), s.get("task_key"), s.get("split", "train")

    def _windows(self) -> None:
        self.train_w: list[dict] = []
        self.test_w: list[dict] = []
        for sid in sorted(self.steps):
            steps = self.steps[sid]
            last = steps[-1]["step"]
            source, task_key, split = self._session_meta(sid)
            for i, st in enumerate(steps):
                if st["kind"] == "load":
                    continue
                t = st["step"]
                if t + self.window > last:
                    continue
                prevs = []
                for x in reversed(steps[:i]):
                    if x["kind"] != "load":
                        prevs.append(x["signature"])
                        if len(prevs) == self.k:
                            break
                win = [
                    x for x in steps
                    if t < x["step"] <= t + self.window and x["kind"] != "load"
                ]
                rec = {
                    "sid": sid, "t": t, "last": last,
                    "prevs": prevs,
                    "sig_set": frozenset(x["signature"] for x in win),
                    "next_sig": steps[i + 1]["signature"] if i + 1 < len(steps) else None,
                    "source": source, "task_key": task_key,
                    "pos": round(t / last, 6) if last else 0.0,
                }
                (self.train_w if split == "train" else self.test_w).append(rec)

    def _encode(self) -> None:
        self.vocab = sorted({
            st["signature"]
            for sid, steps in self.steps.items()
            if self._session_meta(sid)[2] == "train"
            for st in steps
            if st["kind"] != "load" and not st["signature"].startswith(LOAD_PREFIX)
        })
        freq: dict[str, int] = {}
        for sid, steps in self.steps.items():
            if self._session_meta(sid)[2] != "train":
                continue
            for st in steps:
                if st["kind"] != "load" and not st["signature"].startswith(LOAD_PREFIX):
                    freq[st["signature"]] = freq.get(st["signature"], 0) + 1
        self.full_vocab_size = len(self.vocab)
        prescribed = {
            sig for rules in self.rules_by_key.values() for r in rules
            for sig in list(r.get("observable") or ()) + list(r.get("alternatives") or ())
        }
        frequent = sorted(self.vocab, key=lambda c: (-freq.get(c, 0), c))[:MAX_FREQUENT_TARGETS]
        self.vocab = sorted((set(frequent) | prescribed) & set(self.vocab))
        self.vocab_index = {c: j for j, c in enumerate(self.vocab)}
        self.prescribed_any = frozenset(
            c for evs in self.load_events.values() for _step, pset in evs for c in pset
        ) | frozenset(c for pset in self.preload_sets.values() for c in pset)
        self._fast = {}
        task_sessions: dict[str, int] = {}
        for sid in self.steps:
            _src, tk, split = self._session_meta(sid)
            if split == "train" and tk:
                task_sessions[tk] = task_sessions.get(tk, 0) + 1
        self.keep_tasks = frozenset(k for k, n in task_sessions.items() if n >= MIN_TASK_SESSIONS)
        self.vocab_set = frozenset(self.vocab)
        self.vec = DictVectorizer(sparse=True)
        self.X_train = self.vec.fit_transform([
            self._feat(w["prevs"], w["source"], w["task_key"], w["pos"]) for w in self.train_w
        ])
        self.X_test = self.vec.transform([
            self._feat(w["prevs"], w["source"], w["task_key"], w["pos"]) for w in self.test_w
        ])

    def _feat(self, prevs, source, task_key, pos) -> dict:
        prevs = [p if p in self.vocab_set else "<other>" for p in prevs]
        task = task_key if task_key in self.keep_tasks else ("<rare>" if task_key else None)
        return _feature_dict(prevs, source, task, pos)

    # ---------------------------------------------------------------- targets
    def _rows_index(self, rows) -> dict:
        """Per-row-list caches: inverted indexes for labels and integer codes for prev0."""
        key = id(rows)
        hit = self._fast.get(key)
        if hit is None or hit["rows"] is not rows:
            win_idx: dict[str, list[int]] = {}
            next_idx: dict[str, list[int]] = {}
            prev_codes: dict[str, int] = {}
            prev0 = np.empty(len(rows), dtype=np.int64)
            for i, w in enumerate(rows):
                for sig in w.get("sig_set", ()):
                    win_idx.setdefault(sig, []).append(i)
                nxt = w.get("next_sig")
                if nxt is not None:
                    next_idx.setdefault(nxt, []).append(i)
                p0 = w["prevs"][0] if w["prevs"] else "<none>"
                prev0[i] = prev_codes.setdefault(p0, len(prev_codes))
            self._fast[key] = {"win": win_idx, "step": next_idx, "prev0": prev0, "prev_codes": prev_codes,
                               "n": len(rows), "rows": rows}
        return self._fast[key]

    def _valid_mask(self, rows, c: str) -> np.ndarray:
        if c not in self.prescribed_any:
            return np.ones(len(rows), dtype=bool)
        return np.array([not self.exposed(w["sid"], w["t"], c) for w in rows], dtype=bool)

    def _labels(self, rows, kind: str, c: str) -> np.ndarray:
        if kind in ("win", "step") and rows and ("sig_set" in rows[0] or kind == "step"):
            fx = self._rows_index(rows)
            y = np.zeros(fx["n"])
            idx = fx[kind].get(c)
            if idx:
                y[idx] = 1.0
            return y
        if kind == "win":
            return np.array([1.0 if c in w["sig_set"] else 0.0 for w in rows])
        return np.array([1.0 if w["next_sig"] == c else 0.0 for w in rows])

    def _fit_one(self, c: str, rows, X, kind: str) -> dict:
        valid = self._valid_mask(rows, c)
        y_all = self._labels(rows, kind, c)
        idx = np.flatnonzero(valid)
        y = y_all[idx]
        n_pos = int(y.sum())
        n_neg = int(len(y) - n_pos)
        base = (n_pos / len(y)) if len(y) else 0.0
        fx = self._rows_index(rows)
        codes = fx["prev0"][idx]
        n_codes = len(fx["prev_codes"])
        hits_by = np.bincount(codes, weights=y_all[idx], minlength=n_codes)
        n_by = np.bincount(codes, minlength=n_codes)
        names = sorted(fx["prev_codes"], key=fx["prev_codes"].get)
        by_prev = {names[j]: [int(hits_by[j]), int(n_by[j])] for j in np.flatnonzero(n_by)}
        tm = {"base": float(base), "kind": "fallback", "model": None,
              "by_prev": {k: tuple(v) for k, v in by_prev.items()}}
        if n_pos >= MIN_POSITIVES and n_neg >= MIN_POSITIVES:
            fit_idx = idx
            if len(idx) > MAX_FIT_ROWS:
                pos_idx = idx[y_all[idx] == 1]
                neg_idx = idx[y_all[idx] == 0]
                keep = max(MAX_FIT_ROWS - len(pos_idx), 1)
                if len(neg_idx) > keep:
                    take = np.linspace(0, len(neg_idx) - 1, keep).astype(int)
                    neg_idx = neg_idx[take]
                fit_idx = np.sort(np.concatenate([pos_idx, neg_idx]))
            Xf = _with_base(X[fit_idx], base)
            clf = LogisticRegression(
                C=1.0, max_iter=2000, random_state=schema.SEED, solver="lbfgs"
            )
            clf.fit(Xf, y_all[fit_idx])
            tm.update(kind="logistic", model=clf)
        return tm

    def _fit_targets(self) -> None:
        self.models = {"win": {}, "step": {}}
        for n, c in enumerate(self.vocab, 1):
            if n % 25 == 0 or n == len(self.vocab):
                self._progress(f"fit {n}/{len(self.vocab)}")
            for kind, rows, X in (("win", self.train_w, self.X_train),
                                  ("step", self.train_w, self.X_train)):
                self.models[kind][c] = self._fit_one(c, rows, X, kind)
        self.base = {c: self.models["win"][c]["base"] for c in self.vocab}

    def _predict(self, kind: str, c: str, X, rows) -> np.ndarray:
        tm = self.models[kind].get(c)
        if tm is None:
            return np.zeros(X.shape[0])
        if tm["kind"] == "logistic":
            return tm["model"].predict_proba(_with_base(X, tm["base"]))[:, 1]
        base, alpha = tm["base"], SMOOTH_ALPHA
        fx = self._rows_index(rows)
        names = sorted(fx["prev_codes"], key=fx["prev_codes"].get)
        table = np.full(len(names), base)
        for j, p in enumerate(names):
            hits, n = tm["by_prev"].get(p, (0, 0))
            if n:
                table[j] = (hits + alpha * base) / (n + alpha)
        return table[fx["prev0"]] if len(names) else np.full(len(rows), base)

    # ---------------------------------------------------------------- expected adherence
    def _evidence_rows(self, rule_map) -> list[dict]:
        path = self.corpus_dir / "out" / "evidence.csv"
        if path.exists():
            rows = io.read_csv(path)
            for r in rows:
                r["window_start"] = int(r["window_start"])
                r["window_end"] = int(r["window_end"])
            return rows
        return evidence.compute_evidence(self.corpus_dir, window=self.window, rule_map=rule_map)

    def _load_contexts(self):
        """Feature rows for the context at each scorable load, keyed by load_id."""
        by_id = {}
        for ld in self.loads:
            sid, step = ld["session_id"], ld["step"]
            steps = self.steps.get(sid)
            if not steps:
                continue
            prevs = []
            for x in reversed([s for s in steps if s["step"] < step]):
                if x["kind"] != "load":
                    prevs.append(x["signature"])
                    if len(prevs) == self.k:
                        break
            last = steps[-1]["step"]
            source, task_key, _split = self._session_meta(sid)
            by_id[ld["load_id"]] = {
                "prevs": prevs, "source": source, "task_key": task_key,
                "pos": round(step / last, 6) if last else 0.0,
            }
        return by_id

    def expected_rows(self, rule_map=None) -> list[dict]:
        ev_rows = self._evidence_rows(rule_map)
        contexts = self._load_contexts()
        load_ids = sorted(contexts)
        X_load = self.vec.transform([
            self._feat(contexts[i]["prevs"], contexts[i]["source"], contexts[i]["task_key"],
                          contexts[i]["pos"])
            for i in load_ids
        ])
        load_rows = [contexts[i] for i in load_ids]
        pos_of = {lid: n for n, lid in enumerate(load_ids)}
        cache: dict[str, np.ndarray] = {}
        loads_by_id = {ld["load_id"]: ld for ld in self.loads}
        targets = {
            (r["skill"], r["version_id"], r["rule_id"]): r
            for rules in self.rules_by_key.values()
            for r in rules
        }
        out: list[dict] = []
        for ev in ev_rows:
            key = (ev["skill"], ev["version_id"], ev["rule_id"])
            rule = targets.get(key)
            if rule is None:
                out.append({"corpus": self.corpus, "load_id": ev["load_id"],
                            "rule_id": ev["rule_id"], "p_hat": 0.0})
                continue
            sigs = sorted(set(rule.get("observable") or ()) | set(rule.get("alternatives") or ()))
            load = loads_by_id.get(ev["load_id"])
            n = (ev["window_end"] - load["step"]) if load else self.window
            probs = []
            for sig in sigs:
                if sig not in cache:
                    cache[sig] = self._predict("win", sig, X_load, load_rows)
                probs.append(_scale_horizon(cache[sig][pos_of[ev["load_id"]]], n, self.window))
            out.append({
                "corpus": self.corpus, "load_id": ev["load_id"], "rule_id": ev["rule_id"],
                "p_hat": _combine(probs),
            })
        out.sort(key=lambda r: (r["load_id"], r["rule_id"]))
        return out

    # ---------------------------------------------------------------- evaluation
    def _eval_sample(self):
        n = len(self.test_w)
        if n <= MAX_EVAL_WINDOWS:
            return self.test_w, self.X_test
        take = np.linspace(0, n - 1, MAX_EVAL_WINDOWS).astype(int)
        return [self.test_w[i] for i in take], self.X_test[take]

    def _window_eval(self) -> dict:
        yv, pm, pb = [], [], []
        rows, X = self._eval_sample()
        self._progress(f"window eval on {len(rows)} of {len(self.test_w)} test windows")
        for n, c in enumerate(self.vocab, 1):
            if not rows:
                break
            if n % 100 == 0:
                self._progress(f"window eval {n}/{len(self.vocab)}")
            p = self._predict("win", c, X, rows)
            y = self._labels(rows, "win", c)
            mask = self._valid_mask(rows, c)
            yv.append(y[mask])
            pm.append(p[mask])
            pb.append(np.full(int(mask.sum()), self.base[c]))
        if not yv:
            return {"rows": 0, "sessions": 0}
        self._progress("window eval: computing AUC/Brier/calibration")
        y = np.concatenate(yv)
        p_model = np.concatenate(pm)
        p_base = np.concatenate(pb)
        return {
            "rows": int(len(y)),
            "windows_evaluated": len(rows),
            "windows_total": len(self.test_w),
            "sessions": len({w["sid"] for w in rows}),
            "positives": int(y.sum()),
            "model": {"auc": _auc(y, p_model), "brier": float(np.mean((p_model - y) ** 2))},
            "popularity_baseline": {"auc": _auc(y, p_base),
                                    "brier": float(np.mean((p_base - y) ** 2))},
            "calibration": _calibration(y, p_model, N_BINS),
        }

    def _scored_steps(self) -> list[dict]:
        scored = []
        self._progress("hit-rate: collecting first-occurrence test steps")
        for n_sid, sid in enumerate(sorted(self.steps), 1):
            if n_sid % 500 == 0:
                self._progress(f"hit-rate: scanned {n_sid}/{len(self.steps)} sessions, {len(scored)} steps")
            steps = self.steps[sid]
            source, task_key, split = self._session_meta(sid)
            if split != "test":
                continue
            seen: set[str] = set()
            last = steps[-1]["step"]
            for i, st in enumerate(steps):
                sig = st["signature"]
                first = st["kind"] != "load" and sig not in seen
                if st["kind"] != "load":
                    seen.add(sig)
                if not first or i + 1 >= len(steps):
                    continue
                nxt = steps[i + 1]
                if nxt["kind"] == "load":
                    continue
                prevs = []
                for x in reversed(steps[:i]):
                    if x["kind"] != "load":
                        prevs.append(x["signature"])
                        if len(prevs) == self.k:
                            break
                scored.append({
                    "sid": sid, "t": st["step"], "prevs": prevs, "next_sig": nxt["signature"],
                    "seen": frozenset(seen - {sig}),
                    "source": source, "task_key": task_key,
                    "pos": round(st["step"] / last, 6) if last else 0.0,
                })
        return scored

    def _hit_rate_eval(self) -> dict:
        scored = self._scored_steps()
        self._progress(f"hit-rate eval on {len(scored)} first-occurrence test steps")
        if not scored or not self.vocab:
            return {"steps": 0, "sessions": 0, "oov_share": 0.0}
        X = self.vec.transform([
            self._feat(s["prevs"], s["source"], s["task_key"], s["pos"]) for s in scored
        ])
        self._progress("hit-rate: predicting step probabilities")
        model_p = np.column_stack([self._predict("step", c, X, scored) for c in self.vocab])
        self._progress("hit-rate: ranking")
        base_p = np.array([self.base[c] for c in self.vocab])
        freq = self._train_freq()
        rank_of = {c: i for i, c in enumerate(sorted(self.vocab, key=lambda s: (freq[s], s)))}
        hits = {k: {"model": 0, "popularity_baseline": 0} for k in HIT_KS}
        by_decile: dict[int, dict] = {}
        oov = 0
        for i, s in enumerate(scored):
            if i and i % 10000 == 0:
                self._progress(f"hit-rate: ranked {i}/{len(scored)} steps")
            truth = s["next_sig"]
            cand = [j for j, c in enumerate(self.vocab) if c not in s["seen"]]
            in_vocab = truth in self.vocab
            decile = _decile(rank_of[truth], len(self.vocab)) if in_vocab else None
            if decile is not None:
                cell = by_decile.setdefault(
                    decile, {"decile": decile, "steps": 0,
                             "model": {k: 0 for k in HIT_KS},
                             "popularity_baseline": {k: 0 for k in HIT_KS}})
                cell["steps"] += 1
            if not in_vocab:
                oov += 1
                continue
            truth_j = self.vocab_index[truth]
            by_model = sorted(cand, key=lambda j: (-model_p[i, j], self.vocab[j]))
            by_base = sorted(cand, key=lambda j: (-base_p[j], self.vocab[j]))
            for k in HIT_KS:
                if truth_j in by_model[:k]:
                    hits[k]["model"] += 1
                    if decile is not None:
                        by_decile[decile]["model"][k] += 1
                if truth_j in by_base[:k]:
                    hits[k]["popularity_baseline"] += 1
                    if decile is not None:
                        by_decile[decile]["popularity_baseline"][k] += 1
        n = len(scored)
        block = {
            "steps": n,
            "sessions": len({s["sid"] for s in scored}),
            "oov_steps": oov,
            "oov_share": oov / n,
            "candidates": len(self.vocab),
            "full_train_vocabulary": self.full_vocab_size,
            "model": {str(k): hits[k]["model"] / n for k in HIT_KS},
            "popularity_baseline": {str(k): hits[k]["popularity_baseline"] / n for k in HIT_KS},
            "by_decile": [
                {
                    "decile": d,
                    "steps": cell["steps"],
                    "model": {str(k): cell["model"][k] / cell["steps"] for k in HIT_KS},
                    "popularity_baseline": {
                        str(k): cell["popularity_baseline"][k] / cell["steps"] for k in HIT_KS
                    },
                }
                for d, cell in sorted(by_decile.items())
            ],
        }
        bottom = [c for d, c in by_decile.items() if d < N_BINS // 2]
        if bottom:
            steps = sum(c["steps"] for c in bottom)
            block["bottom_half"] = {
                "steps": steps,
                "model": {str(k): sum(c["model"][k] for c in bottom) / steps for k in HIT_KS},
                "popularity_baseline": {
                    str(k): sum(c["popularity_baseline"][k] for c in bottom) / steps
                    for k in HIT_KS
                },
            }
        return block

    def _train_freq(self) -> dict[str, int]:
        freq: dict[str, int] = {c: 0 for c in self.vocab}
        for sid, steps in self.steps.items():
            if self._session_meta(sid)[2] != "train":
                continue
            for st in steps:
                if st["signature"] in freq:
                    freq[st["signature"]] += 1
        return freq

    def eval_block(self) -> dict:
        logistic = sum(1 for c in self.vocab if self.models["win"][c]["kind"] == "logistic")
        return {
            "corpus": self.corpus,
            "window_n": self.window,
            "context_k": self.k,
            "train_sessions": len({w["sid"] for w in self.train_w}),
            "test_sessions": len({w["sid"] for w in self.test_w}),
            "train_windows": len(self.train_w),
            "test_windows": len(self.test_w),
            "vocabulary": len(self.vocab),
            "targets": {
                "vocabulary": len(self.vocab),
                "logistic_window_models": logistic,
                "fallback_window_models": len(self.vocab) - logistic,
            },
            "window": self._window_eval(),
            "next_command": self._hit_rate_eval(),
            "notes": [
                "trained on train-split windows with no load of a skill prescribing the target; "
                "windows that contain such a load are excluded too (leakage guard)",
                "honest counterfactual only: test base rates, vocabulary and hyperparameters use train only",
                "never seen without a load => base rate 0 => p_hat 0",
            ],
        }


def _auc(y: np.ndarray, p: np.ndarray):
    """ROC AUC via the Mann-Whitney rank formula with midranks for ties (equals sklearn's roc_auc_score,
    but one sort instead of a threshold sweep: seconds instead of minutes on ~10^7 pairs)."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n_pos = int((y > 0.5).sum())
    n_neg = len(y) - n_pos
    if len(y) == 0 or n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(p, kind="mergesort")
    ps = p[order]
    ranks = np.empty(len(p), dtype=float)
    _, first, counts = np.unique(ps, return_index=True, return_counts=True)
    mid = first + (counts - 1) / 2.0 + 1.0
    ranks[order] = np.repeat(mid, counts)
    rank_sum = ranks[y > 0.5].sum()
    return float((rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def _calibration(y: np.ndarray, p: np.ndarray, bins: int) -> list[dict]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        sel = (p >= lo) & (p < hi) if b < bins - 1 else (p >= lo) & (p <= hi)
        n = int(sel.sum())
        out.append({
            "bin": b,
            "lower": float(lo),
            "upper": float(hi),
            "count": n,
            "predicted": float(p[sel].mean()) if n else None,
            "observed": float(y[sel].mean()) if n else None,
        })
    return out


def _decile(rank: int, size: int) -> int:
    if size <= 1:
        return 0
    return min(N_BINS - 1, int(rank * N_BINS / size))


def fit_and_predict(corpus_dir, window: int = schema.WINDOW_N, rule_map=None):
    """Return (expected_rows, eval_block) for one corpus directory."""
    model = ExpectationModel(corpus_dir, window=window, rule_map=rule_map)
    rows = model.expected_rows(rule_map)
    model._progress(f"expected rows: {len(rows)}")
    block = model.eval_block()
    model._progress("evaluation done")
    return rows, block


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m potency.expect",
        description="Analysis: D3 expectation model -> out/expected.csv, out/expect_eval.json.",
    )
    p.add_argument("--corpus", default=None, help="corpus (default: every corpus in the data dir)")
    p.add_argument("--data", default=None, help="data dir")
    p.add_argument("--window", type=int, default=schema.WINDOW_N, help="window N")
    p.add_argument("--rule-map", default=None, help="approved rule map JSON (used when evidence is absent)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    rule_map = evidence.read_rule_map(args.rule_map) if args.rule_map else None
    data_dir = io.resolve_data_dir(args.data)
    for corpus_dir in io.corpus_dirs(data_dir, args.corpus):
        rows, block = fit_and_predict(corpus_dir, window=args.window, rule_map=rule_map)
        out_dir = corpus_dir / "out"
        io.write_output_csv(out_dir / "expected.csv", rows)
        io.write_json(out_dir / "expect_eval.json", {block["corpus"]: block})
        print(f"{corpus_dir.name}: {len(rows)} p_hat rows -> {out_dir / 'expected.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
