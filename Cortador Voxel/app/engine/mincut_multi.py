"""Multi-part surface segmentation for the interactive cutter (and for scripted use).
Groups are processed in order: group 0 is cut away from all later groups, then group 1 from the
rest of the still-unassigned surface, ...; the LAST group gets everything left (usually the base /
torso). Each step is a max-flow/min-cut where cutting along concave creases is cheap, so cuts
follow the natural junctions. Cut planes (point, normal, radius) make edges crossing them almost
free, so the cut snaps to the plane there (use for arm/leg joints or any straight cut).
usage: python mincut_multi.py <workdir> [marks.json]
marks.json: {"groups":[{"name":..,"color":"#hex","points":[[x,y,z],...]},...],
             "planes":[{"point":[x,y,z],"normal":[nx,ny,nz],"radius":r},...],
             "strokes":[{"points":[[x,y,z],...],"radius":r},...],   # painted cut lines (brush)
             "seed_r":2.0, "base_below_z": null}
writes: seg.npy (int8 group per triangle), loops.json + loop_N.npy (contacts between groups),
        seg_summary.json"""
import sys, os, json, time, numpy as np, scipy.sparse as sp
from scipy.sparse.csgraph import maximum_flow, breadth_first_order, connected_components

wd = sys.argv[1]; mk = json.load(open(sys.argv[2] if len(sys.argv) > 2 else f"{wd}/marks.json"))
t0 = time.time()
v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); P = v[t]; nV = len(v)
fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); fn /= np.linalg.norm(fn, axis=1)[:, None] + 1e-12; fc = P.mean(1)
e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]); e.sort(1); fid = np.tile(np.arange(len(t)), 3)
key = e[:, 0].astype(np.int64) * nV + e[:, 1]; o = np.argsort(key, kind="stable"); key, fid, e = key[o], fid[o], e[o]
first = np.r_[True, key[1:] != key[:-1]]; E = e[first]; F1 = fid[first]
F2 = np.full(len(E), -1); idx = np.where(~first)[0]; F2[np.searchsorted(np.where(first)[0], idx, side="right") - 1] = fid[idx]
L = np.linalg.norm(v[E[:, 0]] - v[E[:, 1]], axis=1)
w = np.ones(len(E)); ok = F2 >= 0
ang = np.degrees(np.arccos(np.clip((fn[F1[ok]] * fn[F2[ok]]).sum(1), -1, 1)))
concave = ((fc[F2[ok]] - fc[F1[ok]]) * fn[F1[ok]]).sum(1) > 0
f = np.clip((ang - 15) / 35, 0, 1); w[ok] = np.where(concave, 1 - 0.96 * f, 1.0)
for pl in mk.get("planes", []):
    p0 = np.array(pl["point"], float); n = np.array(pl["normal"], float); n /= np.linalg.norm(n); r = float(pl.get("radius", 30))
    s0 = (v[E[:, 0]] - p0) @ n; s1 = (v[E[:, 1]] - p0) @ n
    mid = (v[E[:, 0]] + v[E[:, 1]]) / 2; rad = np.linalg.norm((mid - p0) - np.outer((mid - p0) @ n, n), axis=1)
    cross = (np.sign(s0) != np.sign(s1)) & (rad < r)
    w[cross] *= 0.005
    # edges near the plane but not crossing it get a bit more expensive so the cut stays on the plane
    near = (~cross) & (np.minimum(abs(s0), abs(s1)) < 3) & (rad < r); w[near] *= 3
    print(f"plane at {p0.round(1).tolist()}: {int(cross.sum())} crossing edges")
strokes = [s for s in mk.get("strokes", []) if s.get("points")]
if strokes:
    from scipy.spatial import cKDTree
    pts = np.vstack([np.array(s["points"], float) for s in strokes])
    rad = np.concatenate([np.full(len(s["points"]), float(s.get("radius", 1.5))) for s in strokes])
    mid = (v[E[:, 0]] + v[E[:, 1]]) / 2
    d, j = cKDTree(pts).query(mid, distance_upper_bound=float(rad.max()))
    hitm = np.isfinite(d); hitm[hitm] &= d[hitm] < rad[j[hitm]]
    w[hitm] *= 0.003   # painted cut line: cutting here is almost free
    print(f"painted cut: {len(strokes)} stroke(s), {len(pts)} points, {int(hitm.sum())} edges")
cap = np.maximum(1, np.round(L * w * 1000)).astype(np.int32)

G = mk["groups"]; ng = len(G); r = mk.get("seed_r", 2.0)
seeds = []
for g in G:
    m = np.zeros(nV, bool)
    for p in g["points"]: m |= ((v - np.array(p)) ** 2).sum(1) < r * r
    seeds.append(m)
if mk.get("base_below_z") is not None:
    seeds[-1] |= v[:, 2] < mk["base_below_z"]
paint = np.load(f"{wd}/paint.npy") if os.path.exists(f"{wd}/paint.npy") else None
if paint is not None and len(paint) == len(t):
    pv = np.full(nV, -1, np.int16)
    for k in range(ng): pv[t[paint == k].ravel()] = k
    for k in range(ng):
        for j in range(ng):
            if j != k: seeds[j] &= pv != k          # a painted vertex belongs only to its painted piece
        seeds[k] |= pv == k
    print(f"painted by hand: {int((paint >= 0).sum())} triangles kept")
else:
    paint = None
vlab = np.full(nV, -1, np.int16)
for k in range(ng - 1):
    free = vlab < 0
    src = seeds[k] & free; snk = np.zeros(nV, bool)
    for j in range(k + 1, ng): snk |= seeds[j]
    snk &= free & ~src
    if not src.any():
        print(f"group {k} ({G[k]['name']}): no seed on free surface, skipped"); continue
    ids = np.where(free)[0]; remap = np.full(nV, -1); remap[ids] = np.arange(len(ids)); n = len(ids)
    em = free[E[:, 0]] & free[E[:, 1]]
    a, b, c = remap[E[em, 0]], remap[E[em, 1]], cap[em]
    S, T = n, n + 1; BIG = np.int32(2 ** 30)
    si, ti = remap[np.where(src)[0]], remap[np.where(snk)[0]]
    rows = np.r_[a, b, np.full(len(si), S), ti]; cols = np.r_[b, a, si, np.full(len(ti), T)]
    caps = np.r_[c, c, np.full(len(si), BIG), np.full(len(ti), BIG)].astype(np.int32)
    Gm = sp.csr_matrix((caps, (rows, cols)), shape=(n + 2, n + 2)); Gm.sum_duplicates()
    res = maximum_flow(Gm, S, T, method="dinic")
    R = Gm - res.flow; R.data[R.data < 0] = 0; R.eliminate_zeros(); R.data[:] = 1
    reach = breadth_first_order(R, S, directed=True, return_predecessors=False)
    reach = reach[reach < n]
    vlab[ids[reach]] = k
    print(f"group {k} ({G[k]['name']}): cut {res.flow_value/1000:.1f} (weighted mm), {len(reach)} verts  {time.time()-t0:.0f}s")
vlab[vlab < 0] = ng - 1
tl = vlab[t]
seg = np.where(tl[:, 0] == tl[:, 1], tl[:, 0], np.where(tl[:, 1] == tl[:, 2], tl[:, 1], tl[:, 0])).astype(np.int8)
if paint is not None: seg[paint >= 0] = paint[paint >= 0]
# keep only the seeded connected region of each group; islands go to the group around them
np.save(f"{wd}/seg.npy", seg)
# contact loops between groups (ordered cycles) + summary
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seams import write_loops
from smooth_seg import run_smooth
for f_ in ("field.npy", "field_prev.npy", "seg_prev.npy"):
    if os.path.exists(f"{wd}/{f_}"): os.remove(f"{wd}/{f_}")
auto = float(mk.get("auto_smooth", 1.0))
if os.path.exists(f"{wd}/seg_summary.json"): os.remove(f"{wd}/seg_summary.json")
if auto > 0:   # light automatic smoothing so seams are cut through triangles, not along them
    run_smooth(wd, v, t, seg, G, None, auto, None, r, backup=False)
if auto > 0 and os.path.exists(f"{wd}/seg_summary.json"):
    s_ = json.load(open(f"{wd}/seg_summary.json")); s_["seconds"] = round(time.time() - t0); json.dump(s_, open(f"{wd}/seg_summary.json", "w"), indent=1)
    loops = json.load(open(f"{wd}/loops.json"))
else:   # sem suavização, ou nenhuma costura na superfície (ex.: peças por cor que são cascas separadas)
    loops = write_loops(wd, v, t, seg, [g["name"] for g in G], seconds=round(time.time() - t0))
for s_ in json.load(open(f"{wd}/seg_summary.json"))["groups"]: print("GROUP", s_)
for l in loops: print("LOOP", l["a"], "->", l["b"], "size", l["size"], "at", l["center"])
