"""'Sponge': smooth seams so cuts become straight/rounded curves (cut goes THROUGH triangles, see refine.py).
usage: python smooth_seg.py <workdir> '<json>'
json: {"strokes":[{"points":[[x,y,z],...],"radius":r}]  (omit = every seam),
       "strength": 2.0 (mm blur), "band": 4.0 (mm around seams when smoothing all)}
State: seg.npy (labels on the original triangles, for display), field.npy (soft labels per vertex,
used by separate_seg.py to cut through triangles). Undo: seg_prev.npy / field_prev.npy."""
import sys, os, json, time, shutil, numpy as np
from scipy.spatial import cKDTree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seams import face_adjacency, write_loops
from refine import hard_field, blur_field, refine


def run_smooth(wd, v, t, seg, groups, strokes=None, strength=2.0, band=None, seed_r=2.0, backup=True, log=print):
    t0 = time.time(); ng = len(groups); nV = len(v)
    band = band if band is not None else max(3.0, 2 * strength)
    F = None
    if os.path.exists(f"{wd}/field.npy"):
        F = np.load(f"{wd}/field.npy").astype(np.float64)
        if F.shape != (nV, ng): F = None
    if F is None: F = hard_field(v, t, seg, ng)
    fc = v[t].mean(1); tree_f = cKDTree(fc)
    he, hf, of = face_adjacency(t, nV)
    bm = (of >= 0) & (seg[hf] != seg[np.maximum(of, 0)])
    seam_pts = (v[he[bm, 0]] + v[he[bm, 1]]) / 2
    if not len(seam_pts): log("no seams"); return seg
    if strokes:
        reg = np.zeros(len(t), bool)
        for s in strokes:
            for p in s["points"]: reg[tree_f.query_ball_point(p, float(s.get("radius", 3.0)))] = True
        d, _ = cKDTree(seam_pts).query(fc[reg], distance_upper_bound=band + strength)
        idx = np.where(reg)[0]; reg[idx[~np.isfinite(d)]] = False
    else:
        d, _ = cKDTree(seam_pts).query(fc, distance_upper_bound=band); reg = np.isfinite(d)
    lock = np.zeros(len(t), bool)
    for g in groups:
        for p in g["points"]: lock[tree_f.query_ball_point(p, seed_r)] = True
    paint = np.load(f"{wd}/paint.npy") if os.path.exists(f"{wd}/paint.npy") else None
    if paint is not None and len(paint) == len(t):
        lock |= paint >= 0
        for k in range(ng):
            vv = np.unique(t[paint == k]); F[vv] = 0; F[vv, k] = 1
    else:
        paint = None
    log(f"sponge: {int((reg & ~lock).sum())} triangles, strength {strength} mm")
    F = blur_field(v, t, F, reg, strength, lock)
    new = F[t].mean(1).argmax(1).astype(np.int8)
    if paint is not None: new[paint >= 0] = paint[paint >= 0]
    if backup:
        if os.path.exists(f"{wd}/seg.npy"): shutil.copyfile(f"{wd}/seg.npy", f"{wd}/seg_prev.npy")
        if os.path.exists(f"{wd}/field.npy"): shutil.copyfile(f"{wd}/field.npy", f"{wd}/field_prev.npy")
        elif os.path.exists(f"{wd}/field_prev.npy"): os.remove(f"{wd}/field_prev.npy")
    np.save(f"{wd}/seg.npy", new); np.save(f"{wd}/field.npy", F.astype(np.float32))
    v2, t2, s2 = refine(v, t, F)
    loops = write_loops(wd, v2, t2, s2, [g["name"] for g in groups])
    for l in loops: log(f"LOOP {l['a']} -> {l['b']} size {l['size']} length {l['length']}")
    log(f"smoothed: {int((new != seg).sum())} triangles relabelled, seams re-cut through triangles ({time.time()-t0:.0f}s)")
    return new


def undo(wd):
    if not os.path.exists(f"{wd}/seg_prev.npy"): print("nothing to undo"); return
    shutil.copyfile(f"{wd}/seg_prev.npy", f"{wd}/seg.npy"); os.remove(f"{wd}/seg_prev.npy")
    if os.path.exists(f"{wd}/field_prev.npy"): shutil.copyfile(f"{wd}/field_prev.npy", f"{wd}/field.npy"); os.remove(f"{wd}/field_prev.npy")
    elif os.path.exists(f"{wd}/field.npy"): os.remove(f"{wd}/field.npy")
    v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); seg = np.load(f"{wd}/seg.npy").astype(np.int8)
    names = [g["name"] for g in json.load(open(f"{wd}/marks.json"))["groups"]]
    if os.path.exists(f"{wd}/field.npy"):
        v, t, seg = refine(v, t, np.load(f"{wd}/field.npy").astype(np.float64))
    write_loops(wd, v, t, seg, names); print("undo done")


if __name__ == "__main__":
    wd = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == "--undo": undo(wd); sys.exit(0)
    arg = sys.argv[2] if len(sys.argv) > 2 else "{}"
    cfg = json.load(open(arg)) if arg.endswith(".json") and os.path.exists(arg) else json.loads(arg)
    v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); seg = np.load(f"{wd}/seg.npy").astype(np.int8)
    marks = json.load(open(f"{wd}/marks.json"))
    run_smooth(wd, v, t, seg, marks["groups"], cfg.get("strokes"), float(cfg.get("strength", 2.0)), cfg.get("band"),
               float(marks.get("seed_r", 2.0)))
