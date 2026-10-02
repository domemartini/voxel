"""Seam (contact loop) extraction shared by mincut_multi.py and smooth_seg.py.
write_loops(wd, v, t, seg, names) -> writes loops.json + loop_N.npy (ordered cycle points) + seg_summary.json"""
import os, json, numpy as np, scipy.sparse as sp
from scipy.sparse.csgraph import connected_components


def face_adjacency(t, nV):
    he = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]); hf = np.tile(np.arange(len(t)), 3)
    key = he[:, 0].astype(np.int64) * nV + he[:, 1]; rev = he[:, 1].astype(np.int64) * nV + he[:, 0]
    o = np.argsort(key); ks = key[o]
    pos = np.searchsorted(ks, rev); pos = np.minimum(pos, len(ks) - 1)
    of = np.where(ks[pos] == rev, hf[o][pos], -1)
    return he, hf, of


def loops_from_seg(v, t, seg, he=None, hf=None, of=None):
    nV = len(v)
    if he is None: he, hf, of = face_adjacency(t, nV)
    P = v[t]; fc = P.mean(1)
    ok = of >= 0
    loops = []
    for a in np.unique(seg):
        for b in np.unique(seg):
            if b <= a: continue
            m = ok & (seg[hf] == a) & (seg[np.maximum(of, 0)] == b)
            if not m.any(): continue
            E = he[m]
            lab = connected_components(sp.coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(nV, nV)), directed=False)[1]
            for L in np.unique(lab[E[:, 0]]):
                e = E[lab[E[:, 0]] == L]
                if len(e) < 6: continue
                nxt = {}
                for i, j in e: nxt.setdefault(int(i), []).append(int(j))
                simple = all(len(x) == 1 for x in nxt.values())
                if simple:
                    start = int(e[0, 0]); cyc = [start]; cur = start
                    for _ in range(len(e)):
                        cur = nxt[cur][0]
                        if cur == start: break
                        cyc.append(cur)
                    cyc = np.array(cyc)
                else:
                    cyc = np.unique(e)
                p = v[cyc]; c = p.mean(0); _, _, vt = np.linalg.svd(p - c); n = vt[2]
                near = np.linalg.norm(fc - c, axis=1) < max(4, np.ptp(p, 0).max() * 0.6)
                A_ = fc[near & (seg == a)]; B_ = fc[near & (seg == b)]
                if len(A_) and len(B_) and (B_.mean(0) - A_.mean(0)) @ n < 0: n = -n
                seglen = np.linalg.norm(np.diff(np.r_[p, p[:1]], axis=0), axis=1).sum() if simple else 0.0
                loops.append(dict(a=int(a), b=int(b), cycle=cyc, points=p, center=c.round(2).tolist(), size=round(float(np.ptp(p, 0).max()), 2),
                                  normal=n.round(4).tolist(), nverts=int(len(cyc)), simple=bool(simple), length=round(float(seglen), 1)))
    return loops


def write_loops(wd, v, t, seg, names, seconds=None, he=None, hf=None, of=None):
    for fl in [f for f in os.listdir(wd) if f.startswith("loop_") and f.endswith(".npy")]: os.remove(f"{wd}/{fl}")
    loops = loops_from_seg(v, t, seg, he, hf, of); out = []
    for k, l in enumerate(loops):
        fname = f"loop_{k}.npy"; np.save(f"{wd}/{fname}", l["points"])
        out.append({kk: vv for kk, vv in l.items() if kk not in ("cycle", "points")} | {"file": fname})
    json.dump(out, open(f"{wd}/loops.json", "w"), indent=1)
    P = v[t]; summ = []
    for k, nm in enumerate(names):
        m = seg == k; q = P[m].reshape(-1, 3) if m.any() else np.zeros((1, 3))
        summ.append(dict(name=nm, tris=int(m.sum()), bbox=[q.min(0).round(1).tolist(), q.max(0).round(1).tolist()]))
    prev = json.load(open(f"{wd}/seg_summary.json")) if os.path.exists(f"{wd}/seg_summary.json") else {}
    json.dump(dict(groups=summ, loops=len(out), seconds=seconds if seconds is not None else prev.get("seconds", 0)), open(f"{wd}/seg_summary.json", "w"), indent=1)
    return out
