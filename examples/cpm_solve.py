"""
Pure-Python CPM forward/backward pass on the illustrative schedules.

Working days only (no calendar). Produces deterministic ES/EF/LS/LF/TF
and identifies the critical path(s). Used to verify expected behaviour
and to populate the methodology note.
"""

from collections import defaultdict
from illustrative_schedules import L1a, L1b, L2, L3, L4, L5


def cpm(sched):
    tasks = {t.uid: t for t in sched.tasks}
    succ = defaultdict(list)
    for t in sched.tasks:
        for p in t.predecessors:
            succ[p].append(t.uid)

    # Topological order
    indeg = {uid: len(t.predecessors) for uid, t in tasks.items()}
    order = []
    stack = [uid for uid, d in indeg.items() if d == 0]
    while stack:
        uid = stack.pop(0)
        order.append(uid)
        for s in succ[uid]:
            indeg[s] -= 1
            if indeg[s] == 0:
                stack.append(s)

    # Forward
    es = {}
    ef = {}
    for uid in order:
        t = tasks[uid]
        es[uid] = max((ef[p] for p in t.predecessors), default=0)
        ef[uid] = es[uid] + t.duration_days

    project_finish = max(ef.values())

    # Backward
    lf = {uid: project_finish for uid in tasks}
    ls = {}
    for uid in reversed(order):
        t = tasks[uid]
        if succ[uid]:
            lf[uid] = min(ls[s] for s in succ[uid])
        ls[uid] = lf[uid] - t.duration_days

    tf = {uid: ls[uid] - es[uid] for uid in tasks}
    cp = [uid for uid in order if tf[uid] == 0]
    return {
        "es": es, "ef": ef, "ls": ls, "lf": lf, "tf": tf,
        "finish": project_finish, "critical": cp, "tasks": tasks, "order": order,
    }


def report(sched):
    r = cpm(sched)
    print(f"\n{'='*70}")
    print(f"  {sched.name}")
    print(f"  Deterministic finish: {r['finish']:g} working days")
    print(f"{'='*70}")
    print(f"  {'UID':>4}  {'Name':40s}  {'Dur':>5}  {'ES':>4}  {'EF':>4}  {'TF':>4}  CP")
    for uid in r["order"]:
        t = r["tasks"][uid]
        cp_mark = "***" if uid in r["critical"] else ""
        print(f"  {uid:>4}  {t.name[:40]:40s}  {t.duration_days:>5g}  "
              f"{r['es'][uid]:>4g}  {r['ef'][uid]:>4g}  {r['tf'][uid]:>4g}  {cp_mark}")


if __name__ == "__main__":
    for s in [L1a, L1b, L2, L3, L4, L5]:
        report(s)
