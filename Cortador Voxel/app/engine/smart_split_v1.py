"""Smart splitter: analyse the model and suggest how to cut it into printable pieces.
1. voxelize the light view mesh (winding-number fill, robust to overlapping shells)
2. base = wide slab at the bottom (area profile drops sharply above it)
3. figure = watershed of the thickness map (distance transform) -> natural blobs joined by necks
4. merge blobs whose junction is not a real neck, is too small to hold a pin, or that are tiny
5. seed points for every piece (well inside it) -> the normal min-cut does the precise seam
usage: python smart_split.py <workdir> '{"level": "medio", "bed": 256}'
writes smart.json (pieces with name/color/points/stats) and smart_view.npy (label per view triangle)"""
import sys, os, json, time, numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage.segmentation import watershed
from skimage.morphology import h_maxima

t0 = time.time()
wd = sys.argv[1]
cfg = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
LEVEL, VOLF, MAXP = {"poucas": (0.45, 0.08, 4), "medio": (0.6, 0.03, 7), "muitas": (0.74, 0.012, 12)}[cfg.get("level", "medio")]
BED = float(cfg.get("bed", 256))
LEVEL = float(cfg.get("ratio", LEVEL)); VOLF = float(cfg.get("volf", VOLF)); MAXP = int(cfg.get("maxp", MAXP)); HMIN = cfg.get("h")
v = np.load(f"{wd}/view_v.npy").astype(np.float64); t = np.load(f"{wd}/view_t.npy").astype(np.int64)
P = v[t]; fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
size = v.max(0) - v.min(0); H = size[2]
p = max(float(size.max()) / 230.0, 0.2)                     # voxel pitch (mm)
lo = v.min(0) - 2 * p; dims = np.ceil((v.max(0) + 2 * p - lo) / p).astype(int)
print(f"model {size.round(1).tolist()} mm, voxel {p:.2f} mm, grid {dims.tolist()}")

# ---------- 1. voxelize (columns along z, signed crossings = winding number)
off = 0.5 + 1e-3 * np.pi                                    # column centres slightly jittered (avoid exact edge hits)
x = P[:, :, 0]; y = P[:, :, 1]
ix0 = np.ceil((x.min(1) - lo[0]) / p - off).astype(int); ix1 = np.floor((x.max(1) - lo[0]) / p - off).astype(int)
iy0 = np.ceil((y.min(1) - lo[1]) / p - off).astype(int); iy1 = np.floor((y.max(1) - lo[1]) / p - off).astype(int)
nx_ = np.maximum(ix1 - ix0 + 1, 0); ny_ = np.maximum(iy1 - iy0 + 1, 0); cnt = nx_ * ny_
tri = np.repeat(np.arange(len(t)), cnt)
k = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
cx = ix0[tri] + k % nx_[tri]; cy = iy0[tri] + k // nx_[tri]
px = lo[0] + (cx + off) * p; py = lo[1] + (cy + off) * p
a, b, c = P[tri, 0], P[tri, 1], P[tri, 2]
def ef(p0, p1): return (p1[:, 0] - p0[:, 0]) * (py - p0[:, 1]) - (p1[:, 1] - p0[:, 1]) * (px - p0[:, 0])
w0, w1, w2 = ef(b, c), ef(c, a), ef(a, b); area = w0 + w1 + w2
inside = (np.abs(area) > 1e-12) & (((w0 >= 0) & (w1 >= 0) & (w2 >= 0)) | ((w0 <= 0) & (w1 <= 0) & (w2 <= 0)))
tri, cx, cy, w0, w1, w2, area = tri[inside], cx[inside], cy[inside], w0[inside], w1[inside], w2[inside], area[inside]
zc = (w0 * a[inside, 2] + w1 * b[inside, 2] + w2 * c[inside, 2]) / area
sgn = -np.sign(fn[tri, 2]).astype(np.int32)                 # face pointing down = entering the solid
col = cx.astype(np.int64) * dims[1] + cy
o = np.lexsort((zc, col)); col, zc, sgn = col[o], zc[o], sgn[o]
first = np.r_[True, col[1:] != col[:-1]]
cs = np.cumsum(sgn); start = np.maximum.accumulate(np.where(first, np.arange(len(cs)), 0))
wind = cs - np.r_[0, cs][start]                            # winding after each crossing, per column
seg = (wind[:-1] > 0) & ~first[1:]                          # interval k..k+1 inside and same column
za, zb, cc = zc[:-1][seg], zc[1:][seg], col[:-1][seg]
z0 = np.ceil((za - lo[2]) / p - 0.5).astype(int); z1 = np.floor((zb - lo[2]) / p - 0.5).astype(int)
n = np.maximum(z1 - z0 + 1, 0)
iv = np.repeat(np.arange(len(n)), n); kz = z0[iv] + np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
occ = np.zeros(dims, bool)
cc = cc[iv]; occ[cc // dims[1], cc % dims[1], np.clip(kz, 0, dims[2] - 1)] = True
occ = ndi.binary_closing(occ, iterations=1) | occ
occ = ndi.binary_fill_holes(occ)
lab_cc, ncc = ndi.label(occ)
if ncc > 1:                                                  # drop voxel dust
    sz = np.bincount(lab_cc.ravel()); sz[0] = 0; occ = np.isin(lab_cc, np.where(sz > sz.max() * 0.002)[0])
vol_total = occ.sum() * p ** 3
print(f"solid {vol_total / 1000:.1f} cm3 ({time.time() - t0:.1f}s)")

A = occ.sum((0, 1)); zs = np.where(A > 0)[0]
nb = max(2, int(round(2.0 / p)))

# ---------- 3/4. blobs (watershed on thickness) merged into pieces
def adjacency(lab, dist):
    """pairs of touching labels -> (saddle thickness, contact voxels)."""
    out = {}
    for ax in range(3):
        a_ = np.moveaxis(lab, ax, 0); d_ = np.moveaxis(dist, ax, 0)
        l1, l2 = a_[:-1], a_[1:]; m = (l1 > 0) & (l2 > 0) & (l1 != l2)
        i, j = l1[m], l2[m]; s = np.minimum(d_[:-1][m], d_[1:][m])
        lo_, hi_ = np.minimum(i, j), np.maximum(i, j); key = lo_.astype(np.int64) * 100000 + hi_
        u, inv = np.unique(key, return_inverse=True)
        smax = np.zeros(len(u)); np.maximum.at(smax, inv, s); cnt_ = np.bincount(inv)
        for kk, s_, c_ in zip(u.tolist(), smax.tolist(), cnt_.tolist()):
            e = out.setdefault((kk // 100000, kk % 100000), [0.0, 0])
            e[0] = max(e[0], s_); e[1] += c_
    return out


def blobs(mask):
    dist = ndi.distance_transform_edt(mask) * p
    mk = h_maxima(dist, float(HMIN) if HMIN else max(0.6, 2.2 * p)) & mask
    markers, nm = ndi.label(mk)
    lab = watershed(-dist, markers, mask=mask)
    idx = np.arange(lab.max() + 1)
    vol = np.bincount(lab.ravel(), minlength=len(idx)).astype(float) * p ** 3; vol[0] = 0
    core = ndi.maximum(dist, lab, idx); core[0] = 0
    MIN_VOL = max(VOLF * vol.sum(), 150.0); MIN_AREA = 20.0
    adj = adjacency(lab, dist); alive = set(int(x) for x in idx[1:] if vol[x] > 0)
    parent = idx.copy()
    while True:
        best, bk = None, None
        for (i, j), (sd, cn) in adj.items():
            ratio = sd / max(1e-6, min(core[i], core[j]))
            small = min(vol[i], vol[j]) < MIN_VOL; weak = cn * p * p < MIN_AREA
            score = (3 if small else 0) + (2 if weak else 0) + ratio   # tiny blobs first, then non-necks
            if (small or weak or ratio > LEVEL or len(alive) > MAXP) and (best is None or score > best):
                best, bk = score, (i, j)
        if bk is None: break
        i, j = bk; keep, gone = (i, j) if vol[i] >= vol[j] else (j, i)
        parent[parent == gone] = keep; vol[keep] += vol[gone]; core[keep] = max(core[keep], core[gone]); vol[gone] = 0; alive.discard(gone)
        new = {}
        for (a_, b_), (sd, cn) in adj.items():
            a_ = keep if a_ == gone else a_; b_ = keep if b_ == gone else b_
            if a_ == b_: continue
            kk = (min(a_, b_), max(a_, b_)); e = new.setdefault(kk, [0.0, 0]); e[0] = max(e[0], sd); e[1] += cn
        adj = new
    lab = parent[lab]
    regs = sorted([r for r in np.unique(lab) if r > 0], key=lambda r: -vol[r])
    L = np.zeros(dims, np.int16)
    for k_, r in enumerate(regs): L[lab == r] = k_ + 1
    print(f"{nm} blobs -> {len(regs)} piece(s) ({time.time() - t0:.1f}s)")
    return L, len(regs)


L, npieces = blobs(occ)
dist = ndi.distance_transform_edt(occ) * p
bbox_xy = dims[0] * dims[1] * p * p
# flat disc/plinth candidate: one wide shape on the table whose area stays constant, then drops
cc2, n2 = ndi.label(bot := np.any(occ[:, :, zs[0]:zs[0] + nb], 2)); big = np.bincount(cc2[bot]).max() if n2 else 0
Az = A * p * p; A_bot = np.median(Az[zs[0]:zs[0] + nb]); zp = zs[0] + nb
while zp < zs[0] + 0.3 * (zs[-1] - zs[0]) and Az[zp] >= 0.85 * A_bot: zp += 1
plinth = (n2 and big >= 0.85 * bot.sum() and bot.sum() * p * p >= 0.3 * bbox_xy and (zp - zs[0]) * p >= 1.5
          and zp < zs[0] + 0.3 * (zs[-1] - zs[0]))
# base = the piece that owns most of the model's footprint on the table, with its weight near the table
base_lbl = None
if npieces > 1:
    fl = L[:, :, zs[0]:zs[0] + nb].max(2)
    share = np.bincount(fl[bot], minlength=npieces + 1)[1:] / max(1, bot.sum())
    kb = int(np.argmax(share)); zb_ = np.argwhere(L == kb + 1)[:, 2]
    low = (zb_.mean() - zs[0]) / max(1, zs[-1] - zs[0]) < 0.35
    figure_glued = plinth and (zb_ >= zp).mean() > 0.5             # most of it sits above the plinth -> it's the figure
    if share[kb] >= 0.6 and bot.sum() * p * p >= 0.15 * bbox_xy and low and not figure_glued:
        base_lbl = kb + 1; print(f"base: piece {kb} ({share[kb]:.0%} of the footprint)")
def plinth_side(ax, sgn):
    """flat plinth seen from one side of the bounding box: returns slab mask or None."""
    O = np.moveaxis(occ, ax, 2)
    if sgn < 0: O = O[:, :, ::-1]
    Az_ = O.sum((0, 1)) * p * p; zz = np.where(Az_ > 0)[0]
    if len(zz) < 4: return None
    bt = np.any(O[:, :, zz[0]:zz[0] + nb], 2); c2, m2 = ndi.label(bt)
    if not m2: return None
    Ab = np.median(Az_[zz[0]:zz[0] + nb]); z_ = zz[0] + nb
    while z_ < zz[0] + 0.3 * (zz[-1] - zz[0]) and Az_[z_] >= 0.85 * Ab: z_ += 1
    cross = O.shape[0] * O.shape[1] * p * p
    ok_ = (np.bincount(c2[bt]).max() >= 0.85 * bt.sum() and bt.sum() * p * p >= 0.3 * cross and (z_ - zz[0]) * p >= 1.5
           and z_ < zz[0] + 0.3 * (zz[-1] - zz[0]))
    if not ok_: return None
    sl = np.zeros_like(O); sl[:, :, :z_] = O[:, :, :z_]
    if sgn < 0: sl = sl[:, :, ::-1]
    return np.moveaxis(sl, 2, ax), (z_ - zz[0]) * p, bt.sum() * p * p


if base_lbl is None:
    # plinth under the figure first; otherwise a backdrop disc on any side (figures printed lying down)
    found = None
    for ax_, sg_ in ((2, 1), (2, -1), (0, 1), (0, -1), (1, 1), (1, -1)):
        r_ = plinth_side(ax_, sg_)
        if r_ is not None and (found is None or (ax_ != 2 and r_[2] > found[1][2])):
            found = ((ax_, sg_), r_)
            if ax_ == 2 and sg_ == 1: break
    if found is not None:
        slab = found[1][0]
        L, npieces = blobs(occ & ~slab)
        L[slab] = npieces + 1; npieces += 1; base_lbl = npieces
        print(f"base: flat plinth {found[1][1]:.1f} mm thick (side {found[0]})")

# ---------- 5. per-piece stats, seeds and names
vc = lambda idxs: lo + (np.asarray(idxs) + 0.5) * p
fc = P.mean(1); fnn = fn / (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)
tl = np.full(len(t), 0, np.int16)
for step in (0.4, 0.9, 1.5, 2.2, 3.0):                      # step into the solid along -normal until a voxel is hit
    need = tl == 0
    if not need.any(): break
    q = np.floor((fc[need] - fnn[need] * step * p - lo) / p).astype(int)
    ok = np.all((q >= 0) & (q < dims), 1); vals = np.zeros(need.sum(), np.int16)
    vals[ok] = L[q[ok, 0], q[ok, 1], q[ok, 2]]; tl[np.where(need)[0]] = vals
if (tl == 0).any() and (tl > 0).any():
    tr_ = cKDTree(fc[tl > 0]); _, j_ = tr_.query(fc[tl == 0]); tl[tl == 0] = tl[tl > 0][j_]
np.save(f"{wd}/smart_view.npy", (tl - 1).astype(np.int8))

cores = np.array([np.argwhere(L == k_ + 1).mean(0) for k_ in range(npieces)]) * p + lo
adjL = adjacency(L, dist)
deg = np.zeros(npieces + 1)
for (i, j) in adjL:
    if i != base_lbl and j != base_lbl: deg[i] += 1; deg[j] += 1
fig_ids = [k_ for k_ in range(npieces) if k_ + 1 != base_lbl]
body_k = max(fig_ids, key=lambda k_: (deg[k_ + 1], (L == k_ + 1).sum())) if fig_ids else 0
body = cores[body_k]
dirs = {(2, 1): "Parte de cima", (2, -1): "Parte de baixo", (0, 1): "Lado direito", (0, -1): "Lado esquerdo", (1, 1): "Parte de trás", (1, -1): "Parte da frente"}
PAL = ["#f2c12e", "#3b82f6", "#ef4444", "#22c55e", "#a855f7", "#f97316", "#14b8a6", "#ec4899", "#84cc16", "#06b6d4"]
pieces = []; used = {}
for k_ in range(npieces):
    lbl = k_ + 1; is_base = lbl == base_lbl
    if is_base: name = "Base"
    elif k_ == body_k: name = "Corpo"
    elif base_lbl is None and (np.argwhere(L == k_ + 1)[:, 2].min() - zs[0]) * p < 1.5: name = "Apoio"
    else:
        d = cores[k_] - body; ax = int(np.argmax(np.abs(d))); name = dirs[(ax, int(np.sign(d[ax])) or 1)]
    used[name] = used.get(name, 0) + 1
    if used[name] > 1: name = f"{name} {used[name]}"
    mask = tl == lbl
    cand = np.where(mask)[0]
    if len(cand):   # only the main surface patch of the piece (stray patches would make the min-cut circle a seed)
        sub = t[cand]; import scipy.sparse as sp_
        from scipy.sparse.csgraph import connected_components as ccomp
        e_ = np.r_[sub[:, 0], sub[:, 1], sub[:, 2]]; f_ = np.tile(np.arange(len(cand)), 3)
        M_ = sp_.coo_matrix((np.ones(len(e_)), (f_, e_)), shape=(len(cand), len(v))).tocsr()
        _, cl = ccomp(M_ @ M_.T, directed=False); cand = cand[cl == np.bincount(cl).argmax()]
    pts = []
    if len(cand):
        # prefer triangles far from the other pieces (seeds must be well inside the piece)
        other = np.where((tl != lbl) & (tl > 0))[0]
        dd = cKDTree(fc[other]).query(fc[cand])[0] if len(other) else np.full(len(cand), 99.0)
        good = cand[dd >= max(2.0, 0.45 * dd.max())]
        if not len(good): good = cand[np.argsort(-dd)[:max(1, len(cand) // 10)]]
        sel = [good[0]]; dmin = np.linalg.norm(fc[good] - fc[good[0]], axis=1)
        for _ in range(min(7, len(good) - 1)):                 # farthest point sampling
            j = int(np.argmax(dmin)); sel.append(good[j]); dmin = np.minimum(dmin, np.linalg.norm(fc[good] - fc[good[j]], axis=1))
        pts = [np.round(fc[s], 3).tolist() for s in sel]
    vox = np.argwhere(L == lbl); ext = (vox.max(0) - vox.min(0) + 1) * p if len(vox) else np.zeros(3)
    fits = bool(np.sort(ext)[-1] <= BED - 1 and np.sort(ext)[-2] <= BED - 1)
    cuts = [dict(to=int(j if i == lbl else i) - 1, area=round(cn * p * p, 1)) for (i, j), (sd, cn) in adjL.items() if lbl in (i, j)]
    pieces.append(dict(name=name, color="#9ca3af" if is_base else PAL[k_ % len(PAL)], points=pts, base=is_base,
                       volume_cm3=round(float((L == lbl).sum() * p ** 3 / 1000), 1), size=np.round(ext, 1).tolist(), fits=fits, cuts=cuts))
# base must be last in the cutter's group list (it gets what is left)
order = [i for i, pc in enumerate(pieces) if not pc["base"]] + [i for i, pc in enumerate(pieces) if pc["base"]]
if base_lbl is None:   # without a base, the body is the "rest" piece -> put it last
    order = [i for i in order if i != body_k] + [body_k]
remap = np.full(len(pieces) + 1, -1, np.int8)
for new_i, old_i in enumerate(order): remap[old_i] = new_i
sv = np.load(f"{wd}/smart_view.npy"); np.save(f"{wd}/smart_view.npy", np.where(sv >= 0, remap[np.maximum(sv, 0)], -1).astype(np.int8))
pieces = [pieces[i] for i in order]
for pc in pieces:
    for c_ in pc["cuts"]: c_["to"] = int(remap[c_["to"]])
res = dict(level=cfg.get("level", "medio"), voxel_mm=round(p, 2), base=base_lbl is not None, pieces=pieces, seconds=round(time.time() - t0, 1))
json.dump(res, open(f"{wd}/smart.json", "w"), indent=1, ensure_ascii=False)
for pc in pieces:
    print(f"PIECE {pc['name']}: {pc['volume_cm3']} cm3, {pc['size']} mm, fits={pc['fits']}, cuts={[c['area'] for c in pc['cuts']]} mm2, seeds={len(pc['points'])}")
print(f"done {time.time() - t0:.1f}s")
