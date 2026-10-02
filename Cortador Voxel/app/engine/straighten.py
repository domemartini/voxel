"""Straight cut: replace a wavy seam between two pieces by the best-fit PLANE through it.
Around that seam, every bit of the two pieces is given to one side of the plane (the parts "compensate"
each other) and the cut goes exactly along the plane, through the triangles (see refine.py).
usage: python straighten.py <workdir> '{"loops": [0, 3] | "all"}'
needs v.npy t.npy seg.npy marks.json loops.json loop_<n>.npy  (field.npy optional)
writes seg.npy field.npy (+ seg_prev/field_prev for undo) and the new seams"""
import sys, os, json, shutil, numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refine import hard_field, refine
from seams import write_loops

wd = sys.argv[1]
arg = sys.argv[2] if len(sys.argv) > 2 else '{"loops": "all"}'
cfg = json.load(open(arg)) if arg.endswith(".json") and os.path.exists(arg) else json.loads(arg)
v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); seg = np.load(f"{wd}/seg.npy").astype(np.int8)
G = json.load(open(f"{wd}/marks.json", encoding="utf-8"))["groups"]; ng = len(G); nV = len(v)
loops = json.load(open(f"{wd}/loops.json"))
F = None
if os.path.exists(f"{wd}/field.npy"):
    F = np.load(f"{wd}/field.npy").astype(np.float64)
    if F.shape != (nV, ng): F = None
if F is None: F = hard_field(v, t, seg, ng)
paint = np.load(f"{wd}/paint.npy") if os.path.exists(f"{wd}/paint.npy") else None
ALL = cfg.get("loops", "all") == "all"
sel = range(len(loops)) if ALL else [int(i) for i in cfg["loops"]]
skipped = []; touched = np.zeros(nV, bool)
# vertex adjacency (to keep the change to the neighbourhood that is connected to the seam)
e = np.r_[t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]
Adj = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(nV, nV)).tocsr(); Adj = Adj + Adj.T
tree = cKDTree(v)
vl = F.argmax(1)
done = 0
for i in sel:
    l = loops[i]; a, b = int(l["a"]), int(l["b"])
    f = f"{wd}/{l['file']}"
    if not os.path.exists(f): continue
    pts = np.load(f)
    if len(pts) < 6: continue
    c = pts.mean(0); _, sv, vt = np.linalg.svd(pts - c); n = vt[2]
    flat = sv[2] / max(sv[0], 1e-9)
    R = float(np.linalg.norm(pts - c, axis=1).max()) * 1.3 + 2.0
    dev = np.abs((pts - c) @ n)
    rad = float(np.linalg.norm(pts - c, axis=1).max())
    limit = 0.18 if ALL else 0.35                          # "all" is strict; a seam picked by hand may be more wavy
    if dev.max() > max(1.0, limit * rad) or dev.max() > (4.0 if ALL else 8.0):
        skipped.append(f"{G[a]['name']} | {G[b]['name']}")
        print(f"skipped {G[a]['name']} | {G[b]['name']}: too curved for a flat cut (wave {dev.max():.1f} mm, seam radius {rad:.1f} mm)")
        continue
    Dg = float(2.0 * dev.max() + 1.5)                      # band along the surface: just wide enough to hold the wave
    near = np.zeros(nV, bool); near[tree.query_ball_point(c, R)] = True
    cand = near & ((vl == a) | (vl == b))
    ids = np.where(cand)[0]
    if not len(ids): continue
    rm = np.full(nV, -1); rm[ids] = np.arange(len(ids))
    sub = Adj[ids][:, ids].tocoo()
    ln = np.linalg.norm(v[ids[sub.row]] - v[ids[sub.col]], axis=1)
    Gd = sp.csr_matrix((ln, (sub.row, sub.col)), shape=(len(ids), len(ids)))
    seed = np.unique(tree.query(pts)[1]); seed = seed[cand[seed]]
    if not len(seed): continue
    dist = dijkstra(Gd, directed=False, indices=rm[seed], min_only=True, limit=Dg)
    mask = np.zeros(nV, bool); mask[ids[np.isfinite(dist)]] = True
    if paint is not None and len(paint) == len(t):             # hand painting stays as it is
        pv = np.zeros(nV, bool); pv[t[paint >= 0].ravel()] = True; mask &= ~pv
    d = (v[mask] - c) @ n
    side_a = np.sign(np.mean(((v[mask & (vl == a)] - c) @ n))) if (mask & (vl == a)).any() else 1.0
    side_a = side_a or 1.0
    W = max(Dg, 1.0)
    fa = np.clip(0.5 + side_a * d / (2 * W), 0, 1)
    F[mask] = 0; F[mask, a] = fa; F[mask, b] = 1 - fa; touched |= mask
    done += 1
    print(f"straight cut {G[a]['name']} | {G[b]['name']}: plane through {len(pts)} seam points (warp {100 * flat:.0f}%), {int(mask.sum())} vertices")
json.dump(dict(done=done, skipped=skipped), open(f"{wd}/straight_report.json", "w", encoding="utf-8"), ensure_ascii=False)
if not done:
    print("nothing to straighten"); sys.exit(0)
for fn in ("seg", "field"):
    if os.path.exists(f"{wd}/{fn}.npy"): shutil.copyfile(f"{wd}/{fn}.npy", f"{wd}/{fn}_prev.npy")
if not os.path.exists(f"{wd}/field.npy") and os.path.exists(f"{wd}/field_prev.npy"): os.remove(f"{wd}/field_prev.npy")
new = F[t].mean(1).argmax(1).astype(np.int8)
if paint is not None and len(paint) == len(t): new[paint >= 0] = paint[paint >= 0]
# clean-up: tiny islands (a bit of one piece stranded inside the other) are handed over
ef = np.r_[t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]; ef.sort(1); fid = np.tile(np.arange(len(t)), 3)
key = ef[:, 0].astype(np.int64) * nV + ef[:, 1]; o = np.argsort(key, kind="stable"); key, fid = key[o], fid[o]
same = key[1:] == key[:-1]; f1, f2 = fid[:-1][same], fid[1:][same]
P_ = v[t]; tarea = np.linalg.norm(np.cross(P_[:, 1] - P_[:, 0], P_[:, 2] - P_[:, 0]), axis=1) / 2
for _ in range(3):
    ok_ = new[f1] == new[f2]
    Ga = sp.coo_matrix((np.ones(ok_.sum()), (f1[ok_], f2[ok_])), shape=(len(t), len(t)))
    _, comp = connected_components(Ga, directed=False)
    carea = np.bincount(comp, weights=tarea)
    lab_area = np.bincount(new, weights=tarea, minlength=ng)
    near_change = np.zeros(comp.max() + 1, bool); near_change[comp[touched[t].any(1)]] = True
    small = (carea[comp] < 0.02 * lab_area[new]) & near_change[comp]
    if not small.any(): break
    # give each small island the label of its neighbours across its border
    bd = (new[f1] != new[f2])
    cand_ = np.r_[np.c_[f1[bd], new[f2[bd]]], np.c_[f2[bd], new[f1[bd]]]]
    cand_ = cand_[small[cand_[:, 0]]]
    if not len(cand_): break
    nb = {}
    for fi, lb in cand_: nb.setdefault(comp[fi], []).append(lb)
    for cid, lbs in nb.items():
        tri = np.where(comp == cid)[0]; new[tri] = np.bincount(lbs).argmax()
        vv = np.unique(t[tri]); F[vv] = 0; F[vv, new[tri[0]]] = 1
np.save(f"{wd}/seg.npy", new); np.save(f"{wd}/field.npy", F.astype(np.float32))
v2, t2, s2 = refine(v, t, F)
L = write_loops(wd, v2, t2, s2, [g["name"] for g in G])
for l in L: print("LOOP", l["a"], "->", l["b"], "size", l["size"])
print("straightened", done, "seam(s)")
