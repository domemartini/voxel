"""Conserto de malha: separa arestas com 3+ faces e fecha buracos (usado pela separação volumétrica)."""
import numpy as np


def split_nonmanifold(v, t):
    """give every fan of faces around a vertex its own copy of the vertex: edges shared by 3+ faces
    (two surfaces touching) come apart, so the mesh becomes manifold."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    nF = len(t); corner = np.arange(nF * 3).reshape(-1, 3)
    he = np.c_[t[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)]; hf = np.repeat(np.arange(nF), 3)
    hc = np.c_[corner[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)]            # corners at the two ends of each half-edge
    key = np.minimum(he[:, 0], he[:, 1]).astype(np.int64) * (len(v) + 1) + np.maximum(he[:, 0], he[:, 1])
    o = np.argsort(key, kind="stable"); ks = key[o]
    starts = np.r_[0, np.where(ks[1:] != ks[:-1])[0] + 1]; cnt = np.diff(np.r_[starts, len(ks)])
    good = starts[cnt == 2]                                              # edges with exactly two faces
    h1, h2 = o[good], o[good + 1]
    same_dir = he[h1, 0] == he[h2, 0]
    ok = ~same_dir                                                       # consistently oriented pairs only
    h1, h2 = h1[ok], h2[ok]
    # half-edge h1 = (a,b), h2 = (b,a): corner of a in h1 <-> corner of a in h2 (which is h2's second end)
    rows = np.r_[hc[h1, 0], hc[h1, 1]]; cols = np.r_[hc[h2, 1], hc[h2, 0]]
    G = sp.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(nF * 3, nF * 3))
    _, lab = connected_components(G, directed=False)
    # new vertex per (original vertex, corner group)
    ov = t.reshape(-1)
    k2 = lab.astype(np.int64)
    uniq, newid = np.unique(k2, return_inverse=True)
    nv = np.zeros((len(uniq), 3)); nv[newid] = v[ov]
    return nv, newid.reshape(-1, 3)


def fill_holes(v, t, max_edges=200):
    """close small open loops with a fan around their centre."""
    e = np.c_[t[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)]
    key = e[:, 0].astype(np.int64) * (len(v) + 1) + e[:, 1]; rev = e[:, 1].astype(np.int64) * (len(v) + 1) + e[:, 0]
    border = e[~np.isin(key, rev)]
    if not len(border): return v, t
    nxt = {int(b): int(a) for a, b in border}                          # walk the loop reversed (fill must face the other way)
    seen = set(); new_v = [v]; new_t = [t]; nV = len(v)
    for s0 in list(nxt):
        if s0 in seen: continue
        loop = [s0]; cur = s0
        while True:
            cur = nxt.get(cur)
            if cur is None or cur == s0 or cur in seen or len(loop) > max_edges: break
            loop.append(cur)
        seen.update(loop)
        if cur != s0 or len(loop) < 3: continue
        c = v[loop].mean(0); new_v.append(c[None]); ci = nV; nV += 1
        new_t.append(np.array([[ci, loop[i], loop[(i + 1) % len(loop)]] for i in range(len(loop))]))
    return np.vstack(new_v), np.vstack(new_t)
