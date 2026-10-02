"""Build closed part meshes straight from a surface segmentation (seg.npy from mincut_multi.py):
part = its own surface + a cap that exactly fills every seam loop (constrained Delaunay on the
loop's best-fit plane). No boolean slabs -> the cut follows painted/creased seams exactly, curved
or not. Also writes caps.json for plugs (cap of part a points into the later part b).
usage: python separate_seg.py <workdir>
needs v.npy t.npy seg.npy marks.json  writes part_<k>_v.npy/_t.npy, parts.json, caps.json"""
import sys, json, numpy as np, scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
import shapely
from shapely.geometry import Polygon

wd = sys.argv[1]
v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); seg = np.load(f"{wd}/seg.npy").astype(int)
G = json.load(open(f"{wd}/marks.json"))["groups"]; ng = len(G)
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DELF = f"{wd}/del.npy"
dele = np.load(DELF) if os.path.exists(DELF) else None
if dele is not None and (len(dele) != len(t) or not dele.any()): dele = None
F = None
if os.path.exists(f"{wd}/field.npy"):
    F = np.load(f"{wd}/field.npy").astype(np.float64)
    if F.shape != (len(v), ng): F = None
if dele is not None:                                      # the "xadrez" area is an extra label that no piece keeps
    print(f"deleted by the user: {int(dele.sum())} triangles")
    if F is not None:
        F = np.c_[F, np.zeros(len(v))]; dv = np.unique(t[dele]); F[dv] = 0; F[dv, ng] = 1
    seg = seg.copy(); seg[dele] = ng
if F is not None:
    from refine import refine
    v, t, seg = refine(v, t, F); seg = seg.astype(int)
    print(f"seams cut through triangles (smooth): {len(t)} triangles after refinement")
VOID = ng if dele is not None else None
NL = ng + 1 if VOID is not None else ng
nV = len(v)
names = [g["name"] for g in G] + (["(apagado)"] if VOID is not None else [])
# directed half-edges and their faces
he = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]); hf = np.tile(np.arange(len(t)), 3)
key = he[:, 0].astype(np.int64) * nV + he[:, 1]
opp = dict(zip(key.tolist(), hf.tolist()))
rev = he[:, 1].astype(np.int64) * nV + he[:, 0]
of = np.array([opp.get(k, -1) for k in rev.tolist()])
bnd = (of >= 0) & (seg[hf] != seg[np.maximum(of, 0)])
_e = np.sort(he, 1); mesh_edges = set((_e[:, 0].astype(np.int64) * nV + _e[:, 1]).tolist())
caps_json = {n: [] for n in names}
extra_v = [v]; nextra = nV
cap_faces = {k: [] for k in range(NL)}   # faces (oriented for that part)
bad = 0; nsm = 0
from capsmooth import smooth_cap, disk_cap
for a in range(NL):
    for b in range(a + 1, NL):
        # half-edges of part a whose opposite face is part b: directed i->j as seen from a
        m = bnd & (seg[hf] == a) & (seg[np.maximum(of, 0)] == b)
        if not m.any(): continue
        E = he[m]
        lab = connected_components(sp.coo_matrix((np.ones(len(E)), (E[:, 0], E[:, 1])), shape=(nV, nV)), directed=False)[1]
        for L in np.unique(lab[E[:, 0]]):
            e = E[lab[E[:, 0]] == L]
            nxt = {}
            for i, j in e: nxt.setdefault(int(i), []).append(int(j))
            if any(len(x) != 1 for x in nxt.values()):
                bad += 1; print(f"seam {names[a]}|{names[b]}: loop with {len(e)} edges is not simple (pinch) - using fan cap")
            # walk the cycle following part a's direction i->j (a seam that ends at a 3-piece junction is an open chain:
            # the cap closes it with the chord from its end back to its start, as before)
            start = int(e[0, 0]); cyc = [start]; cur = start
            for _ in range(len(e)):
                if cur not in nxt: break
                cur = nxt[cur][0]
                if cur == start: break
                cyc.append(cur)
            cycles = [cyc]
            for cyc in cycles:
                if len(cyc) < 3: continue
                cyc = np.array(cyc); P = v[cyc]; c = P.mean(0)
                _, _, vt = np.linalg.svd(P - c); nrm = vt[2]; A = vt[0]; B = vt[1]
                uv = np.c_[(P - c) @ A, (P - c) @ B]
                tris = None
                poly = Polygon(uv)
                if len(cyc) >= 3 and poly.is_valid and True:
                    idx = {tuple(np.round(p, 9)): k for k, p in enumerate(uv)}
                    try:
                        tri = shapely.constrained_delaunay_triangles(poly)
                        tris = np.array([[idx[tuple(np.round(q, 9))] for q in list(g.exterior.coords)[:3]] for g in tri.geoms])
                    except Exception:
                        tris = None
                gidx = None
                if os.environ.get("VOXELCUT_DEBUG_CAPS"):
                    print(f"  SEAM {names[a]}|{names[b]}: {len(cyc)} pts, {len(e)} arestas, polígono {'ok' if poly.is_valid else 'INVÁLIDO'}, cdt {'ok' if tris is not None else 'não'}, "
                          f"plano {np.ptp(uv[:, 0]):.2f}x{np.ptp(uv[:, 1]):.2f} mm, fora do plano {np.ptp((P - c) @ nrm):.2f} mm")
                if tris is not None and not os.environ.get('VOXELCUT_TAMPA_ANTIGA') and len(cyc) >= 24 and min(np.ptp(uv, 0)) > 1.0:   # tampas minúsculas ficam simples
                    # tampa lisa: malha fina dentro do contorno + película esticada (sem triângulos longos amassados)
                    try:
                        loc = {int(g): k for k, g in enumerate(cyc)}
                        ed = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
                        forb = [(int(x), int(y)) for x, y in ed if (min(cyc[x], cyc[y]) * nV + max(cyc[x], cyc[y])) in mesh_edges and abs(int(x) - int(y)) not in (1, len(cyc) - 1)]
                        Uv, Hn, T2 = smooth_cap(uv, (P - c) @ nrm, tris, proibidas=forb)
                        if os.environ.get('VOXELCUT_DUMP_CAP') and len(cyc) == int(os.environ['VOXELCUT_DUMP_CAP']): np.savez(os.path.join(os.environ['TEMP'], 'cap_dump.npz'), uv=uv, h=(P - c) @ nrm, tris=tris, forb=np.array(forb).reshape(-1, 2))
                        PP = np.r_[uv, Uv][T2]; o2 = (PP[:, 1, 0] - PP[:, 0, 0]) * (PP[:, 2, 1] - PP[:, 0, 1]) - (PP[:, 1, 1] - PP[:, 0, 1]) * (PP[:, 2, 0] - PP[:, 0, 0])
                        if (o2 <= 0).any() or not np.isfinite(Hn).all(): raise ValueError(f"{int((o2 <= 0).sum())} triângulos invertidos")   # trava: nunca piora a tampa
                        tris = T2
                        newv = c + Uv[:, :1] * A + Uv[:, 1:2] * B + Hn[:, None] * nrm
                        gidx = np.r_[cyc, np.arange(nextra, nextra + len(newv))]; extra_v.append(newv); nextra += len(newv)
                        nsm += 1
                        if os.environ.get("VOXELCUT_DEBUG_CAPS"):
                            from capsmooth import _orient
                            PP = np.r_[uv, Uv]; inv = sum(1 for tt in tris if _orient([tuple(q) for q in PP], tt) <= 0)
                            V3 = np.r_[P, newv]; Qd = V3[tris]; nn = np.cross(Qd[:, 1] - Qd[:, 0], Qd[:, 2] - Qd[:, 0]); nn /= np.linalg.norm(nn, axis=1)[:, None] + 1e-12
                            ee = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), 1); ff = np.tile(np.arange(len(tris)), 3)
                            kk = ee[:, 0].astype(np.int64) * 10**7 + ee[:, 1]; oo = np.argsort(kk); kk, ff = kk[oo], ff[oo]; sm = kk[1:] == kk[:-1]
                            an = np.degrees(np.arccos(np.clip((nn[ff[:-1][sm]] * nn[ff[1:][sm]]).sum(1), -1, 1)))
                            bl = np.linalg.norm(np.roll(uv, -1, 0) - uv, axis=1)
                            print(f"  DEBUG cap {names[a]}|{names[b]}: borda {len(cyc)} (aresta mediana {np.median(bl):.3f}, min {bl.min():.4f}), novos {len(Uv)}, invertidos {inv}, "
                                  f"ângulo médio {an.mean():.1f}°, 95% {np.percentile(an, 95):.1f}°, desvio da borda ao plano {np.ptp((P - c) @ nrm):.2f} mm, tamanho {np.ptp(uv[:, 0]):.1f}x{np.ptp(uv[:, 1]):.1f}")
                    except Exception as ex:
                        print(f"seam {names[a]}|{names[b]}: smooth cap skipped ({ex}) - plain cap"); gidx = None
                if tris is not None and gidx is None:
                    # a CDT chord that is already a mesh edge would make that edge shared by 3+ faces -> use a fan
                    if True:
                        chords = np.sort(np.concatenate([cyc[tris][:, [0, 1]], cyc[tris][:, [1, 2]], cyc[tris][:, [2, 0]]]), 1)
                        ring = set(map(tuple, np.sort(np.c_[cyc, np.roll(cyc, -1)], 1).tolist()))
                        inner = [c_ for c_ in map(tuple, chords.tolist()) if c_ not in ring]
                        if any((a_ * nV + b_) in mesh_edges for a_, b_ in inner):
                            tris = None
                if tris is None and True and len(cyc) >= 12 and not os.environ.get('VOXELCUT_TAMPA_ANTIGA'):
                    # costura curva demais pra achatar: tampa lisa pelo "disco" (antes era um leque de triângulos)
                    try:
                        def _forb(T0):
                            ed = np.concatenate([T0[:, [0, 1]], T0[:, [1, 2]], T0[:, [2, 0]]])
                            return [(int(x), int(y)) for x, y in ed if (min(cyc[x], cyc[y]) * nV + max(cyc[x], cyc[y])) in mesh_edges and abs(int(x) - int(y)) not in (1, len(cyc) - 1)]
                        newv, T2 = disk_cap(P, _forb)
                        if not np.isfinite(newv).all(): raise ValueError("posição inválida")
                        gidx = np.r_[cyc, np.arange(nextra, nextra + len(newv))]; extra_v.append(newv); nextra += len(newv); tris = T2; nsm += 1
                        print(f"seam {names[a]}|{names[b]}: curved seam -> smooth disk cap")
                    except Exception as ex:
                        print(f"seam {names[a]}|{names[b]}: disk cap skipped ({ex}) - fan"); tris = None; gidx = None
                if tris is None:   # fallback: fan from an extra centre vertex
                    ci = nextra; extra_v.append(c[None]); nextra += 1
                    tris = np.array([[len(cyc) + 0, k, (k + 1) % len(cyc)] for k in range(len(cyc))])
                    gidx = np.r_[cyc, ci]
                elif gidx is None:
                    gidx = cyc
                F = gidx[tris]
                # orient: part a traverses cyc as i->j, so a's cap must contain j->i
                f0 = F[0]; i0, j0 = cyc[0], cyc[1]
                s = set(zip(np.r_[f0, f0[:1]][:-1].tolist(), np.r_[f0, f0[:1]][1:].tolist()))
                # check any face containing the first seam edge
                has = [k for k, f in enumerate(F) if i0 in f and j0 in f]
                if has:
                    f = F[has[0]].tolist(); pos = f.index(int(i0))
                    if f[(pos + 1) % 3] == int(j0): F = F[:, ::-1]      # wrong way -> flip
                cap_faces[a].append(F); cap_faces[b].append(F[:, ::-1])
                # cap info for plugs (normal from a into b)
                allv = np.vstack(extra_v)
                Q = allv[F]; fn = np.cross(Q[:, 1] - Q[:, 0], Q[:, 2] - Q[:, 0]); area = np.linalg.norm(fn, axis=1).sum() / 2
                N = fn.sum(0); N /= np.linalg.norm(N) + 1e-12
                gv = allv[np.unique(F)]; o = gv.mean(0)
                A2 = np.cross(N, [0, 0, 1] if abs(N[2]) < 0.9 else [1, 0, 0]); A2 /= np.linalg.norm(A2); B2 = np.cross(N, A2)
                u, inv = np.unique(F, return_inverse=True)
                d = (allv[u] - o) @ N
                if b == VOID: print(f"closed the hole left by the deleted area on {names[a]} ({area:.1f} mm2)"); continue
                caps_json[names[a]].append(dict(normal=N.tolist(), origin=o.tolist(), A=A2.tolist(), B=B2.tolist(),
                                                 uv=np.c_[(allv[u] - o) @ A2, (allv[u] - o) @ B2].tolist(), tris=inv.reshape(-1, 3).tolist(),
                                                 area=float(area), dev=[float(d.min()), float(d.max())], h=np.round(d, 4).tolist(), target=names[b]))
                print(f"seam {names[a]} -> {names[b]}: {len(cyc)} verts, cap {area:.1f} mm2")
allv = np.vstack(extra_v)
parts = []
for k in range(ng):
    F = np.vstack([t[seg == k]] + cap_faces[k]) if cap_faces[k] else t[seg == k]
    u, inv = np.unique(F, return_inverse=True); Fk = inv.reshape(-1, 3)
    e = np.sort(np.concatenate([Fk[:, [0, 1]], Fk[:, [1, 2]], Fk[:, [2, 0]]]), 1)
    _, cnt = np.unique(e[:, 0].astype(np.int64) * 10**8 + e[:, 1], return_counts=True)
    np.save(f"{wd}/part_{k}_v.npy", allv[u]); np.save(f"{wd}/part_{k}_t.npy", Fk)
    parts.append(dict(name=names[k], tris=int(len(Fk)), open_edges=int((cnt == 1).sum()), nonmanifold=int((cnt > 2).sum()), cap_tris=int(sum(len(x) for x in cap_faces[k]))))
    print("PART", parts[-1])
json.dump(parts, open(f"{wd}/parts.json", "w"), indent=1)
json.dump(caps_json, open(f"{wd}/caps.json", "w"))
print(f"smooth caps: {nsm}")
if bad: print("WARNING", bad, "non-simple seam(s)")
