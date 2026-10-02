"""Smart splitter: analyse the model and suggest how to cut it into printable pieces.
1. voxelize the light view mesh (winding-number fill, robust to overlapping shells)
2. base = the piece that owns the table footprint (thickness watershed) or a flat plinth
3. tips = points far from the body core, walking inside the solid (hands, feet, head, weapons, tails)
4. for each tip, grow a region toward the core and min-cut it against the core: cuts that stay the same
   while the region grows are real joints (neck, shoulder, hip, wrist...)
5. keep cuts that are short for the piece they free (score = cut length / sqrt(piece area)), sized by level
6. seed points for every piece -> the normal min-cut on the full mesh does the precise seam
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
LEVEL, VOLF, MAXP = 0.6, 0.03, 7          # thickness-watershed settings (only used to find the base)
LVL = cfg.get("level", "medio")
LV = {"poucas": dict(minf=0.06, maxp=4, q=2.5, mincut=16),
      "medio": dict(minf=0.02, maxp=8, q=2.8, mincut=12),
      "muitas": dict(minf=0.008, maxp=14, q=3.1, mincut=7)}[LVL]
for k_ in ("minf", "maxp", "q", "mincut"):
    if k_ in cfg: LV[k_] = type(LV[k_])(cfg[k_])
BED = float(cfg.get("bed", 256))
HMIN = None
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

base_vox = (L == base_lbl) if base_lbl else np.zeros(dims, bool)

# ---------- 3. evaluation mesh + crease-aware cut graph (same weights as the real min-cut)
import heapq
import scipy.sparse as sp
from scipy.sparse.csgraph import maximum_flow, breadth_first_order, connected_components
from skimage.graph import MCP_Geometric
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # módulos do motor (o Python embutido não põe a pasta do script no caminho)
import simplificar as fs
figv = occ & ~base_vox
ve, te = fs.simplify(v.astype(np.float32), t.astype(np.int32), target_reduction=max(0.0, 1 - 80000 / len(t)))
ve = np.asarray(ve, float); te = np.asarray(te, np.int64); nV = len(ve)
Pq = ve[te]; fq = np.cross(Pq[:, 1] - Pq[:, 0], Pq[:, 2] - Pq[:, 0]); farea = np.linalg.norm(fq, axis=1) / 2
fq /= np.linalg.norm(fq, axis=1)[:, None] + 1e-12; fcq = Pq.mean(1)
e = np.concatenate([te[:, [0, 1]], te[:, [1, 2]], te[:, [2, 0]]]); e.sort(1); fid = np.tile(np.arange(len(te)), 3)
key = e[:, 0] * nV + e[:, 1]; o = np.argsort(key, kind="stable"); key, fid, e = key[o], fid[o], e[o]
first = np.r_[True, key[1:] != key[:-1]]; Ed = e[first]; F1 = fid[first]
F2 = np.full(len(Ed), -1); idx_ = np.where(~first)[0]; F2[np.searchsorted(np.where(first)[0], idx_, side="right") - 1] = fid[idx_]
EL = np.linalg.norm(ve[Ed[:, 0]] - ve[Ed[:, 1]], axis=1); w = np.ones(len(Ed)); ok = F2 >= 0
ang = np.degrees(np.arccos(np.clip((fq[F1[ok]] * fq[F2[ok]]).sum(1), -1, 1)))
conc = ((fcq[F2[ok]] - fcq[F1[ok]]) * fq[F1[ok]]).sum(1) > 0
w[ok] = np.where(conc, 1 - 0.96 * np.clip((ang - 15) / 35, 0, 1), 1.0)
cap = np.maximum(1, np.round(EL * w * 1000)).astype(np.int64)
vfa = np.zeros(nV); np.add.at(vfa, te.ravel(), np.repeat(farea / 3, 3))
_, ind = ndi.distance_transform_edt(~occ, return_indices=True)
qv = np.clip(np.floor((ve - lo) / p).astype(int), 0, dims - 1)
qv = ind[:, qv[:, 0], qv[:, 1], qv[:, 2]].T                  # nearest solid voxel of every eval vertex
vbase = base_vox[qv[:, 0], qv[:, 1], qv[:, 2]]
tree = cKDTree(ve)
A_fig = vfa[~vbase].sum()
fvox = np.argwhere(figv)                                     # every figure voxel -> nearest eval vertex
_, vox_near = tree.query(lo + (fvox + 0.5) * p)
BIG = 2 ** 30
NTIP = {"poucas": 8, "medio": 10, "muitas": 12}[LVL]
# peça que vale imprimir: volume e tamanho mínimos (evita capas finíssimas e lasquinhas de poucos mm³)
V_FIG = float(len(fvox)) * p ** 3
VMIN = max(250.0, {"poucas": 0.05, "medio": 0.02, "muitas": 0.008}[LVL] * V_FIG); EMIN = 10.0
H_FIG = float(np.ptp(ve[~vbase, 2])) if (~vbase).any() else float(H)
if max(H_FIG, float(np.sort(size)[-2])) < 60:                # miniatura: no máximo 2 cortes além da base
    LV["maxp"] = min(LV["maxp"], 2); print(f"MINI {H_FIG:.0f} mm: no máximo 2 cortes")
print(f"eval mesh {len(te)} tris, figure {A_fig / 100:.0f} cm2, {V_FIG / 1000:.1f} cm3, peça mínima {VMIN:.0f} mm3 ({time.time() - t0:.1f}s)")


def cut_from(src, snk, active, band=None):
    """min-cut on the eval surface restricted to `active` vertices; returns the source side.
    band: só esses vértices entram no grafo; o resto de `active` é contraído no sumidouro (bem mais rápido)."""
    fora = None
    if band is not None:
        fora = active & ~band; active = active & band
    em = active[Ed[:, 0]] & active[Ed[:, 1]]
    ids = np.where(active)[0]; rm = np.full(nV, -1); rm[ids] = np.arange(len(ids)); n = len(ids)
    a, b, c = rm[Ed[em, 0]], rm[Ed[em, 1]], cap[em]
    src = src & active & ~snk; snk = snk & active
    xa = np.zeros(0, int); xc = np.zeros(0, cap.dtype)
    if fora is not None:                                          # arestas da faixa pra fora dela -> direto no sumidouro
        e1 = active[Ed[:, 0]] & fora[Ed[:, 1]]; e2 = active[Ed[:, 1]] & fora[Ed[:, 0]]
        xa = np.r_[rm[Ed[e1, 0]], rm[Ed[e2, 1]]]; xc = np.r_[cap[e1], cap[e2]]
    if not src.any() or (not snk.any() and not len(xa)): return None
    si, ti = rm[np.where(src)[0]], rm[np.where(snk)[0]]
    S_, T_ = n, n + 1
    Gm = sp.csr_matrix((np.r_[c, c, np.full(len(si), BIG), np.full(len(ti), BIG), xc],
                        (np.r_[a, b, np.full(len(si), S_), ti, xa], np.r_[b, a, si, np.full(len(ti), T_), np.full(len(xa), T_)])), shape=(n + 2, n + 2))
    Gm.sum_duplicates(); Gm = Gm.astype(np.int32)
    r = maximum_flow(Gm, S_, T_, method="dinic")
    R = Gm - r.flow; R.data[R.data < 0] = 0; R.eliminate_zeros(); R.data[:] = 1
    reach = breadth_first_order(R, S_, directed=True, return_predecessors=False); reach = reach[reach < n]
    out = np.zeros(nV, bool); out[ids[reach]] = True
    return out


def best_split(mask):
    """best joint inside a piece (eval-vertex mask): tips far from the piece core, growing min-cuts."""
    A_reg = vfa[mask].sum()
    if A_reg < 2 * LV["minf"] * A_fig: return None
    vm = mask[vox_near]; vx = fvox[vm]; vm_all = vm
    if len(vx) < 50 or len(vx) * p ** 3 < 2 * VMIN: return None
    lo_i = vx.min(0) - 1; hi_i = vx.max(0) + 2; sh = hi_i - lo_i
    sub = np.zeros(sh, bool); sub[tuple((vx - lo_i).T)] = True
    dsub = ndi.distance_transform_edt(sub) * p
    core = np.unravel_index(np.argmax(dsub), sh); corep = lo + (np.array(core) + lo_i + 0.5) * p
    cost = np.where(sub, 1.0, -1.0)
    Gc, _ = MCP_Geometric(cost, fully_connected=True).find_costs([core]); Gc = np.where(sub & np.isfinite(Gc), Gc * p, 0)
    surf = sub & ~ndi.binary_erosion(sub)
    kk = max(3, int(round(8 / p))) | 1
    tv = np.argwhere(surf & (Gc == ndi.maximum_filter(np.where(surf, Gc, 0), size=kk)) & (Gc > 0.15 * Gc.max()))
    tv = tv[np.argsort(-Gc[tuple(tv.T)])]
    Rn = 0.1 * np.linalg.norm(sh) ; keep_ = []           # spread the tips out (no ten tips on the same sword)
    for x in tv:
        if all(np.linalg.norm(x - y) > Rn for y in keep_): keep_.append(x)
        if len(keep_) >= NTIP: break
    tv = np.array(keep_) if keep_ else tv[:0]
    snk = np.zeros(nV, bool); snk[tree.query_ball_point(corep, dsub.max() + 3 * p)] = True; snk &= mask
    qs = qv - lo_i; inb = np.all((qs >= 0) & (qs < sh), 1) & mask
    best = None
    for tip in tv:
        Gt, _ = MCP_Geometric(cost, fully_connected=True).find_costs([tuple(tip)])
        D = Gt[core] * p
        if not np.isfinite(D) or D <= 0: continue
        gv = np.full(nV, np.inf); gv[inb] = Gt[tuple(qs[inb].T)] * p
        prev = None
        for f in (0.1, 0.2, 0.3, 0.45, 0.6, 0.75):
            inR = cut_from(np.isfinite(gv) & (gv < f * D), snk, mask, band=np.isfinite(gv) & (gv < min(1.05, f + 0.4) * D))
            if inR is None or not inR.any(): prev = None; continue
            if prev is not None and (prev & inR).sum() / max(1, (prev | inR).sum()) > 0.9:
                ar = vfa[inR].sum(); rest = A_reg - ar
                cm = (inR[Ed[:, 0]] != inR[Ed[:, 1]]) & mask[Ed[:, 0]] & mask[Ed[:, 1]]
                cl = float(EL[cm].sum()); q = cl / np.sqrt(max(ar, 1e-6))
                cv = inR[vox_near] & vm_all                                   # voxels da peça que o corte solta
                vol_c = float(cv.sum()) * p ** 3; vol_r = float((vm_all & ~inR[vox_near]).sum()) * p ** 3
                ext_c = float(np.ptp(fvox[cv], 0).max()) * p if cv.any() else 0.0
                # espessura típica da parte (lâmina de capa fina não vira peça: some ao separar)
                esp_c = 2 * float(np.percentile(dsub[tuple((fvox[cv] - lo_i).T)], 90)) if cv.any() else 0.0
                if min(ar, rest) >= LV["minf"] * A_fig and q <= LV["q"] and cl >= LV["mincut"] and min(vol_c, vol_r) >= VMIN and ext_c >= EMIN and esp_c >= 2.0:
                    score = np.sqrt(min(ar, rest) / A_fig) / q
                    if best is None or score > best[0]: best = (score, inR.copy(), cl, ar, q)
            prev = inR
    return best


# ---------- 4/5. start from the pieces that are already loose (several figures / parts laid on the plate)
cc_lab, ncc = ndi.label(figv)
vcc = cc_lab[qv[:, 0], qv[:, 1], qv[:, 2]]
parts = []
for k_ in range(1, ncc + 1):
    m_ = (vcc == k_) & ~vbase
    if base_lbl and 0 < vfa[m_].sum() < 0.05 * A_fig: vbase |= m_; continue   # pebbles/chains lying on the base
    if vfa[m_].sum() >= 0.01 * A_fig: parts.append(m_)
if not parts: parts = [~vbase]
if len(parts) > 1:                                           # cascas soltas finas/pequenas demais (ex.: capa enfiada no corpo) ficam com a maior
    d_all = ndi.distance_transform_edt(figv) * p
    ok_, ruim_ = [], []
    for m_ in parts:
        vv_ = m_[vox_near]; vol_ = float(vv_.sum()) * p ** 3; esp_ = 2 * float(np.percentile(d_all[tuple(fvox[vv_].T)], 90)) if vv_.any() else 0.0
        (ok_ if vol_ >= VMIN and esp_ >= 2.0 else ruim_).append(m_)
    if not ok_: ok_ = [max(parts, key=lambda m_: vfa[m_].sum())]; ruim_ = [m_ for m_ in parts if m_ is not ok_[0]]
    big_ = int(np.argmax([vfa[m_].sum() for m_ in ok_]))
    for m_ in ruim_: ok_[big_] = ok_[big_] | m_
    if ruim_: print(f"LOOSE {len(ruim_)} casca(s) fina(s)/pequena(s) juntada(s) à maior")
    parts = ok_
rest_ = ~vbase & ~np.any(parts, 0)
if rest_.any(): parts[int(np.argmax([vfa[m_].sum() for m_ in parts]))] |= rest_
if len(parts) > 1: print(f"LOOSE {len(parts)} separate piece(s) already")
# technical part? CAD exports have long thin triangles; block/voxel models are all axis aligned; plaques are flat
vf_ = np.load(f"{wd}/v.npy"); tf_ = np.load(f"{wd}/t.npy")
if len(tf_) > 300000: tf_ = tf_[np.random.default_rng(0).choice(len(tf_), 300000, replace=False)]
Pf_ = vf_[tf_]; Lf_ = np.linalg.norm(Pf_[:, [1, 2, 0]] - Pf_, axis=2).max(1)
Af_ = np.linalg.norm(np.cross(Pf_[:, 1] - Pf_[:, 0], Pf_[:, 2] - Pf_[:, 0]), axis=1) / 2
asp_med = float(np.median(Lf_ ** 2 / np.maximum(2 * Af_, 1e-12)))
fig_f = ~vbase[te].any(1)
axis_frac = farea[fig_f & (np.abs(fq).max(1) > np.cos(np.radians(2)))].sum() / max(farea[fig_f].sum(), 1e-9)
ss_ = np.sort(size); plaque = ss_[0] / ss_[-1] < 0.06
TECH = asp_med > 9 or axis_frac > 0.85 or plaque
TECH_WHY = "triângulos de CAD" if asp_med > 9 else "blocos alinhados" if axis_frac > 0.85 else "placa fina" if plaque else ""
print(f"shape check: triangle aspect {asp_med:.1f}, axis-aligned {100 * axis_frac:.0f}%, thinness {ss_[0] / ss_[-1]:.2f}" + (f" -> TECH ({TECH_WHY})" if TECH else ""))
# ---------- split recursively: always take the best joint available in any piece
heap = []; cnt_ = [0]
def push(i):
    b = best_split(parts[i])
    if b is not None: cnt_[0] += 1; heapq.heappush(heap, (-b[0], cnt_[0], i, b))
if not TECH:
    for i0 in range(len(parts)): push(i0)
while heap and len(parts) < LV["maxp"] + 1:
    _, _, i, b = heapq.heappop(heap)
    score, inR, cl, ar, q = b
    child = inR & parts[i]; parts[i] = parts[i] & ~child; parts.append(child)
    print(f"JOINT cut {cl:.0f} mm frees {ar / 100:.1f} cm2 ({100 * ar / A_fig:.0f}%), score {q:.2f} ({time.time() - t0:.1f}s)")
    heap = [h for h in heap if h[2] != i]; heapq.heapify(heap)
    push(i); push(len(parts) - 1)
print(f"{len(parts)} figure piece(s) ({time.time() - t0:.1f}s)")

# ---------- 6. labels, seeds, stats  (the biggest piece is the body; it gets what is left)
areas = [vfa[m].sum() for m in parts]
BODY_i = int(np.argmax(areas))
others = [int(i) for i in np.argsort(-np.array(areas)) if i != BODY_i]
lab_v = np.full(nV, -1, np.int32)
for k_, i in enumerate(others): lab_v[parts[i]] = k_
NB = len(others); BODY = NB; BASE = NB + 1
lab_v[parts[BODY_i]] = BODY; lab_v[(lab_v < 0) & ~vbase] = BODY
if base_lbl: lab_v[vbase] = BASE
npieces = BASE + 1 if base_lbl else BODY + 1
adjm = sp.coo_matrix((np.ones(len(Ed) * 2), (np.r_[Ed[:, 0], Ed[:, 1]], np.r_[Ed[:, 1], Ed[:, 0]])), shape=(nV, nV)).tocsr()
# view labels: copy from a very close eval vertex, then flood along the view surface (never jump across gaps)
nVv = len(v); dv, jv = tree.query(v, distance_upper_bound=2.5 * p)
labv = np.full(nVv, -1, np.int32); okv = np.isfinite(dv); labv[okv] = lab_v[jv[okv]]
Av = sp.coo_matrix((np.ones(t.size), (t.ravel(), t[:, [1, 2, 0]].ravel())), shape=(nVv, nVv)).tocsr(); Av = (Av + Av.T).tocsr()
for _ in range(200):
    miss = labv < 0
    if not miss.any(): break
    src_ = np.where(~miss)[0]; rows_, cols_ = Av[miss][:, src_].nonzero()
    if not len(rows_): break
    labv[np.where(miss)[0][rows_]] = labv[src_[cols_]]
labv[labv < 0] = BODY
raw = labv[t[:, 0]]
zs_min = ve[:, 2].min()
cent = [ve[lab_v == k_].mean(0) if (lab_v == k_).any() else ve.mean(0) for k_ in range(npieces)]
dirs = {(2, 1): "Parte de cima", (2, -1): "Parte de baixo", (0, 1): "Lado direito", (0, -1): "Lado esquerdo", (1, 1): "Parte de trás", (1, -1): "Parte da frente"}
PAL = ["#f2c12e", "#3b82f6", "#ef4444", "#22c55e", "#a855f7", "#f97316", "#14b8a6", "#ec4899", "#84cc16", "#06b6d4", "#eab308", "#6366f1", "#f43f5e", "#10b981"]
top_k = int(lab_v[np.argmax(np.where(vbase, -1e9, ve[:, 2]))])
cutpairs = {}
cmk = lab_v[Ed[:, 0]] != lab_v[Ed[:, 1]]
for a_, b_, l_ in zip(lab_v[Ed[cmk, 0]], lab_v[Ed[cmk, 1]], EL[cmk]):
    k2 = (int(min(a_, b_)), int(max(a_, b_))); cutpairs[k2] = cutpairs.get(k2, 0) + l_
dist_all = ndi.distance_transform_edt(figv) * p
dvox = dist_all[tuple(fvox.T)]; lvox = lab_v[vox_near]
pieces = []; used = {}
for k_ in range(npieces):
    m = lab_v == k_
    if k_ == BASE: name = "Base"
    elif k_ == BODY: name = "Corpo"
    elif vfa[m].sum() >= 0.06 * A_fig and (lvox == k_).any() and 2 * np.percentile(dvox[lvox == k_], 90) < 3.0: name = "Capa"
    elif vfa[m].sum() >= 0.2 * A_fig and np.ptp(ve[m, 2]) >= 0.5 * np.ptp(ve[~vbase, 2]): name = "Figura 2"
    elif k_ == top_k and cent[k_][2] > cent[BODY][2] and vfa[m].sum() < 0.3 * A_fig: name = "Cabeça"
    elif not base_lbl and m.any() and ve[m, 2].min() - zs_min < 1.5: name = "Apoio"
    else:
        d = cent[k_] - cent[BODY]; ax = int(np.argmax(np.abs(d))); name = dirs[(ax, int(np.sign(d[ax])) or 1)]
    used[name] = used.get(name, 0) + 1
    if used[name] > 1: name = f"{name} {used[name]}"
    cand = np.where(m)[0]; pts = []
    if len(cand):
        sub_ = adjm[cand][:, cand]; _, cl_ = connected_components(sub_, directed=False); cand = cand[cl_ == np.bincount(cl_).argmax()]
        other = np.where(~m)[0]
        dd = cKDTree(ve[other]).query(ve[cand])[0] if len(other) else np.full(len(cand), 99.0)
        good = cand[dd >= max(1.5, 0.45 * dd.max())]
        if not len(good): good = cand[np.argsort(-dd)[:max(1, len(cand) // 10)]]
        sel = [good[0]]; dmin = np.linalg.norm(ve[good] - ve[good[0]], axis=1)
        for _ in range(min(7, len(good) - 1)):
            j = int(np.argmax(dmin)); sel.append(good[j]); dmin = np.minimum(dmin, np.linalg.norm(ve[good] - ve[good[j]], axis=1))
        pts = [np.round(ve[s_], 3).tolist() for s_ in sel]
    ext = ve[m].max(0) - ve[m].min(0) if m.any() else np.zeros(3)
    fits = bool(np.sort(ext)[-1] <= BED - 1 and np.sort(ext)[-2] <= BED - 1)
    cuts = [dict(to=int(b_ if a_ == k_ else a_), length=round(float(l_), 1)) for (a_, b_), l_ in cutpairs.items() if k_ in (a_, b_)]
    pieces.append(dict(name=name, color="#9ca3af" if k_ == BASE else PAL[k_ % len(PAL)], points=pts, base=k_ == BASE,
                       area_cm2=round(float(vfa[m].sum() / 100), 1), size=np.round(ext, 1).tolist(), fits=fits, cuts=cuts))
order = list(range(NB)) + [BODY] + ([BASE] if base_lbl else [])   # the last one gets whatever is left
remap = np.full(npieces, -1); remap[order] = np.arange(len(order))
np.save(f"{wd}/smart_view.npy", np.where(raw >= 0, remap[np.maximum(raw, 0)], -1).astype(np.int8))
pieces = [pieces[i] for i in order]
for pc in pieces:
    for c_ in pc["cuts"]: c_["to"] = int(remap[c_["to"]])
res = dict(level=LVL, voxel_mm=round(p, 2), base=bool(base_lbl), pieces=pieces, seconds=round(time.time() - t0, 1),
           technical=TECH_WHY if TECH else False, loose=len(parts) if ncc > 1 else 1)
json.dump(res, open(f"{wd}/smart.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
for pc in pieces:
    print(f"PIECE {pc['name']}: {pc['size']} mm, fits={pc['fits']}, cuts={[c['length'] for c in pc['cuts']]} mm, seeds={len(pc['points'])}")
print(f"done {time.time() - t0:.1f}s")
