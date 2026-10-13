"""
Minimal Monte Carlo simulator for the illustrative schedules.

For each schedule, we apply a default Triangular distribution per task
(notes give hints; otherwise +/- 25% around the mean), run 20000 iterations,
and report P50/P80/P90 + per-task criticality index.

Pure numpy - no engine dependencies. Used to verify expected behaviour
of each illustrative case.
"""

import numpy as np
from collections import defaultdict, Counter
from illustrative_schedules import L1a, L1b, L2, L3, L4


RNG = np.random.default_rng(42)
N = 20000


def parse_triangular(notes: str, mean: float):
    """Extract Triangular(a, b, c) from notes if present, else default."""
    if "Triangular(" in notes:
        inside = notes.split("Triangular(", 1)[1].split(")", 1)[0]
        parts = [float(x.strip()) for x in inside.split(",")]
        if len(parts) == 3:
            return tuple(parts)
    # default: symmetric +/- 25% around mean
    return (mean * 0.8, mean, mean * 1.25)


def topo_order(sched):
    succ = defaultdict(list)
    for t in sched.tasks:
        for p in t.predecessors:
            succ[p].append(t.uid)
    indeg = {t.uid: len(t.predecessors) for t in sched.tasks}
    order = []
    stack = [uid for uid, d in indeg.items() if d == 0]
    while stack:
        uid = stack.pop(0)
        order.append(uid)
        for s in succ[uid]:
            indeg[s] -= 1
            if indeg[s] == 0:
                stack.append(s)
    return order, succ


def simulate(sched, n=N):
    tasks = {t.uid: t for t in sched.tasks}
    order, succ = topo_order(sched)

    # Sample N durations per task
    samples = {}
    for t in sched.tasks:
        if t.duration_days == 0:
            samples[t.uid] = np.zeros(n)
        else:
            a, b, c = parse_triangular(t.notes, t.duration_days)
            samples[t.uid] = RNG.triangular(a, b, c, n)

    # Forward pass per iteration (vectorised)
    ef = {}
    for uid in order:
        t = tasks[uid]
        if t.predecessors:
            preds_ef = np.maximum.reduce([ef[p] for p in t.predecessors])
        else:
            preds_ef = np.zeros(n)
        ef[uid] = preds_ef + samples[uid]

    # Project finish per iteration = max EF across all tasks (handles multiple ends)
    finish = np.maximum.reduce(list(ef.values()))

    # Criticality index: per iteration, walk back from project finish.
    # An activity is critical if its EF == its successors' ES (i.e. no slack).
    # Simple approach: backward pass per iteration to compute LF, mark TF==0.
    # Vectorised backward pass:
    lf = {uid: finish.copy() for uid in tasks}
    for uid in reversed(order):
        if succ[uid]:
            lf[uid] = np.minimum.reduce([lf[s] - samples[s] for s in succ[uid]])
    tf = {uid: (lf[uid] - ef[uid]) for uid in tasks}
    critical_count = {uid: np.sum(tf[uid] < 0.01) for uid in tasks}

    # Percentiles
    p50 = float(np.percentile(finish, 50))
    p80 = float(np.percentile(finish, 80))
    p90 = float(np.percentile(finish, 90))
    mean = float(np.mean(finish))

    return {
        "finish": finish, "p50": p50, "p80": p80, "p90": p90, "mean": mean,
        "criticality": {uid: critical_count[uid] / n for uid in tasks},
        "tasks": tasks, "order": order,
    }


def report(sched, det_finish):
    r = simulate(sched)
    print(f"\n{'='*70}")
    print(f"  {sched.name}")
    print(f"  Deterministic finish: {det_finish:g} days")
    print(f"  MC mean:  {r['mean']:.2f}")
    print(f"  MC P50:   {r['p50']:.2f}")
    print(f"  MC P80:   {r['p80']:.2f}")
    print(f"  MC P90:   {r['p90']:.2f}")
    print(f"  Bias (mean - deterministic): +{r['mean']-det_finish:.2f} days")
    print(f"\n  Criticality index per task:")
    for uid in r["order"]:
        t = r["tasks"][uid]
        ci = r["criticality"][uid] * 100
        bar = "#" * int(ci / 5)
        print(f"    {uid:>4}  {t.name[:42]:42s}  {ci:5.1f}%  {bar}")


if __name__ == "__main__":
    cases = [(L1a, 20), (L1b, 26), (L2, 30), (L3, 82), (L4, 40)]
    for sched, det in cases:
        report(sched, det)
