"""Teste de folga: uma régua com furos de folgas diferentes (0,05 a 0,30 mm, o número gravado do lado = centésimos de mm)
e uma "chave" com o pino do jeito que está configurado. Imprime, encaixa a chave em cada furo: o que entra justo sem forçar
é a folga da sua impressora e filamento.
usage: python calibracao.py <saida.stl> '<joints json>'"""
import sys, os, json, struct, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manifold3d as mf
import shapely, shapely.affinity
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union

out = sys.argv[1]; J = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
FOLGAS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
tipo = J.get("pin_type", "round")
mf.set_circular_segments(64)

SEG7 = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}


def texto(s, h):
    w = 0.55 * h; e = max(0.17 * h, 0.5); gap = 0.3 * h
    P_ = {"a": ((0, h), (w, h)), "b": ((w, h), (w, h / 2)), "c": ((w, h / 2), (w, 0)), "d": ((0, 0), (w, 0)), "e": ((0, 0), (0, h / 2)), "f": ((0, h / 2), (0, h)), "g": ((0, h / 2), (w, h / 2))}
    g = unary_union([shapely.affinity.translate(LineString(P_[sg]).buffer(e / 2, cap_style="square"), i * (w + gap), 0) for i, ch in enumerate(s) for sg in SEG7.get(ch, "")])
    b = g.bounds; return shapely.affinity.translate(g, -(b[0] + b[2]) / 2, -(b[1] + b[3]) / 2)


def cs(geom):
    rings = []
    for pg in (geom.geoms if hasattr(geom, "geoms") else [geom]):
        ext = np.asarray(pg.exterior.coords)[:-1]
        if not Polygon(ext).exterior.is_ccw: ext = ext[::-1]
        rings.append(ext)
        for h in pg.interiors:
            hh = np.asarray(h.coords)[:-1]
            if Polygon(hh).exterior.is_ccw: hh = hh[::-1]
            rings.append(hh)
    return mf.CrossSection(rings, mf.FillRule.Positive)


def forma(r, grow=0.0):
    """contorno do pino (igual ao do Voxel Cut), aumentado pela folga no furo"""
    rr = r + grow
    if tipo == "square": h = 0.8 * rr; return Polygon([(-h, -h), (h, -h), (h, h), (-h, h)])
    if tipo == "hex": a = np.arange(6) * np.pi / 3; return Polygon(np.c_[rr * np.cos(a), rr * np.sin(a)])
    if tipo == "none": h = 5 + grow; return Polygon([(-h, -h), (h, -h), (h, h), (-h, h)])    # sem pino: testa o rebaixo (um ressalto quadrado)
    return Point(0, 0).buffer(rr, quad_segs=24)


ima = tipo == "magnet"
if ima: r = float(J.get("mag_d", 6)) / 2; prof = float(J.get("mag_h", 2)) + 0.2
elif tipo == "none": r = 5.0; prof = float(J.get("step_depth", 2)) + 0.3
else:
    r = (float(J.get("pin_d") or 0) or (8.0 if tipo == "center" else 4.0)) / 2; prof = float(J.get("pin_len", 4)) + 0.4
passo = max(2 * r + 6, 11); larg = passo * len(FOLGAS) + 4; fundo = 2 * r + 13; alt = prof + 1.6
regua = mf.Manifold.cube((larg, fundo, alt)).translate((-larg / 2, -fundo / 2, 0))
furos = []; marcas = []
for i, c in enumerate(FOLGAS):
    x = -larg / 2 + 2 + passo * (i + 0.5); y = fundo / 2 - 1.5 - r - 0.3
    furos.append(mf.Manifold.extrude(cs(shapely.affinity.translate(forma(r, c), x, y)), prof + 0.01).translate((0, 0, alt - prof)))
    t = shapely.affinity.translate(texto(str(int(round(c * 100))), 4.0), x, -fundo / 2 + 4.5)
    marcas.append(mf.Manifold.extrude(cs(t), 0.61).translate((0, 0, alt - 0.6)))
regua = regua - mf.Manifold.batch_boolean(furos + marcas, mf.OpType.Add)
pecas = [regua]
if not ima:                                             # a chave: cabo + o pino no tamanho certo (o ímã você testa com o próprio ímã)
    cabo_l, cabo_w, cabo_h = max(2 * r + 10, 16), max(2 * r + 6, 12), 4.0
    cabo = mf.Manifold.cube((cabo_l, cabo_w, cabo_h)).translate((-cabo_l / 2, -cabo_w / 2, 0))
    L = prof - 0.4
    pino = mf.Manifold.extrude(cs(forma(r)), L - 0.4).translate((0, 0, cabo_h))
    ponta = mf.Manifold.extrude(cs(forma(r)), 0.4, scale_top=(max(0.2, 1 - 0.8 / (2 * r)),) * 2).translate((0, 0, cabo_h + L - 0.4))
    chave = (cabo + pino + ponta).translate((0, -fundo / 2 - cabo_w / 2 - 6, 0))
    pecas.append(chave)
m = mf.Manifold.batch_boolean(pecas, mf.OpType.Add)
me = m.to_mesh(); v = np.asarray(me.vert_properties)[:, :3]; t = np.asarray(me.tri_verts)
v = v - [v[:, 0].min(), v[:, 1].min(), 0]
tri = v[t].astype(np.float32); n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-20
rec = np.zeros(len(t), np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])); rec["n"] = n; rec["v"] = tri
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
with open(out, "wb") as f: f.write(b"Voxel Cut - teste de folga".ljust(80, b" ")); f.write(struct.pack("<I", len(t))); f.write(rec.tobytes())
print(f"RESULT teste de folga: {tipo} {2 * r:.1f} mm, folgas {', '.join(f'{c:.2f}' for c in FOLGAS)} -> {out}")
