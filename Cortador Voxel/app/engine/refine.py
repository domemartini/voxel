"""Smooth seams by cutting THROUGH triangles.
A per-vertex soft label field F (nV x n_parts) is blurred near the seams; the cut is then the exact
iso-line where the two strongest parts are equal (marching triangles), so seams become smooth
curves instead of following jagged triangle edges.
  hard_field(v,t,seg,ng)                 -> F from the triangle labels (area weighted)
  blur_field(v,t,F,region,strength,lock) -> F blurred inside region (triangles), lock = frozen tris
  refine(v,t,F)                          -> v2,t2,seg2 (watertight, labels per new triangle)"""
import numpy as np, scipy.sparse as sp


def tri_area(v, t):
    P = v[t]; return np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1) / 2


def hard_field(v, t, seg, ng):
    a = tri_area(v, t); F = np.zeros((len(v), ng))
    np.add.at(F, (t.ravel(), np.repeat(seg.astype(int), 3)), np.repeat(a, 3))
    return F / (F.sum(1, keepdims=True) + 1e-12)


def blur_field(v, t, F, region, strength, lock=None):
    if lock is not None: region = region & ~lock
    if not region.any(): return F
    nV = len(v); E = np.concatenate([t[region][:, [0, 1]], t[region][:, [1, 2]], t[region][:, [2, 0]]])
    A = sp.coo_matrix((np.ones(2 * len(E)), (np.r_[E[:, 0], E[:, 1]], np.r_[E[:, 1], E[:, 0]])), shape=(nV, nV)).tocsr()
    A.data[:] = 1; deg = np.asarray(A.sum(1)).ravel(); deg[deg == 0] = 1
    isr = np.zeros(nV, bool); isr[np.unique(t[region])] = True
    if lock is not None and lock.any(): isr[np.unique(t[lock])] = False
    elen = np.median(np.linalg.norm(v[E[:, 0]] - v[E[:, 1]], axis=1))
    iters = int(min(600, max(4, (strength / max(elen, 1e-3)) ** 2 / 2)))
    Dinv = sp.diags(1.0 / deg); F = F.copy()
    for _ in range(iters):
        Fn = Dinv @ (A @ F); F[isr] = 0.5 * F[isr] + 0.5 * Fn[isr]
    return F


def refine(v, t, F):
    dom = F.argmax(1); L = dom[t]
    mixed = ~((L[:, 0] == L[:, 1]) & (L[:, 1] == L[:, 2]))
    out_t = [t[~mixed]]; out_s = [L[~mixed, 0]]
    newv = []; ekey = {}; nV = len(v)

    def cross(i, j):
        k = (i, j) if i < j else (j, i)
        if k in ekey: return ekey[k]
        a, b = dom[i], dom[j]
        si = F[i, a] - F[i, b]; sj = F[j, a] - F[j, b]
        u = si / (si - sj) if si != sj else 0.5
        u = min(max(u, 0.03), 0.97)
        idx = nV + len(newv); newv.append(v[i] + (v[j] - v[i]) * u); ekey[k] = idx
        return idx

    tris, labs = [], []
    for tri in t[mixed]:
        i, j, k = int(tri[0]), int(tri[1]), int(tri[2]); li, lj, lk = dom[i], dom[j], dom[k]
        if li != lj and lj != lk and li != lk:          # three parts meet: fan from the centre
            c = nV + len(newv); newv.append(v[[i, j, k]].mean(0))
            pij, pjk, pki = cross(i, j), cross(j, k), cross(k, i)
            tris += [[c, i, pij], [c, pij, j], [c, j, pjk], [c, pjk, k], [c, k, pki], [c, pki, i]]
            labs += [li, lj, lj, lk, lk, li]
            continue
        # two parts: rotate so the odd vertex comes first (keeps orientation)
        if lj == lk: o, a, b = i, j, k
        elif li == lk: o, a, b = j, k, i
        else: o, a, b = k, i, j
        pa, pb = cross(o, a), cross(o, b)
        tris += [[o, pa, pb], [pa, a, b], [pa, b, pb]]
        labs += [dom[o], dom[a], dom[a]]
    if tris:
        out_t.append(np.array(tris)); out_s.append(np.array(labs))
    v2 = np.vstack([v, np.array(newv)]) if newv else v
    return v2, np.vstack(out_t), np.concatenate(out_s).astype(np.int8)
