"""Pratos: deita cada peça na face que mais encosta na mesa e arruma as peças nos pratos da impressora, sem encostar.
usage: python plates.py <workdir> ['{"gap": 3, "por_cor": true, "refazer": false, "prato": null, "mesa": {"w": 256, "h": 256}}']
lê:    _build/<nome>.stl (peças prontas), pieces.json, info.json (pratos do arquivo original), seg.npy/part.npy/cor.npy,
       joints.json, layout.json (o anterior: o que o usuário arrumou fica onde está)
grava: layout.json = {mesa, n, itens: [{name, placa, R (3x3, p' = R p, no frame do STL), x, y (centro da peça no prato, mm),
       opcoes: [R...] (faces boas pra deitar), fil (filamento), fixo (veio do designer), grande (não cabe)}]}
Pratos seguem o Bambu Studio: placa k em (col*1.2*w, -lin*1.2*w), col/lin numa grade de ceil(sqrt(n)) colunas."""
import sys, os, json, re, struct, math, time, numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.signal import fftconvolve
from scipy.spatial import ConvexHull

RES = 1.0            # mm por pixel no mapa de ocupação do prato
BORDA = 2.0          # mm livres na borda do prato


def read_stl(p):
    data = open(p, "rb").read()
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        tri = np.array(re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data), np.float64).reshape(-1, 3, 3)
    else:
        n = struct.unpack("<I", data[80:84])[0]
        dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        tri = np.frombuffer(data[84:84 + n * 50], dtype=dt)["v"]
    return tri.reshape(-1, 3).astype(np.float64), np.arange(len(tri) * 3).reshape(-1, 3)   # sem juntar vértices: aqui só importa a forma


def rot_to_down(n):
    """rotação que leva a normal n (para fora da peça) para -Z: essa face fica apoiada na mesa"""
    n = n / np.linalg.norm(n); d = np.array([0.0, 0.0, -1.0]); c = float(n @ d)
    if c > 1 - 1e-9: return np.eye(3)
    if c < -1 + 1e-9: return np.diag([1.0, -1.0, -1.0])
    ax = np.cross(n, d); s = np.linalg.norm(ax); ax /= s
    K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + s * K + (1 - c) * K @ K


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def faces_boas(V, T, maxn=6):
    """faces candidatas pra deitar a peça: planos do casco convexo, ordenados pela área que encosta de verdade na mesa"""
    try:
        h = ConvexHull(V)
    except Exception:
        return [(np.eye(3), 0.0)]
    eq = h.equations[:, :3]; fa = V[h.simplices]
    ar = 0.5 * np.linalg.norm(np.cross(fa[:, 1] - fa[:, 0], fa[:, 2] - fa[:, 0]), axis=1)
    ordem = np.argsort(-ar)[:600]; livre = np.ones(len(ordem), bool); clus = []      # agrupa facetas quase paralelas (3°)
    En, Ea = eq[ordem], ar[ordem]
    for j in range(len(ordem)):
        if not livre[j]: continue
        junto = livre & (En @ En[j] > 0.9986); livre &= ~junto
        clus.append((En[j], float(Ea[junto].sum())))
        if len(clus) >= 40: break
    clus.sort(key=lambda c: -c[1]); clus = clus[:14]
    tv = V[T]; tn = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0]); ta = 0.5 * np.linalg.norm(tn, axis=1)
    tn = tn / (2 * ta[:, None] + 1e-20)
    out = []
    cand = [(n / np.linalg.norm(n)) for n, _ in clus] + [np.array([0.0, 0.0, -1.0])]      # + como está no modelo
    for n in cand:
        h_ = V @ n; d = h_.max()
        near = (h_[T] > d - 0.25).all(1) & (tn @ n > 0.996); contato = float(ta[near].sum())
        # área que vai precisar de suporte: faces viradas pra baixo mais de 45° e fora da mesa
        pend = (tn @ n > 0.7071) & ~(h_[T] > d - 0.3).all(1); suporte = float(ta[pend].sum())
        if contato < 1.0 and n[2] > -0.99: continue
        out.append((rot_to_down(n), contato, suporte + 3.0 * max(0.0, 20.0 - contato)))
    out.sort(key=lambda o: o[2] - 0.5 * o[1])
    uniq = []
    for o in out:
        if not any(np.abs(o[0] - u[0]).max() < 0.05 for u in uniq): uniq.append(o)
    return [(R, c) for R, c, _ in uniq[:maxn]] or [(np.eye(3), 0.0)]


def pegada(V, T, R):
    """mapa (pixels de RES mm) da sombra da peça no prato, já girada por R; e o canto (mm) do mapa"""
    P = V @ R.T; P -= [0, 0, P[:, 2].min()]
    xy = P[:, :2]; lo = xy.min(0) - RES; hi = xy.max(0) + RES
    W, H = (np.ceil((hi - lo) / RES) + 1).astype(int)
    q = (xy - lo) / RES
    m = np.zeros((H, W), bool)
    ij = np.floor(q).astype(int); m[ij[:, 1].clip(0, H - 1), ij[:, 0].clip(0, W - 1)] = True
    tq = q[T]; big = (np.ptp(tq[:, :, 0], 1) > 1.2) | (np.ptp(tq[:, :, 1], 1) > 1.2)
    if big.any():                                            # triângulos grandes (tampas de corte, faces planas): desenha inteiros
        im = Image.new("1", (W, H), 0); dr = ImageDraw.Draw(im)
        for tr in tq[big]: dr.polygon([tuple(p) for p in tr], fill=1)
        m |= np.array(im, bool)
    m = ndimage.binary_closing(m, np.ones((3, 3)), iterations=1, border_value=0) | m
    m = ndimage.binary_fill_holes(m)
    return m, lo, P


def angulo_retangulo(P):
    """ângulo que deixa a sombra da peça no menor retângulo (as peças ficam alinhadas e cabem melhor)"""
    xy = P[:, :2]
    try:
        hv = xy[ConvexHull(xy).vertices]
    except Exception:
        return 0.0
    e = np.diff(np.vstack([hv, hv[:1]]), axis=0); angs = np.unique(np.round(np.arctan2(e[:, 1], e[:, 0]) % (np.pi / 2), 4))
    best, ba = 1e30, 0.0
    for a in angs:
        r = hv @ rot_z(-a)[:2, :2].T; area = np.ptp(r[:, 0]) * np.ptp(r[:, 1])
        if area < best: best, ba = area, a
    return -float(ba)


def mesa_do_arquivo(path):
    """tamanho da mesa da impressora configurada num 3MF do Bambu (projetos abertos antes de o Voxel ler os pratos)"""
    if not path or not str(path).lower().endswith(".3mf") or not os.path.exists(path): return None
    import zipfile
    try:
        ps = zipfile.ZipFile(path).read("Metadata/project_settings.config").decode(errors="ignore")
    except Exception:
        return None
    pa = re.search(r'"printable_area"\s*:\s*\[(.*?)\]', ps, re.S)
    xy = np.array([[float(a), float(b)] for a, b in re.findall(r'"([-\d.]+)x([-\d.]+)"', pa.group(1))]) if pa else np.zeros((0, 2))
    if not len(xy): return None
    m = {"w": float(np.ptp(xy[:, 0])), "h": float(np.ptp(xy[:, 1])), "excluir": []}
    be = re.search(r'"bed_exclude_area"\s*:\s*\[(.*?)\]', ps, re.S)
    ex = [[float(a), float(b)] for a, b in re.findall(r'"([-\d.]+)x([-\d.]+)"', be.group(1))] if be else []
    if len(ex) >= 3: m["excluir"] = [ex]
    return m


class Prato:
    def __init__(s, mesa, cor=None):
        s.W, s.H = int(mesa["w"] / RES), int(mesa["h"] / RES); s.cor = cor
        s.occ = np.zeros((s.H, s.W), np.float32); b = int(math.ceil(BORDA / RES))
        s.occ[:b] = s.occ[-b:] = 1; s.occ[:, :b] = s.occ[:, -b:] = 1
        for poly in mesa.get("excluir", []):
            im = Image.new("1", (s.W, s.H), 0); ImageDraw.Draw(im).polygon([(x / RES, y / RES) for x, y in poly], fill=1)
            s.occ[np.array(im, bool)] = 1
        s.vazio = True

    def marcar(s, m, i0, j0):
        h, w = m.shape; a0, b0 = max(i0, 0), max(j0, 0); a1, b1 = min(i0 + h, s.H), min(j0 + w, s.W)
        if a1 > a0 and b1 > b0: s.occ[a0:a1, b0:b1] = np.maximum(s.occ[a0:a1, b0:b1], m[a0 - i0:a1 - i0, b0 - j0:b1 - j0])
        s.vazio = False

    def lugar(s, md):
        """melhor posição livre (canto do mapa, pixels) pra pegada dilatada md, ou None"""
        h, w = md.shape
        if h > s.H or w > s.W: return None
        ov = fftconvolve(s.occ, md[::-1, ::-1].astype(np.float32), mode="valid")
        ok = ov < 0.5
        if not ok.any(): return None
        ii, jj = np.nonzero(ok)
        cy, cx = ii + h / 2, jj + w / 2
        if s.vazio: sc = (cy - s.H / 2) ** 2 + (cx - s.W / 2) ** 2          # prato vazio: no meio
        else: sc = (cy - s.H / 2) ** 2 + (cx - s.W / 2) ** 2 * 0.8           # perto do centro, espalhando pros lados
        k = int(np.argmin(sc)); return int(ii[k]), int(jj[k])


def main():
    wd = sys.argv[1]; opt = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    t0 = time.time(); B = f"{wd}/_build"
    info = json.load(open(f"{wd}/info.json")); pieces = json.load(open(f"{wd}/pieces.json", encoding="utf-8"))
    placas_src = info.get("placas") or {}
    L0 = None
    if os.path.exists(f"{wd}/layout.json"):
        try: L0 = json.load(open(f"{wd}/layout.json", encoding="utf-8"))
        except Exception: L0 = None
    mesa = dict(placas_src.get("mesa") or mesa_do_arquivo(opt.get("template")) or {"w": 256.0, "h": 256.0, "excluir": []})
    mo = opt.get("mesa", (L0 or {}).get("mesa_escolhida"))                   # a mesa que o usuário escolheu fica
    if isinstance(mo, dict) and (float(mo["w"]), float(mo["h"])) != (mesa["w"], mesa["h"]):   # outra impressora
        mesa = {"w": float(mo["w"]), "h": float(mo["h"]), "excluir": mo.get("excluir", [])}
    else:
        mo = None
    GAP = float(opt.get("gap", 3.0))
    SCALE = float(info.get("export_scale", 1.0)) * float(info.get("prescale", 1.0))
    names = [p["name"] for p in pieces] + (["Pinos"] if os.path.exists(f"{B}/Pinos.stl") else [])
    marks = json.load(open(f"{wd}/marks.json"))["groups"] if os.path.exists(f"{wd}/marks.json") else []
    gi = {g["name"]: i for i, g in enumerate(marks)}
    # filamento de cada peça (arquivo pintado): cor que mais aparece nos triângulos dela
    fil = {}
    if os.path.exists(f"{wd}/cor.npy") and os.path.exists(f"{wd}/seg.npy"):
        cor = np.load(f"{wd}/cor.npy"); seg = np.load(f"{wd}/seg.npy")
        if len(cor) == len(seg):
            for n in names:
                if n in gi:
                    c = cor[seg == gi[n]]
                    if len(c): fil[n] = int(np.bincount(c).argmax())
    # peças intactas de um arquivo que já vinha em pratos: ficam onde o designer deixou
    fixos = {}
    if placas_src.get("objetos") and os.path.exists(f"{wd}/seg.npy") and os.path.exists(f"{wd}/part.npy"):
        seg = np.load(f"{wd}/seg.npy"); part = np.load(f"{wd}/part.npy")
        dl = np.load(f"{wd}/del.npy") if os.path.exists(f"{wd}/del.npy") else np.zeros(len(seg), bool)
        jj = json.load(open(f"{wd}/joints.json", encoding="utf-8")) if os.path.exists(f"{wd}/joints.json") else []
        com_encaixe = {j[k] for j in jj if j.get("pins") or j.get("step") for k in ("piece", "to")}
        for n in names:
            if n not in gi or n in com_encaixe: continue
            sel = (seg == gi[n]) & ~dl; ob = np.unique(part[sel])
            if len(ob) != 1: continue
            o = str(int(ob[0]))
            if o not in placas_src["objetos"] or ((part == ob[0]) & ~dl).sum() != sel.sum(): continue
            M = np.array(placas_src["objetos"][o]["M"]); M3 = M[:3] / SCALE
            if np.abs(M3.T @ M3 - np.eye(3)).max() > 0.02 or np.linalg.det(M3) < 0: continue
            fixos[n] = (placas_src["objetos"][o]["placa"], M3.T, M[3])
    antes = {}
    if L0 and not opt.get("refazer") and L0.get("mesa", {}).get("w") == mesa["w"] and L0.get("mesa", {}).get("h") == mesa["h"]:
        antes = {it["name"]: it for it in L0["itens"]}
    refaz_prato = opt.get("prato")                              # reorganizar só este prato (as peças dele)
    POR_COR = bool(opt.get("por_cor", (L0 or {}).get("por_cor", True))) and len(set(fil.values())) > 1    # sem AMS: cada cor nos seus pratos
    pratos = {}; itens = []; pend = []

    def prato(k, cor=None):
        if k not in pratos: pratos[k] = Prato(mesa, cor)
        return pratos[k]

    dil = ndimage.generate_binary_structure(2, 1)
    rg = max(1, int(round(GAP / RES)))
    for n in names:
        V, T = read_stl(f"{B}/{n}.stl"); tam = (V.max(0) - V.min(0)).round(1).tolist()
        opc = faces_boas(V, T)
        it = dict(name=n, fil=fil.get(n), tam=tam, opcoes=[R.round(6).tolist() for R, _ in opc])
        a = antes.get(n)
        manter = a is not None and np.abs(np.array(a.get("tam", [0, 0, 0])) - tam).max() < 1.5 and (refaz_prato is None or a["placa"] != refaz_prato)
        if manter:
            R = np.array(a["R"]); m, lo, P = pegada(V, T, R); c = (P[:, :2].min(0) + P[:, :2].max(0)) / 2
            i0, j0 = int(round((a["y"] - c[1] + lo[1]) / RES)), int(round((a["x"] - c[0] + lo[0]) / RES))
            prato(a["placa"], fil.get(n) if POR_COR else None).marcar(m, i0, j0)
            it.update(placa=a["placa"], R=a["R"], x=a["x"], y=a["y"], fixo=a.get("fixo", False), grande=a.get("grande", False)); itens.append(it); continue
        if n in fixos and refaz_prato is None:
            k, R, t = fixos[n]; P = V @ R.T + t
            m, lo, P2 = pegada(V, T, R); c = (P[:, :2].min(0) + P[:, :2].max(0)) / 2; c2 = (P2[:, :2].min(0) + P2[:, :2].max(0)) / 2
            i0, j0 = int(round((c[1] - c2[1] + lo[1]) / RES)), int(round((c[0] - c2[0] + lo[0]) / RES))
            prato(k, fil.get(n) if POR_COR else None).marcar(m, i0, j0)
            it.update(placa=k, R=R.round(6).tolist(), x=round(float(c[0]), 2), y=round(float(c[1]), 2), fixo=True, grande=False); itens.append(it); continue
        R0 = np.array(a["R"]) if (a is not None and refaz_prato is not None and a["placa"] == refaz_prato) else opc[0][0]
        pend.append((it, V, T, R0))
    # as maiores primeiro; separando por cor, cada cor em seus pratos
    def area_sombra(p):
        P = p[1] @ p[3].T; return np.ptp(P[:, 0]) * np.ptp(P[:, 1])
    if refaz_prato is not None: prato(refaz_prato)
    pend.sort(key=lambda p: -area_sombra(p)); pend.sort(key=lambda p: ((p[0]["fil"] or 0) if POR_COR else 0))
    for it, V, T, R0 in pend:
        cor = it["fil"] if POR_COR else None
        _, _, P0 = pegada(V, T, R0); a0 = angulo_retangulo(P0)
        cands = []
        for q in range(4):
            R = rot_z(a0 + q * np.pi / 2) @ R0; m, lo, P = pegada(V, T, R)
            m = np.pad(m, rg); lo = lo - rg * RES; md = ndimage.binary_dilation(m, dil, iterations=rg)
            cands.append((R, m, md, lo, P))
        feito = False
        ordem = sorted(pratos) if refaz_prato is None else [refaz_prato] + [k for k in sorted(pratos) if k != refaz_prato]
        for k in ordem:
            pr = pratos[k]
            if POR_COR and pr.cor != cor and not pr.vazio: continue
            best = None
            for R, m, md, lo, P in cands:
                pos = pr.lugar(md)
                if pos is None: continue
                i0, j0 = pos; h, w = md.shape; sc = ((i0 + h / 2) - pr.H / 2) ** 2 + ((j0 + w / 2) - pr.W / 2) ** 2
                if best is None or sc < best[0]: best = (sc, R, m, md, lo, P, i0, j0)
            if best:
                _, R, m, md, lo, P, i0, j0 = best
                if pr.vazio and POR_COR: pr.cor = cor
                pr.marcar(m, i0, j0)
                c = (P[:, :2].min(0) + P[:, :2].max(0)) / 2 - lo       # centro da peça dentro do mapa (mm)
                x, y = j0 * RES + c[0], i0 * RES + c[1]
                it.update(placa=k, R=R.round(6).tolist(), x=round(float(x), 2), y=round(float(y), 2), fixo=False, grande=False); feito = True; break
        if not feito:                                          # prato novo; se nem num prato vazio cabe, fica no meio e avisa
            k = max(pratos, default=0) + 1; pr = prato(k, cor); best = None
            for R, m, md, lo, P in cands:
                pos = pr.lugar(md)
                if pos is not None: best = (R, m, md, lo, P) + pos; break
            if best:
                R, m, md, lo, P, i0, j0 = best; pr.marcar(m, i0, j0)
                c = (P[:, :2].min(0) + P[:, :2].max(0)) / 2 - lo; x, y = j0 * RES + c[0], i0 * RES + c[1]; grande = False
            else:
                R = cands[0][0]; pr.vazio = False; pr.occ[:] = 1; x, y = mesa["w"] / 2, mesa["h"] / 2; grande = True
                print(f"WARNING {it['name']}: {it['tam']} mm não cabe no prato de {mesa['w']:.0f}x{mesa['h']:.0f}")
            it.update(placa=k, R=R.round(6).tolist(), x=round(float(x), 2), y=round(float(y), 2), fixo=False, grande=grande)
        itens.append(it)
    # numera os pratos sem buracos (1, 2, 3...)
    usados = sorted({it["placa"] for it in itens}); ren = {k: i + 1 for i, k in enumerate(usados)}
    for it in itens: it["placa"] = ren[it["placa"]]
    itens.sort(key=lambda it: (it["placa"], names.index(it["name"])))
    L = dict(mesa=mesa, mesa_escolhida=mo, n=len(usados), gap=GAP, por_cor=POR_COR, cores=len(set(fil.values())) > 1,
             escala=float(info.get("export_scale", 1.0)), itens=itens)
    json.dump(L, open(f"{wd}/layout.json", "w", encoding="utf-8"), ensure_ascii=False)
    for k in range(1, len(usados) + 1):
        print(f"plate {k}: " + ", ".join(it["name"] + (" (designer)" if it.get("fixo") else "") for it in itens if it["placa"] == k))
    print(f"done {len(itens)} pieces on {len(usados)} plate(s) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
