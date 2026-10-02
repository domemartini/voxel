"""Final stage (manifold3d): joints between the pieces, binary STLs and a light preview for the viewer.
Joint types (config "joint"):
  pins   - 1 or 2 round locating pins (chamfered tip) on the upper piece, matching holes (+clearance) in the
           piece below; pins sit well inside the cut face (wall margin from the edge)
  key    - the cut face shape, pulled in from the edge by a wall and rounded (no jagged seam), as a smooth key
  glue   - flat faces only
Every hole is checked against the piece that receives it: if it would break through, the pin gets shorter
or the joint falls back to glue.
usage: python finish.py <workdir>
needs: config.json caps.json parts.json part_<k>_v/t.npy info.json
writes: out_dir/<name>.stl, workdir/pieces.bin + pieces.json (preview), workdir/joints.json"""
import sys, os, json, time, struct, numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # módulos do motor (o Python embutido não põe a pasta do script no caminho)
import manifold3d as mf
import shapely
import shapely.affinity
from shapely.geometry import Polygon, Point, MultiPolygon
from shapely.ops import unary_union, polylabel

wd = sys.argv[1]
cfg = json.load(open(f"{wd}/config.json", encoding="utf-8")); caps = json.load(open(f"{wd}/caps.json", encoding="utf-8"))
info = json.load(open(f"{wd}/info.json")); parts = json.load(open(f"{wd}/parts.json", encoding="utf-8"))
OUT = cfg["out_dir"]; os.makedirs(OUT, exist_ok=True)
if os.path.exists(f"{OUT}/Pinos.stl"): os.remove(f"{OUT}/Pinos.stl")
SCALE = cfg.get("export_scale", info.get("export_scale", 1.0))
J = cfg.get("joints") or {}
_legacy = cfg.get("joint", "pins")                            # old configs: pins / key / glue
STEP = bool(J.get("step", _legacy == "key"))                  # recess ("rebaixo") following the cut
STEP_D = float(J.get("step_depth", 2.0)) / SCALE
PIN_TYPE = J.get("pin_type", "none" if _legacy in ("key", "glue") else "round")   # none / round / square / hex / cone / center
PIN_COUNT = J.get("pin_count", "auto")
PIN_OFF = False                                                # "sem pino" só neste corte (escolha por corte: joints.cuts)
PIN_D = float(J.get("pin_d", cfg.get("pin_d", 0)) or 0) / SCALE      # 0 = automatic
PIN_L = float(J.get("pin_len", cfg.get("pin_len", 4.0))) / SCALE
LOOSE = bool(J.get("loose", False))                            # dowel printed apart, holes in both pieces
CLEAR = float(J.get("clear", cfg.get("clear", 0.15))) / SCALE
WALL = float(J.get("wall", cfg.get("wall", 1.2))) / SCALE
ROUND = float(J.get("round", 1.5)) / SCALE                     # rounding of the recess outline
CH = 0.4 / SCALE                                               # chamfer at tips
MIN_AREA = float(cfg.get("plug_min_area", 8)) / SCALE ** 2
MAG_R = float(J.get("mag_d", 6)) / 2 / SCALE                   # ímã de neodímio (pin_type "magnet"): furo dos dois lados
MAG_H = float(J.get("mag_h", 2)) / SCALE
LABEL = bool(J.get("etiqueta", True))                          # número do corte gravado nas duas faces (some depois de montar)
names = [f["name"] for f in cfg["figures"]] + [cfg.get("base_name", "Base")]
caps_names = [p["name"] for p in parts]
t00 = time.time()
mf.set_circular_segments(40)


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


def to_m(v, t):
    mesh = mf.Mesh(vert_properties=np.ascontiguousarray(v, np.float32), tri_verts=np.ascontiguousarray(t, np.uint32))
    m = mf.Manifold(mesh)
    if m.status() != mf.Error.NoError:
        mesh.merge(); m = mf.Manifold(mesh)
    if m.status() != mf.Error.NoError:                                  # repair: split touching sheets, close pinholes
        v2, t2 = split_nonmanifold(np.asarray(v, float), np.asarray(t, np.int64))
        v2, t2 = fill_holes(v2, t2)
        m2 = mf.Manifold(mf.Mesh(vert_properties=np.ascontiguousarray(v2, np.float32), tri_verts=np.ascontiguousarray(t2, np.uint32)))
        if m2.status() == mf.Error.NoError: m = m2
    return m


def arrays(m):
    me = m.to_mesh(); return np.asarray(me.vert_properties)[:, :3].astype(np.float64), np.asarray(me.tri_verts).astype(np.int64)


def union(lst):
    lst = [x for x in lst if x is not None]
    return None if not lst else (lst[0] if len(lst) == 1 else mf.Manifold.batch_boolean(lst, mf.OpType.Add))


def _varios_pedacos(m):
    """True se a malha tem mais de um pedaço solto. Conta por conectividade (rápido); decompose() é caro em malha grande."""
    me = m.to_mesh(); T = np.asarray(me.tri_verts).astype(np.int64)
    if not len(T): return False
    n = len(me.vert_properties)
    g = sp.coo_matrix((np.ones(len(T) * 2), (np.r_[T[:, 0], T[:, 1]], np.r_[T[:, 1], T[:, 2]])), shape=(n, n))
    return connected_components(g, directed=False)[0] - int((np.bincount(T.ravel(), minlength=n) == 0).sum()) > 1


def keep_main(m, frac=0.004):
    if not _varios_pedacos(m): return m, 0
    comps = m.decompose()
    if len(comps) <= 1: return m, 0
    vol = np.array([c.volume() for c in comps]); keep = [c for c, x in zip(comps, vol) if x > frac * vol.sum()]
    return union(keep), len(comps) - len(keep)


def write_stl(path, v, t):
    tri = (v[t] * SCALE).astype(np.float32); n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-20
    rec = np.zeros(len(t), np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])); rec["n"] = n; rec["v"] = tri
    with open(path, "wb") as f:
        f.write(b"Cortador Voxel".ljust(80, b" ")); f.write(struct.pack("<I", len(t))); f.write(rec.tobytes())


def polys(g):
    return [] if g is None or g.is_empty else (list(g.geoms) if hasattr(g, "geoms") else [g])


def cap_shape(g):
    """2D shape of a cut face (in its own plane frame)."""
    uv = np.array(g["uv"]); tris = np.array(g["tris"])
    tp = [Polygon(uv[t]) for t in tris if np.isfinite(uv[t]).all()]
    return unary_union([x for x in tp if x.area > 1e-9]).buffer(0.001 / SCALE)


def cs_of(geom):
    """shapely (Multi)Polygon -> manifold CrossSection."""
    rings = []
    for pg in polys(geom):
        ext = np.asarray(pg.exterior.coords)[:-1]
        if Polygon(ext).exterior.is_ccw is False: ext = ext[::-1]
        rings.append(ext)
        for hole in pg.interiors:
            h = np.asarray(hole.coords)[:-1]
            if Polygon(h).exterior.is_ccw: h = h[::-1]
            rings.append(h)
    return mf.CrossSection(rings, mf.FillRule.Positive) if rings else None


def prism(cs, frame, z0, z1, tip=0.0):
    """extrude a cross-section along the cut normal from z0 to z1, with a chamfered tip of height `tip`."""
    if cs is None or cs.area() < 1e-6 or z1 - z0 <= tip: return None
    body = mf.Manifold.extrude(cs, z1 - z0 - tip).translate((0, 0, z0))
    if tip > 0:
        c = cs.bounds(); cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2          # scale the tip about its centre
        csc = cs.translate((-cx, -cy)); size = max(c[2] - c[0], c[3] - c[1])
        k = max(0.2, 1 - 2 * tip / max(size, 1e-6))
        top = mf.Manifold.extrude(csc, tip, scale_top=(k, k)).translate((cx, cy, z1 - tip))
        body = body + top
    return body.transform(frame)


def pin_shape(c, r, grow=0.0, angle=0.0):
    """2D outline of one pin (grown by the clearance for the hole)."""
    x, y = c; rr = r + grow
    if PIN_TYPE == "square":
        h = 0.8 * rr                                           # side ~ 1.6 r
        sq = Polygon([(-h, -h), (h, -h), (h, h), (-h, h)])
        return shapely.affinity.translate(shapely.affinity.rotate(sq, angle), x, y)
    if PIN_TYPE == "hex":
        a_ = np.radians(angle) + np.arange(6) * np.pi / 3
        return Polygon(np.c_[x + rr * np.cos(a_), y + rr * np.sin(a_)])
    return Point(x, y).buffer(rr, quad_segs=10)


def pin_layout(S):
    """centres + radius of the pins inside region S (already inset from the edge)."""
    if S is None or S.is_empty: return [], 0
    big = max(polys(S), key=lambda x: x.area)
    c0 = polylabel(big, tolerance=0.05 / SCALE); rin = big.exterior.distance(c0)
    for h in big.interiors: rin = min(rin, h.distance(c0))
    if PIN_TYPE == "center":                                   # estilo dos kits: um pino grande no meio do corte (ombro, pescoço)
        r = PIN_D / 2 if PIN_D else float(np.clip(0.55 * rin, 1.2 / SCALE, 10.0 / SCALE))
        return [(c0.x, c0.y)], r
    if PIN_TYPE == "magnet":                                   # o ímã tem tamanho fixo: sem espaço, sem ímã
        r = MAG_R; inner = S.buffer(-(r + CLEAR + 0.4 / SCALE))
        if inner.is_empty: return [], r
        want = {"auto": 2 if S.area > 500 / SCALE ** 2 else 1, "1": 1, "2": 2, "3": 3}.get(str(PIN_COUNT), 1)
    else:
        r = PIN_D / 2 if PIN_D else float(np.clip(0.4 * rin, 1.0 / SCALE, 3.0 / SCALE))
        inner = S.buffer(-(r + CLEAR + 0.4 / SCALE))
        if inner.is_empty:
            if PIN_D: return [], r
            r = 0.8 / SCALE; inner = S.buffer(-(r + CLEAR + 0.2 / SCALE))
            if inner.is_empty: return [], r
        want = {"auto": 3 if S.area > 600 / SCALE ** 2 else 2, "1": 1, "2": 2, "3": 3}.get(str(PIN_COUNT), 2)
    ib = max(polys(inner), key=lambda x: x.area)
    p1 = polylabel(ib, tolerance=0.05 / SCALE)
    if not ib.contains(p1): p1 = ib.representative_point()
    ctr = np.array([p1.x, p1.y])
    if want == 1: return [tuple(ctr)], r
    xs = np.linspace(inner.bounds[0], inner.bounds[2], 50); ys = np.linspace(inner.bounds[1], inner.bounds[3], 50)
    grid = np.array([(x, y) for x in xs for y in ys if inner.contains(Point(x, y))])
    if not len(grid): return [tuple(ctr)], r
    # 2+ pins spread out (they stop the piece from turning), then pulled a bit toward the middle
    first = grid[np.argmax(np.linalg.norm(grid - ctr, axis=1))]
    second = grid[np.argmax(np.linalg.norm(grid - first, axis=1))]
    if np.linalg.norm(first - second) < 2 * r + 2.0 / SCALE: return [tuple(ctr)], r
    pts = [first, second]
    while len(pts) < want:
        dm = np.min([np.linalg.norm(grid - q, axis=1) for q in pts], 0); j = int(np.argmax(dm))
        if dm[j] < 2 * r + 2.0 / SCALE: break
        pts.append(grid[j])
    pts = [q + 0.25 * (ctr - q) for q in pts]
    pts = [q for q in pts if inner.contains(Point(*q))] or [ctr]
    return [tuple(q) for q in pts], r


def step_shape(S, wall=None):
    k = S.buffer(-(WALL if wall is None else wall))
    if ROUND > 0: k = k.buffer(-ROUND).buffer(ROUND)
    k = k.simplify(0.05 / SCALE)
    return None if k.is_empty or k.area < 4 / SCALE ** 2 else k


MINW = 0.8 / SCALE                                             # minimum wall left around every pocket/hole


def fits(sec, frame, z0, z1, target, source=None, z_ini=None):
    """would this pocket/hole (grown by a minimum wall) stay inside the model? It may only cut into the target
    piece (and the source piece it starts from) - never open a window to the outside."""
    # a parede mínima só vale DENTRO da peça que recebe o furo, abaixo do nível do corte (z_ini). Na altura do próprio corte,
    # em volta da peça, o chão pode ficar uns décimos abaixo: ali é ar, o furo fica coberto pela peça - e isso reprovava
    # todo encaixe de pata pequena
    chk = prism(cs_of(sec.buffer(MINW)), frame, z0 if z_ini is None else max(z0, z_ini), z1)
    if chk is None: return False
    out = chk - orig[target]
    if source is not None: out = out - orig[source]
    if os.environ.get("VOXELCUT_DEBUG_JUNTA") and z_ini is not None: print(f"        fits: chk {chk.volume() * SCALE ** 3:.2f} mm3, fora {out.volume() * SCALE ** 3:.3f} mm3, z {z0:.2f}..{z1:.2f}")
    return out.volume() / max(chk.volume(), 1e-9) < 0.002


# ---------- pieces
P = []; RAW = {}
for k in range(len(parts)):
    rv, rt = np.load(f"{wd}/part_{k}_v.npy"), np.load(f"{wd}/part_{k}_t.npy")
    m = to_m(rv, rt)
    if m.status() != mf.Error.NoError or m.is_empty():
        print(f"WARNING piece {names[k]}: mesh could not be closed - exported as it is, without joints")
        RAW[k] = (rv, rt); m = mf.Manifold()
    P.append(m)
orig = list(P)
SIDES = J.get("sides") or {}                                  # {"A|B": name of the piece that gets the RECESS} or "auto"


def local_z(hts, c, rr, lo, hi):
    """altura (mín, máx) da superfície do corte em volta do pino (corte curvo: o pino nasce da superfície ali, não do ponto mais alto)"""
    if hts is None: return lo, hi
    uv, h = hts; cx, cy = (c.x, c.y) if hasattr(c, "x") else (c[0], c[1]); d = np.hypot(uv[:, 0] - cx, uv[:, 1] - cy); m = d <= 1.6 * rr
    if m.sum() < 3: m = d <= np.partition(d, min(5, len(d) - 1))[min(5, len(d) - 1)]
    return float(h[m].min()), float(h[m].max())


def plan(male, female, frame, lo, hi, S, curvo=False, hts=None):
    """joint where `male` gets the boss + pins and `female` gets the pocket + holes. Nothing is built yet.
    curvo: the cut face bends more than the step is deep -> no step (a flat-topped boss would stick out as a block)"""
    pl = dict(male=male, female=female, frame=frame, lo=lo, hi=hi, K=None, D=0, pins=[], mags=[], score=0.0, S=S, hts=hts)
    top = hi; region = S.buffer(-WALL)
    if STEP and not curvo and PIN_TYPE != "center":             # o pino central já alinha: sem rebaixo
        for extra in (0.0, 0.8, 1.6, 2.4):                       # deeper inset (smaller boss, thicker wall) until it fits
            Kt = step_shape(S, WALL + extra / SCALE); D = STEP_D
            while Kt is not None and D >= 0.6 / SCALE and not fits(Kt.buffer(CLEAR), frame, lo - 0.4 / SCALE, hi + D + CLEAR, female, male, z_ini=hi + 0.3 / SCALE): D *= 0.7
            if os.environ.get("VOXELCUT_DEBUG_JUNTA"): print(f"      [rebaixo] S {S.area * SCALE ** 2:.1f} mm2, boss {0 if Kt is None else Kt.area * SCALE ** 2:.1f} mm2, D final {D * SCALE:.2f} mm (lo {lo:.2f} hi {hi:.2f})")
            if Kt is not None and D >= 0.6 / SCALE:
                pl.update(K=Kt, D=D); top = hi + D; region = Kt.buffer(-0.8 / SCALE); break
    if PIN_TYPE == "magnet" and not PIN_OFF:                   # furo pro ímã nas duas peças, na mesma posição
        cen, r = pin_layout(region); Lm = MAG_H + 0.2 / SCALE
        for c in cen:
            fshape = Point(*c).buffer(r + CLEAR, quad_segs=12)
            zlo, ztop = (top, top) if pl["K"] is not None else local_z(hts, c, r, lo, hi)
            if ztop - zlo > 1.0 / SCALE: continue                # face torta demais ali: o ímã não assenta
            zf = top + CLEAR if pl["K"] is not None else ztop     # fundo do rebaixo (ou a própria face) na peça de cima
            if fits(fshape, frame, zlo - Lm, ztop + 0.05 / SCALE, male, female) and \
               fits(fshape, frame, zlo - 0.05 / SCALE, zf + Lm, female, male, z_ini=zf + 0.3 / SCALE):
                pl["mags"].append(dict(f=fshape, r=r, a=zlo - Lm, b=ztop + 0.05 / SCALE, c=zlo - 0.05 / SCALE, d=zf + Lm))
    elif PIN_TYPE != "none" and not PIN_OFF:
        cen, r = pin_layout(region)
        ang = float(np.degrees(np.arctan2(cen[1][1] - cen[0][1], cen[1][0] - cen[0][0]))) if len(cen) >= 2 else 0.0
        for c in cen:
            for rr in ([r] if PIN_D else [r, r * 0.85, r * 0.72, 0.7 / SCALE]):   # thinner pin before giving up (min 1.4 mm)
                if rr < 0.7 / SCALE - 1e-9 or rr > r + 1e-9: continue
                mshape = pin_shape(c, rr, 0, ang); fshape = pin_shape(c, rr, CLEAR, ang)
                zlo, ztop = (lo, top) if pl["K"] is not None else local_z(hts, c, rr, lo, hi)
                if LOOSE:                                             # separate dowel, half in each piece
                    La = Lb = PIN_L / 2
                    while La >= 1.0 / SCALE and not fits(fshape, frame, zlo - La - 0.3 / SCALE, ztop + 0.05 / SCALE, male, female): La *= 0.7
                    while Lb >= 1.0 / SCALE and not fits(fshape, frame, zlo - 0.4 / SCALE, ztop + Lb + 0.3 / SCALE, female, male, z_ini=ztop + 0.3 / SCALE): Lb *= 0.7
                    if La >= 1.0 / SCALE and Lb >= 1.0 / SCALE:
                        pl["pins"].append(dict(m=mshape, f=fshape, r=rr, La=La, Lb=Lb, lo=zlo, top=ztop)); break
                    continue
                L = max(PIN_L, 1.2 * rr) if PIN_TYPE == "center" else PIN_L
                while L >= 1.2 / SCALE and not fits(fshape, frame, zlo - 0.4 / SCALE, ztop + L + 0.4 / SCALE, female, male, z_ini=ztop + 0.3 / SCALE): L *= 0.7
                if L >= 1.2 / SCALE:
                    pl["pins"].append(dict(m=mshape, f=fshape, r=rr, L=L, lo=zlo, top=ztop)); break
    pl["top"] = top
    # how good is it: area x depth of the recess + pins (length x section)
    pl["score"] = (pl["K"].area * pl["D"] if pl["K"] is not None else 0) + sum(q["m"].area * q.get("L", q.get("Lb", 0)) for q in pl["pins"]) + \
                  sum(q["f"].area * MAG_H for q in pl["mags"])
    return pl


def commit(pl, rec):
    male, female, frame, lo, top = pl["male"], pl["female"], pl["frame"], pl["lo"], pl["top"]
    if pl["K"] is not None:
        K, D, hi = pl["K"], pl["D"], pl["hi"]
        adds[male].append(prism(cs_of(K), frame, lo - 1.0 / SCALE, hi + D, tip=min(0.3 / SCALE, D / 3)))
        holes[female].append(prism(cs_of(K.buffer(CLEAR, join_style="round")), frame, lo - 0.4 / SCALE, hi + D + CLEAR))
        rec["step"] = dict(depth_mm=round(float(D * SCALE), 1), area_mm2=round(float(K.area * SCALE ** 2), 1))
    for q in pl["mags"]:
        holes[male].append(prism(cs_of(q["f"]), frame, q["a"], q["b"])); holes[female].append(prism(cs_of(q["f"]), frame, q["c"], q["d"]))
        rec.setdefault("magnets", []).append(dict(d_mm=round(float(2 * MAG_R * SCALE), 1), h_mm=round(float(MAG_H * SCALE), 1)))
    for q in pl["pins"]:
        lo, top = q.get("lo", pl["lo"]), q.get("top", pl["top"])           # altura local do corte no pino
        if LOOSE:
            holes[male].append(prism(cs_of(q["f"]), frame, lo - q["La"] - 0.3 / SCALE, top + 0.05 / SCALE))
            holes[female].append(prism(cs_of(q["f"]), frame, lo - 0.4 / SCALE, top + q["Lb"] + 0.3 / SCALE))
            Ltot = q["La"] + q["Lb"] + (top - lo); dowels.append((q["m"], Ltot))
            rec["pins"].append(dict(type=PIN_TYPE, d_mm=round(float(2 * q["r"] * SCALE), 1), len_mm=round(float(Ltot * SCALE), 1), loose=True))
            continue
        L = q["L"]; tip = 0.45 * L if PIN_TYPE == "cone" else min(CH, L / 3)
        adds[male].append(prism(cs_of(q["m"]), frame, lo - 1.0 / SCALE, top + L, tip=tip))
        holes[female].append(prism(cs_of(q["f"]), frame, lo - 0.4 / SCALE, top + L + 0.4 / SCALE, tip=tip if PIN_TYPE == "cone" else 0))
        rec["pins"].append(dict(type=PIN_TYPE, d_mm=round(float(2 * q["r"] * SCALE), 1), len_mm=round(float(L * SCALE), 1)))


def dovetail(male, female, frame, lo, hi, S):
    """rabo de andorinha: uma lingueta em trapézio atravessa a face do corte (estreita na face, larga no fundo); a outra peça
    ganha o canal. Entra deslizando por uma ponta e não sai puxando. Só em corte plano, e o canal precisa sair pro ar em pelo
    menos uma ponta (se a outra peça for mais larga que o corte nas duas pontas, não tem por onde entrar)."""
    dbg = os.environ.get("VOXELCUT_DEBUG_JUNTA")
    if dbg: print(f"      [rabo] face {(hi - lo) * SCALE:.2f} mm de altura")
    if hi - lo > 1.5 / SCALE: return None
    mrr = S.minimum_rotated_rectangle; xy = np.asarray(mrr.exterior.coords)[:4]; c = xy.mean(0)
    e1, e2 = xy[1] - xy[0], xy[2] - xy[1]
    eixos = [(e1, e2), (e2, e1)] if np.linalg.norm(e1) >= np.linalg.norm(e2) else [(e2, e1), (e1, e2)]   # primeiro deslizando no comprido
    F = np.asarray(frame, float); Lx = 4 * float(max(np.linalg.norm(e1), np.linalg.norm(e2))) + 10 / SCALE
    for lng, shr in eixos:
        d = lng / np.linalg.norm(lng); perp = np.array([-d[1], d[0]]); Wd = float(np.linalg.norm(shr)) * SCALE
        Ml = np.array([[perp[0], 0, d[0], c[0] - Lx / 2 * d[0]], [perp[1], 0, d[1], c[1] - Lx / 2 * d[1]], [0, 1, 0, 0]])
        M = np.c_[F[:, :3] @ Ml[:, :3], F[:, :3] @ Ml[:, 3] + F[:, 3]]
        ang = float(np.degrees(np.arctan2(d[1], d[0])))
        for k in (1.0, 0.75, 0.55):
            w0 = float(np.clip(0.3 * Wd, 3.0, 12.0)) * k / SCALE; Dd = float(np.clip(0.3 * Wd, 2.0, 5.0)) * k / SCALE; w1 = w0 + Dd
            if (w1 + 2 * WALL) * SCALE > Wd: continue
            faixa = shapely.affinity.translate(shapely.affinity.rotate(Polygon([(-Lx, -w1 / 2 - CLEAR), (Lx, -w1 / 2 - CLEAR), (Lx, w1 / 2 + CLEAR), (-Lx, w1 / 2 + CLEAR)]),
                                                                       ang, origin=(0, 0)), c[0], c[1])
            # as duas pontas: logo depois da borda do corte, na faixa do canal, tem peça de baixo (fechado) ou ar (aberto)?
            abertas = []
            for sgn in (1, -1):
                meio = shapely.affinity.translate(shapely.affinity.rotate(Polygon([(0, -Lx), (sgn * Lx, -Lx), (sgn * Lx, Lx), (0, Lx)]), ang, origin=(0, 0)), c[0], c[1])
                anel = S.buffer(2.0 / SCALE).difference(S.buffer(0.3 / SCALE)).intersection(faixa).intersection(meio)
                E = prism(cs_of(anel), frame, hi + 0.3 / SCALE, hi + Dd) if anel.area > 0 else None
                if E is None or E.volume() <= 0: continue
                if (E ^ orig[female]).volume() / E.volume() < 0.05: abertas.append(sgn)
            if dbg: print(f"      [rabo] eixo {ang:.0f}°, k {k}: largura {w0 * SCALE:.1f}, fundo {Dd * SCALE:.1f}, pontas abertas {abertas}")
            if not abertas: break                                # este eixo não tem por onde entrar: tenta o outro
            z0 = lo - 0.6 / SCALE
            trap = Polygon([(-w0 / 2, z0), (w0 / 2, z0), (w0 / 2, hi), (w1 / 2, hi + Dd), (-w1 / 2, hi + Dd), (-w0 / 2, hi)])
            gap = trap.buffer(CLEAR, join_style="mitre")
            tongue = mf.Manifold.extrude(cs_of(trap), Lx).transform(M) ^ prism(cs_of(S), frame, z0 - 0.1 / SCALE, hi + Dd + 0.1 / SCALE)
            slot_all = mf.Manifold.extrude(cs_of(gap), Lx).transform(M)
            slot = slot_all ^ prism(cs_of(S.buffer(1.0 / SCALE)), frame, lo - 0.4 / SCALE, hi + Dd + CLEAR + 0.1 / SCALE)
            dentro = slot_all ^ prism(cs_of(S.buffer(-0.05 / SCALE)), frame, hi + 0.05 / SCALE, hi + Dd + CLEAR + 0.1 / SCALE)
            fora = dentro - orig[female]
            if dbg: print(f"      [rabo]   canal {dentro.volume() * SCALE ** 3:.0f} mm3, fora {fora.volume() * SCALE ** 3:.1f} mm3")
            if dentro.volume() > 0 and fora.volume() / dentro.volume() < 0.01:
                return dict(tongue=tongue, slot=slot, faixa=faixa, w_mm=round(w0 * SCALE, 1), d_mm=round(Dd * SCALE, 1), pontas=len(abertas))
    return None


SEG7 = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}


def texto(s, h):
    """número em 7 segmentos (sem fonte): traços com espessura que imprime bem, centrado em (0,0)"""
    w = 0.55 * h; e = max(0.17 * h, 0.5 / SCALE); gap = 0.3 * h; P_ = {"a": ((0, h), (w, h)), "b": ((w, h), (w, h / 2)), "c": ((w, h / 2), (w, 0)), "d": ((0, 0), (w, 0)),
                                                                     "e": ((0, 0), (0, h / 2)), "f": ((0, h / 2), (0, h)), "g": ((0, h / 2), (w, h / 2))}
    from shapely.geometry import LineString
    out = []
    for i, ch in enumerate(s):
        x0 = i * (w + gap)
        out += [shapely.affinity.translate(LineString(P_[sg]).buffer(e / 2, cap_style="square"), x0, 0) for sg in SEG7.get(ch, "")]
    g = unary_union(out); b = g.bounds
    return shapely.affinity.translate(g, -(b[0] + b[2]) / 2, -(b[1] + b[3]) / 2)


def etiqueta(n, pl, rec, livre):
    """grava o número do corte nas duas faces, onde não tem pino, ímã nem lingueta (fica escondido depois de montar)"""
    male, female, frame, hts = pl["male"], pl["female"], pl["frame"], pl.get("hts")
    dbg = os.environ.get("VOXELCUT_DEBUG_JUNTA")
    if livre is None or livre.is_empty:
        if dbg: print(f"      [número {n}] sem espaço livre")
        return
    big = max(polys(livre), key=lambda x: x.area)
    if dbg: print(f"      [número {n}] área livre {big.area * SCALE ** 2:.0f} mm2, bounds {np.round(np.array(big.bounds) * SCALE, 1).tolist()}")
    # lugares candidatos: o ponto mais "fundo" da área livre e uma grade, do mais longe da borda pro mais perto
    b0 = big.bounds; xs = np.linspace(b0[0], b0[2], 14); ys = np.linspace(b0[1], b0[3], 14)
    cand = [polylabel(big, tolerance=0.05 / SCALE)] + [Point(x, y) for x in xs for y in ys if big.contains(Point(x, y))]
    cand.sort(key=lambda q: -big.exterior.distance(q)); cand = cand[:60]
    achou = None
    for hmm in (6.0, 5.0, 4.0, 3.2, 2.6, 2.3):
        T0 = texto(str(n), hmm / SCALE); T0b = T0.buffer(0.3 / SCALE)
        for pt in cand:
            if big.contains(shapely.affinity.translate(T0b, pt.x, pt.y)): achou = (pt, shapely.affinity.translate(T0, pt.x, pt.y)); break
        if achou: break
    if not achou:
        if dbg: print(f"      [número {n}] não coube")
        return
    pt, T = achou
    if pl["K"] is not None: zlo = zhi = pl["top"]
    else:
        zlo, zhi = local_z(hts, pt, 3 / SCALE, pl["lo"], pl["hi"])
        if zhi - zlo > 1.6 / SCALE:                            # face torta ali: pula
            if dbg: print(f"      [número {n}] face torta ({(zhi - zlo) * SCALE:.1f} mm)")
            return
    fundo = pl["top"] + CLEAR if pl["K"] is not None else zhi
    Tm = shapely.affinity.scale(T, -1, 1, origin=pt)           # do outro lado, espelhado (lê certo olhando a face)
    holes[male].append(prism(cs_of(T), frame, zlo - 0.4 / SCALE, zhi + 0.3 / SCALE))
    holes[female].append(prism(cs_of(Tm), frame, (zlo if pl["K"] is None else fundo) - 0.3 / SCALE, fundo + 0.4 / SCALE))
    rec["n"] = n


adds = {k: [] for k in range(len(P))}; holes = {k: [] for k in range(len(P))}; report = []; dowels = []
for k, nm in enumerate(caps_names):
    for g in caps.get(nm, []):
        tgt = caps_names.index(g["target"]) if g.get("target") in caps_names else len(caps_names) - 1
        N, O, A, B = (np.array(g[x], float) for x in ("normal", "origin", "A", "B"))
        lo, hi = g["dev"]
        S = cap_shape(g)
        opc = str(((J.get("cuts") or {}).get("|".join(sorted([names[k], names[tgt]]))) or {}).get("pins", "auto"))   # escolha do usuário pra este corte: auto / 0 / 1 / 2 / 3 / colar
        PIN_OFF = opc == "0"; PIN_COUNT = J.get("pin_count", "auto") if opc in ("auto", "0", "colar") else opc
        rec = dict(piece=names[k], to=names[tgt], area_mm2=round(S.area * SCALE ** 2, 1), step=False, pins=[], recess_in=None)
        n_corte = len(report) + 1
        hts = (np.asarray(g["uv"], float), np.asarray(g["h"], float)) if g.get("h") is not None else None
        frame_f = np.c_[A, B, N, O]
        so_cola = dict(male=k, female=tgt, frame=frame_f, lo=lo, hi=hi, K=None, top=hi, hts=hts)
        if k in RAW or tgt in RAW:
            report.append(rec); print(f"   {names[k]} | {names[tgt]}: glue (piece could not be repaired)"); continue
        if opc == "colar" or S.area < MIN_AREA or (not STEP and (PIN_TYPE == "none" or PIN_OFF) and opc != "rabo"):
            if LABEL and S.area >= MIN_AREA: etiqueta(n_corte, so_cola, rec, S.buffer(-WALL))
            report.append(rec); print(f"   {names[k]} | {names[tgt]}: glue" + (" (você escolheu só colar)" if opc == "colar" else f" ({rec['area_mm2']} mm2)")); continue
        if opc == "rabo":                                       # rabo de andorinha neste corte (no lugar de rebaixo e pinos)
            want = SIDES.get("|".join(sorted([names[k], names[tgt]])), "auto")
            femea = tgt if want == names[tgt] else k if want == names[k] else (tgt if orig[tgt].volume() >= orig[k].volume() else k)
            args = (k, tgt, frame_f, lo, hi, S) if femea == tgt else (tgt, k, np.c_[A, -B, -N, O], -hi, -lo, shapely.affinity.scale(S, 1, -1, origin=(0, 0)))
            dv = dovetail(*args)
            if dv is not None:
                adds[args[0]].append(dv["tongue"]); holes[args[1]].append(dv["slot"])
                rec["dovetail"] = dict(w_mm=dv["w_mm"], depth_mm=dv["d_mm"]); rec["recess_in"] = names[args[1]]
                if LABEL:
                    pl_ = dict(male=args[0], female=args[1], frame=args[2], lo=args[3], hi=args[4], K=None, top=args[4], hts=None)
                    etiqueta(n_corte, pl_, rec, args[5].buffer(-WALL).difference(dv["faixa"].buffer(0.8 / SCALE)))
                report.append(rec); print(f"   {names[k]} | {names[tgt]}: dovetail {dv['w_mm']} x {dv['d_mm']} mm (slot in {names[args[1]]})"); continue
            print(f"   {names[k]} | {names[tgt]}: no room for a dovetail (or the cut is not flat) - normal joint")
        # quanto a tampa sobe e desce dentro da área do rebaixo (tampa curva -> sem rebaixo, só pinos)
        curvo = False
        if STEP and g.get("h") is not None:
            K0 = step_shape(S, WALL); hh = np.asarray(g["h"], float); uvv = np.asarray(g["uv"], float)
            if K0 is not None and not K0.is_empty:
                dentro = shapely.contains_xy(K0, uvv[:, 0], uvv[:, 1])
                faixa = float(np.ptp(hh[dentro])) if dentro.sum() > 3 else float(hi - lo)
                curvo = faixa > 0.75 * STEP_D
                if curvo: print(f"   {names[k]} | {names[tgt]}: curved cut ({faixa * SCALE:.1f} mm) - pins only, no step")
        hts = (np.asarray(g["uv"], float), np.asarray(g["h"], float)) if g.get("h") is not None else None
        fwd = (k, tgt, np.c_[A, B, N, O], lo, hi, S, curvo, hts)      # recess in the other piece (boss + pins on this one)
        S_r = shapely.affinity.scale(S, 1, -1, origin=(0, 0))    # seen from the other side: flip N and B (still right-handed)
        rev = (tgt, k, np.c_[A, -B, -N, O], -hi, -lo, S_r, curvo, None if hts is None else (hts[0] * [1, -1], -hts[1]))
        key = "|".join(sorted([names[k], names[tgt]]))
        want = SIDES.get(key, "auto")
        if want == names[tgt]: pl = plan(*fwd)
        elif want == names[k]: pl = plan(*rev)
        else:
            p1 = plan(*fwd); p2 = plan(*rev)
            # the recess goes into the BIGGER piece (more material: body, base) unless it is clearly worse there
            big, small = (p1, p2) if orig[tgt].volume() >= orig[k].volume() else (p2, p1)
            pl = big if big["score"] >= 0.7 * small["score"] else small
        commit(pl, rec); rec["recess_in"] = names[pl["female"]]
        if LABEL:
            livre = pl["K"].buffer(-0.6 / SCALE) if pl["K"] is not None else pl["S"].buffer(-WALL)
            ocup = [q["m"].buffer(0.6 / SCALE) for q in pl["pins"]] + [q["f"].buffer(0.6 / SCALE) for q in pl["mags"]]
            etiqueta(n_corte, pl, rec, livre.difference(unary_union(ocup)) if ocup else livre)
        report.append(rec)
        what = (["recess %.1f mm" % rec["step"]["depth_mm"]] if rec["step"] else []) + \
               ([f"{len(rec['pins'])} pin(s) {PIN_TYPE} d={rec['pins'][0]['d_mm']} L={rec['pins'][0]['len_mm']}"] if rec["pins"] else []) +                ([f"{len(rec['magnets'])} magnet(s) {rec['magnets'][0]['d_mm']}x{rec['magnets'][0]['h_mm']}"] if rec.get("magnets") else []) +                ([f"label {rec['n']}"] if rec.get("n") else [])
        print(f"   {names[k]} | {names[tgt]}: " + ((" + ".join(what) + f" (recess in {rec['recess_in']})") if what else "glue (too thin)"))
for k in range(len(P)):
    if adds[k]:
        before = P[k].volume(); fig = union([P[k]] + adds[k])
        fig, _ = keep_main(fig)
        if fig is not None and fig.volume() >= before * 0.999: P[k] = fig
        else: print(f"WARNING {names[k]}: pins lost geometry, skipped")
    if holes[k]:
        before = P[k].volume(); P[k] = P[k] - union(holes[k]); P[k], dropped = keep_main(P[k], 0.001)
        print(f"{names[k]}: {len(holes[k])} hole(s), -{before - P[k].volume():.0f} mm3")
if dowels:                                                     # loose pins: one extra STL, lying on the plate
    row = []; x = 0.0
    for male, Ltot in dowels:
        c = male.centroid; sh = shapely.affinity.translate(male, -c.x, -c.y)
        b0 = sh.bounds; w = b0[2] - b0[0]; k_ = max(0.2, 1 - 2 * CH / w)
        body = mf.Manifold.extrude(cs_of(sh), Ltot - 2 * CH).translate((0, 0, CH))
        tip_t = mf.Manifold.extrude(cs_of(sh), CH, scale_top=(k_, k_)).translate((0, 0, Ltot - CH))
        tip_b = mf.Manifold.extrude(cs_of(sh), CH, scale_top=(k_, k_)).mirror((0, 0, 1)).translate((0, 0, CH))
        row.append((body + tip_t + tip_b).rotate((0, 90, 0)).translate((x, 0, w / 2))); x += Ltot + 3.0 / SCALE
    dv, dt = arrays(union(row)); write_stl(f"{OUT}/Pinos.stl", dv, dt)
    print(f"RESULT Pinos: {len(dowels)} loose pin(s)")
json.dump(report, open(f"{wd}/joints.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)

try:
    import simplificar as fs
except ImportError:
    fs = None
blob, meta = [], []
for k, m in enumerate(P):
    v, t = RAW[k] if k in RAW else arrays(m)
    if not len(t): print(f"WARNING piece {names[k]} is empty"); continue
    write_stl(f"{OUT}/{names[k]}.stl", v, t)
    size = (v.max(0) - v.min(0)) * SCALE
    print(f"RESULT {names[k]}: tris={len(t)} pieces={len(m.decompose()) if k not in RAW else '?'} closed={k not in RAW} size_mm={size.round(1).tolist()}")
    if fs is not None and len(t) > 120000:
        v2, t2 = fs.simplify(v.astype(np.float32), t.astype(np.int32), target_reduction=1 - 120000 / len(t))
    else:
        v2, t2 = v, t
    v2 = np.asarray(v2, np.float32); t2 = np.asarray(t2, np.uint32)
    meta.append(dict(name=names[k], nv=int(len(v2)), nt=int(len(t2)), size=size.round(1).tolist(), tris=int(len(t))))
    blob += [v2.tobytes(), t2.tobytes()]
open(f"{wd}/pieces.bin", "wb").write(b"".join(blob)); json.dump(meta, open(f"{wd}/pieces.json", "w", encoding="utf-8"))
print("done %.0fs" % (time.time() - t00))
