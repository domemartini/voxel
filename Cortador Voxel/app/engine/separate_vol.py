"""Separação VOLUMÉTRICA: reparte o volume da figura entre as peças marcadas (cada ponto do interior fica com a peça
marcada mais próxima) e corta o modelo original com essas regiões. Encontros de 3 ou mais peças ficam limpos (um "Y"),
as peças nunca se sobrepõem nem deixam fresta e as superfícies de corte saem lisas.
Mesmo formato de saída de separate_seg.py (part_<k>_v/_t.npy, parts.json, caps.json), então finish.py não muda.
Se o modelo não for um sólido fechado, usa separate_seg.py (método por superfície).
usage: python separate_vol.py <workdir>"""
import sys, os, json, time, runpy
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
import manifold3d as mf
from skimage import measure
from scipy.ndimage import gaussian_filter, binary_dilation, binary_erosion, distance_transform_edt
from scipy.sparse.linalg import cg
from skimage.draw import polygon as rpoly

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
wd = sys.argv[1]; T0 = time.time()
v0 = np.load(f"{wd}/v.npy"); t0 = np.load(f"{wd}/t.npy"); seg = np.load(f"{wd}/seg.npy").astype(int)
G = json.load(open(f"{wd}/marks.json", encoding="utf-8"))["groups"]; ng = len(G); names = [g["name"] for g in G]
COR_SPLIT = False          # peças que seguem as cores do arquivo (Separar por cor): o corte acompanha a pintura, não se achata
if os.path.exists(f"{wd}/cor.npy"):
    _cor = np.load(f"{wd}/cor.npy")
    if len(_cor) == len(seg):
        _pura = sum(int(np.bincount(_cor[seg == _k]).max()) for _k in np.unique(seg) if (seg == _k).any())
        COR_SPLIT = _pura / len(seg) > 0.92
        if COR_SPLIT: print(f"peças seguem as cores do arquivo ({_pura / len(seg):.0%}): cortes sem achatar")


def metodo_superficie(motivo):
    print(f"volumetric split not possible ({motivo}) - using the surface method")
    sys.argv = [os.path.join(HERE, "separate_seg.py"), wd]; runpy.run_path(os.path.join(HERE, "separate_seg.py"), run_name="__main__"); sys.exit(0)


def solido(v, t):
    return mf.Manifold(mf.Mesh(vert_properties=np.ascontiguousarray(v, np.float32), tri_verts=np.ascontiguousarray(t, np.uint32)))


# cascas inteiras de uma peça só, sem encostar em nenhuma outra casca (kit que já vem separado, peça solta de outra cor):
# vão direto pra peça, do jeito que são, sem passar pela grade
e_ = np.r_[t0[:, [0, 1]], t0[:, [1, 2]]]
_, cv_ = connected_components(sp.coo_matrix((np.ones(len(e_)), (e_[:, 0], e_[:, 1])), shape=(len(v0), len(v0))), directed=False)
shell = cv_[t0[:, 0]]; nsh = int(shell.max()) + 1
DELF = f"{wd}/del.npy"; dele0 = np.load(DELF) if os.path.exists(DELF) else np.zeros(len(t0), bool)
if len(dele0) != len(t0): dele0 = np.zeros(len(t0), bool)
direto = {}; resto = np.ones(len(t0), bool)
if 1 < nsh <= 3000:
    tv_ = v0[t0]; bmin = np.full((nsh, 3), np.inf); bmax = np.full((nsh, 3), -np.inf)
    np.minimum.at(bmin, shell, tv_.min(1)); np.maximum.at(bmax, shell, tv_.max(1))
    over = np.all((bmin[:, None] <= bmax[None] + 0.01) & (bmax[:, None] >= bmin[None] - 0.01), axis=2); np.fill_diagonal(over, False)
    for s_ in np.flatnonzero(~over.any(1)):
        tri = np.flatnonzero(shell == s_); ls_ = np.unique(seg[tri])
        if len(ls_) != 1 or dele0[tri].any(): continue
        u_, inv_ = np.unique(t0[tri], return_inverse=True)
        m_ = solido(v0[u_], inv_.reshape(-1, 3))
        if m_.status() != mf.Error.NoError or m_.volume() <= 0: continue
        direto.setdefault(int(ls_[0]), []).append(m_.as_original()); resto[tri] = False
    if direto: print(f"{sum(len(x) for x in direto.values())} loose shell(s) kept whole ({len(direto)} piece(s)), {int(resto.sum())} triangles go through the grid")
t0 = t0[resto]; seg = seg[resto]
DIRETO_IDS = {m_.original_id() for ms in direto.values() for m_ in ms}
parts, pieces, regions = [], {}, {}
OID = -1
if len(t0):
    orig = solido(v0, t0)
    if orig.status() != mf.Error.NoError:                      # malha com defeito: separa arestas com 3+ faces e fecha os buracos
        from reparo import split_nonmanifold, fill_holes
        vr, tr_ = split_nonmanifold(v0, t0); vr, tr_ = fill_holes(vr, tr_, max_edges=5000)
        orig = solido(vr, tr_); print(f"model repaired before cutting: {orig.status()}")
    if orig.status() != mf.Error.NoError or orig.volume() <= 0: metodo_superficie("model is not a closed solid")
    # CASCA DE DONO ÚNICO: o designer às vezes faz cada parte como um sólido separado, enfiado no outro (base de pedra e o
    # boneco em cima). Se uma casca inteira é de uma peça só, o volume dentro dela é dessa peça: o corte fica exatamente
    # onde as cascas se encontram, em vez de o volume ser repartido "por proximidade" (que fazia a sola do pé virar uma
    # cúpula comendo a pedra em volta).
    DONOS = []
    if orig.status() == mf.Error.NoError:
        ee_ = np.r_[t0[:, [0, 1]], t0[:, [1, 2]]]
        _, cv_ = connected_components(sp.coo_matrix((np.ones(len(ee_)), (ee_[:, 0], ee_[:, 1])), shape=(len(v0), len(v0))), directed=False)
        sh0 = cv_[t0[:, 0]]; nsh0 = int(sh0.max()) + 1
        if 1 < nsh0 <= 200:
            tv0 = v0[t0]; bmin = np.full((nsh0, 3), np.inf); bmax = np.full((nsh0, 3), -np.inf)
            np.minimum.at(bmin, sh0, tv0.min(1)); np.maximum.at(bmax, sh0, tv0.max(1))
            ntri = np.bincount(sh0, minlength=nsh0)
            for s_ in range(nsh0):
                if ntri[s_] < 0.02 * len(t0): continue                     # só cascas grandes
                cont = np.bincount(seg[sh0 == s_], minlength=ng + 1); k_ = int(cont.argmax())
                if k_ >= ng or cont[k_] < 0.97 * ntri[s_]: continue       # tem mais de uma peça marcada nela: o motor decide
                if (seg == k_).sum() > 1.6 * cont[k_]: continue           # a peça também está em outra casca: não trava
                toca = np.all((bmin <= bmax[s_] + 0.01) & (bmax >= bmin[s_] - 0.01), axis=1); toca[s_] = False
                if not toca.any(): continue
                u_, inv_ = np.unique(t0[sh0 == s_], return_inverse=True)
                m_ = solido(v0[u_], inv_.reshape(-1, 3))
                if m_.status() == mf.Error.NoError and m_.volume() > 0: DONOS.append((m_, k_))
            if DONOS: print(f"single-owner shells: {', '.join(names[k] for _, k in DONOS)} (volume inside them is fixed to that piece)")
    comps = orig.decompose()
    if len(comps) > 1:                                          # cascas soltas sobrepostas (ex.: asas enfiadas no corpo): funde num sólido só
        orig = mf.Manifold.batch_boolean(comps, mf.OpType.Add); print(f"merged {len(comps)} overlapping shells into one solid")

    # ---------------------------------------------------------------- pontos rotulados da superfície
    lab = seg.copy()
    dele = dele0[resto] if dele0.any() else None
    VOID = None
    if dele is not None and len(dele) == len(t0) and dele.any():
        VOID = ng; lab[dele] = VOID; print(f"deleted by the user: {int(dele.sum())} triangles")
    vs, ts, ls = v0, t0, lab
    if os.path.exists(f"{wd}/field.npy"):                      # costura suave (corta os triângulos no meio): pontos mais precisos na costura
        F = np.load(f"{wd}/field.npy").astype(np.float64)
        if F.shape == (len(v0), ng):
            if VOID is not None:
                F = np.c_[F, np.zeros(len(v0))]; dv = np.unique(t0[dele]); F[dv] = 0; F[dv, ng] = 1
            from refine import refine
            vs, ts, ls = refine(v0, t0, F); ls = ls.astype(int)
    C = vs[ts].mean(1); Lp = ls
    tree = cKDTree(C)
    NL = ng + (1 if VOID is not None else 0)
    print(f"labelled surface points: {len(C)}  ({time.time() - T0:.0f}s)")

    # ---------------------------------------------------------------- grade 3D e campo harmônico (película esticada entre as regiões)
    vu_ = v0[np.unique(t0)]; lo, hi = vu_.min(0), vu_.max(0); diag = float(np.linalg.norm(hi - lo))
    h = max(diag / 400, (np.prod(hi - lo) / 12e6) ** (1 / 3))
    h = max(h, (orig.volume() / 1.2e6) ** (1 / 3))            # no máximo ~1,2M voxels dentro da figura: o tempo do campo cresce com isso (figura pequena e cheia de detalhe ficava lenta)
    lo = lo - 3 * h; hi = hi + 3 * h
    nx, ny, nz = (np.ceil((hi - lo) / h).astype(int) + 1)
    inside = np.zeros((nx, ny, nz), bool)                    # dentro/fora: fatia o sólido em cada altura e rasteriza a fatia
    for kz in range(nz):
        acc = np.zeros((nx, ny), np.int16)
        for poly in orig.slice(lo[2] + kz * h).to_polygons():
            pp = np.asarray(poly)
            if len(pp) < 3: continue
            area = 0.5 * np.sum(pp[:, 0] * np.roll(pp[:, 1], -1) - np.roll(pp[:, 0], -1) * pp[:, 1])
            rr, cc = rpoly((pp[:, 0] - lo[0]) / h, (pp[:, 1] - lo[1]) / h, shape=(nx, ny))
            acc[rr, cc] += 1 if area > 0 else -1
        inside[:, :, kz] = acc > 0
    print(f"  fatias prontas ({time.time() - T0:.0f}s)", flush=True)
    FORCADO = None
    if DONOS:
        cobre = np.zeros(inside.shape, np.int8); FORCADO = np.full(inside.shape, -1, np.int32)
        for m_, k_ in DONOS:
            b_ = m_.bounding_box(); z0_ = max(0, int(np.floor((b_[2] - lo[2]) / h))); z1_ = min(nz - 1, int(np.ceil((b_[5] - lo[2]) / h)))
            mk = np.zeros(inside.shape, bool)
            for kz in range(z0_, z1_ + 1):
                acc = np.zeros((nx, ny), np.int16)
                for poly in m_.slice(lo[2] + kz * h).to_polygons():
                    pp = np.asarray(poly)
                    if len(pp) < 3: continue
                    area = 0.5 * np.sum(pp[:, 0] * np.roll(pp[:, 1], -1) - np.roll(pp[:, 0], -1) * pp[:, 1])
                    rr, cc = rpoly((pp[:, 0] - lo[0]) / h, (pp[:, 1] - lo[1]) / h, shape=(nx, ny))
                    acc[rr, cc] += 1 if area > 0 else -1
                mk[:, :, kz] = acc > 0
            mk &= inside; cobre += mk; FORCADO[mk] = k_
        FORCADO[cobre != 1] = -1                                      # onde duas cascas se sobrepõem, o motor decide
        print(f"  volume travado pelas cascas: {int((FORCADO >= 0).sum())} voxels ({time.time() - T0:.0f}s)", flush=True)
    LP_T, VIS_T = (Lp.copy(), np.ones(len(Lp), bool)) if len(ts) == len(Lp) else (None, None)
    # pele enterrada: casca enfiada dentro de outra (pé com pino dentro da base). Depois de juntar tudo num sólido, a pele que
    # ficou no miolo não é mais superfície e não vale como rótulo.
    fundo_ = binary_erosion(inside, iterations=2)
    ijk_ = np.clip(np.rint((C - lo) / h).astype(int), 0, np.array(inside.shape) - 1)
    enterrado = fundo_[ijk_[:, 0], ijk_[:, 1], ijk_[:, 2]]; del fundo_
    if enterrado.any() and (~enterrado).sum() > 100:
        if LP_T is not None: VIS_T = ~enterrado
        C = C[~enterrado]; Lp = Lp[~enterrado]; tree = cKDTree(C)
        print(f"buried surface ignored: {int(enterrado.sum())} labelled points inside the solid")
    # PELE AMOSTRADA POR IGUAL: um ponto por triângulo deixa as áreas lisas de triângulo grande (fundo de base, corte plano
    # do designer) quase sem rótulo, e o miolo ali ficava "mais perto" de outra peça densa (a sola do pé 15 mm acima):
    # a peça escorria pra dentro da vizinha. Triângulo maior que a grade ganha pontos espalhados nele.
    if LP_T is not None:
        tv_ = vs[ts]; L_ = np.linalg.norm(tv_ - tv_[:, [1, 2, 0]], axis=2).max(1)
        gr = np.flatnonzero((L_ > 2.5 * h) & VIS_T)
        if len(gr):
            nn_ = np.minimum(np.ceil(L_[gr] / (2 * h)).astype(int), 120); extra, lab_x = [], []       # um ponto a cada ~2 voxels
            for n_ in np.unique(nn_):
                ids = gr[nn_ == n_]; ij = np.array([(i, j) for i in range(n_ + 1) for j in range(n_ + 1 - i)], float) / n_
                w_ = np.c_[1 - ij.sum(1), ij]                                        # coordenadas baricêntricas
                pts = np.einsum("pk,tkd->tpd", w_, tv_[ids]).reshape(-1, 3)
                extra.append(pts); lab_x.append(np.repeat(LP_T[ids], len(w_)))
            extra = np.vstack(extra); lab_x = np.concatenate(lab_x)
            C = np.vstack([C, extra]); Lp = np.concatenate([Lp, lab_x]); tree = cKDTree(C)
            print(f"even surface sampling: +{len(extra)} points on {len(gr)} big triangles")
    faixa = binary_dilation(inside, iterations=3)             # "peça mais próxima" só dentro e numa faixa fina em volta (o resto fica fora de tudo)
    # peça mais próxima: busca exata só na casca (dentro encostado em fora) e na faixa de fora, onde a costura é decidida;
    # o fundo do interior só precisa de um chute inicial pro solver, e vem do voxel de casca mais perto (linear, ~10x mais rápido)
    perto = faixa & ~binary_erosion(inside, iterations=1)
    fi = np.flatnonzero(perto); GP = np.c_[np.unravel_index(fi, inside.shape)] * h + lo
    print(f"  casca + faixa: {len(fi) / 1e6:.1f}M pontos ({time.time() - T0:.0f}s)", flush=True)
    _, nn = tree.query(GP, workers=-1); lab_near = np.full(inside.size, -1, np.int64); lab_near[fi] = Lp[nn]; lab_near = lab_near.reshape(nx, ny, nz); del GP, nn
    fundo = inside & ~perto
    if fundo.any():
        casca_m = inside & perto
        _, ind = distance_transform_edt(~casca_m, return_distances=True, return_indices=True)
        lab_near[fundo] = lab_near[ind[0][fundo], ind[1][fundo], ind[2][fundo]]; del ind
    print(f"grid {nx}x{ny}x{nz} ({nx * ny * nz / 1e6:.1f}M points, {h:.2f} mm), {inside.sum()} inside  ({time.time() - T0:.0f}s)")
    # Laplace no interior, com o rótulo da superfície fixo na casca (voxels de dentro encostados em voxels de fora)
    idx_in = np.flatnonzero(inside); coords = np.c_[np.unravel_index(idx_in, inside.shape)]
    pos = -np.ones(inside.size, np.int64); pos[idx_in] = np.arange(len(idx_in))
    I, J = [], []; casca = np.zeros(len(idx_in), bool); shp = np.array(inside.shape)
    for ax in range(3):
        for s_ in (-1, 1):
            c2 = coords.copy(); c2[:, ax] += s_; ok = (c2[:, ax] >= 0) & (c2[:, ax] < shp[ax])
            q = -np.ones(len(coords), np.int64); q[ok] = pos[np.ravel_multi_index(c2[ok].T, inside.shape)]
            casca |= q < 0; g_ = q >= 0; I.append(np.flatnonzero(g_)); J.append(q[g_])
    I = np.concatenate(I); J = np.concatenate(J)
    Adj = sp.coo_matrix((np.ones(len(I)), (I, J)), shape=(len(idx_in),) * 2).tocsr(); Lap = sp.diags(np.asarray(Adj.sum(1)).ravel()) - Adj
    if FORCADO is not None:                                          # voxels dentro de casca de dono único: fixos como a pele
        forc_in = FORCADO.ravel()[idx_in]; casca |= forc_in >= 0
    free = np.flatnonzero(~casca); fix = np.flatnonzero(casca)
    Lff = Lap[free][:, free].tocsr(); Lfb = Lap[free][:, fix]
    lab_in = lab_near.ravel()[idx_in]
    if FORCADO is not None: lab_in = np.where(forc_in >= 0, forc_in, lab_in)
    # cada peça: campo só numa caixa em volta da casca dela (fora da caixa o campo dela é ~0). Com muitas peças pequenas
    # (ex.: separar por cor) isso é muito mais rápido e a memória não cresce com o número de peças: guardamos só os 2 maiores.
    TOPV1 = np.zeros(len(idx_in), np.float32); TOPL1 = np.full(len(idx_in), -1, np.int32)
    TOPV2 = np.zeros(len(idx_in), np.float32); TOPL2 = np.full(len(idx_in), -1, np.int32)
    CAMPO = {}
    for k in range(NL):
        fk = np.flatnonzero(casca & (lab_in == k))
        if not len(fk): continue
        ck = coords[fk]; mg = int(max(8, 0.35 * (ck.max(0) - ck.min(0)).max())); lo_k = np.maximum(ck.min(0) - mg, 0); hi_k = np.minimum(ck.max(0) + mg, shp - 1)
        sel = np.flatnonzero(np.all((coords >= lo_k) & (coords <= hi_k), axis=1))
        if len(sel) > 0.7 * len(idx_in):
            sel = np.arange(len(idx_in)); lo_k = np.zeros(3, int); hi_k = shp - 1
            b = (lab_in[fix] == k).astype(float)
            x, _ = cg(Lff, -(Lfb @ b), x0=(lab_in[free] == k).astype(float), rtol=1e-4, maxiter=1000)
            val = np.zeros(len(idx_in), np.float32); val[fix] = b; val[free] = x
        else:
            Ls = Lap[sel][:, sel].tocsr(); fx = casca[sel]; fr_ = ~fx       # vizinhos fora da caixa ficam de fora = valor 0
            b = (lab_in[sel][fx] == k).astype(float)
            x, _ = cg(Ls[fr_][:, fr_], -(Ls[fr_][:, fx] @ b), x0=(lab_in[sel][fr_] == k).astype(float), rtol=1e-4, maxiter=1000)
            val = np.zeros(len(sel), np.float32); val[fx] = b; val[fr_] = x
        if os.environ.get("VOXELCUT_TEMPOS"): print(f"    campo {names[k] if k < ng else 'apagado'}: {len(sel) / 1e6:.2f}M voxels ({time.time() - T0:.0f}s)", flush=True)
        CAMPO[k] = (sel, val, lo_k, hi_k)
        m1, a1, m2, a2 = TOPV1[sel], TOPL1[sel], TOPV2[sel], TOPL2[sel]; up = val > m1
        TOPV2[sel] = np.where(up, m1, np.maximum(m2, val)); TOPL2[sel] = np.where(up, a1, np.where(val > m2, k, a2))
        TOPV1[sel] = np.where(up, val, m1); TOPL1[sel] = np.where(up, k, a1)
    del Lap, Lff, Lfb, Adj
    print(f"harmonic field ready  ({time.time() - T0:.0f}s, {len(CAMPO)} campos)")


    def taubin(V, Fc, it=8, lam=0.5, mu=-0.53):
        """alisa a superfície sem encolher (Taubin)"""
        e = np.r_[Fc[:, [0, 1]], Fc[:, [1, 2]], Fc[:, [2, 0]]]
        A = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(V), len(V))).tocsr(); A = ((A + A.T) > 0).astype(float)
        deg = np.asarray(A.sum(1)).ravel(); deg[deg == 0] = 1; W = sp.diags(1 / deg) @ A
        for _ in range(it):
            V = V + lam * (W @ V - V); V = V + mu * (W @ V - V)
        return V


    orig = orig.as_original(); OID = orig.original_id()
    for k in range(NL):
        if not (Lp == k).any() or k not in CAMPO: continue
        sel, val, lo_k, hi_k = CAMPO[k]
        g0 = np.maximum(lo_k - 2, 0); g1 = np.minimum(hi_k + 3, shp)                              # sub-grade da caixa da peça
        f = np.where(lab_near[g0[0]:g1[0], g0[1]:g1[1], g0[2]:g1[2]] == k, 1.0, -1.0).astype(np.float32)
        ins = inside[g0[0]:g1[0], g0[1]:g1[1], g0[2]:g1[2]]; f[ins] = -1.0                          # dentro e fora da caixa: não é dela
        uo = np.where(TOPL1[sel] == k, TOPV2[sel], TOPV1[sel]); cs = coords[sel] - g0
        f[cs[:, 0], cs[:, 1], cs[:, 2]] = val - uo
        f = gaussian_filter(f, 1.0)                                                                # campo suave -> superfície de corte lisa
        f[[0, -1], :, :] = -1; f[:, [0, -1], :] = -1; f[:, :, [0, -1]] = -1                       # região fechada dentro da grade
        if f.max() <= 0: continue
        Vr, Fr, _, _ = measure.marching_cubes(f, level=0.0, spacing=(h, h, h))
        Vr = taubin(Vr + lo + g0 * h, Fr, it=25)
        reg = mf.Manifold(mf.Mesh(vert_properties=np.ascontiguousarray(Vr, np.float32), tri_verts=np.ascontiguousarray(Fr, np.uint32)))
        if reg.status() != mf.Error.NoError: metodo_superficie(f"region of {names[k] if k < ng else 'deleted'} is not closed")
        if reg.volume() <= 0:
            reg = mf.Manifold(mf.Mesh(vert_properties=np.ascontiguousarray(Vr, np.float32), tri_verts=np.ascontiguousarray(Fr[:, ::-1], np.uint32)))
        reg = reg.as_original(); regions[k] = reg.original_id()
        pc = orig ^ reg
        comps = sorted(pc.decompose(), key=lambda m: -m.volume())
        if comps and len(comps) > 1:                                                                 # pedacinhos soltos na costura: fora
            big = comps[0].volume(); pc = mf.Manifold.batch_boolean([c for c in comps if c.volume() > 0.002 * big], mf.OpType.Add)
        if pc.volume() < 1.0:                                                                         # casquinha sem volume (ex.: decalque de cor): não vira peça
            print(f"piece {names[k] if k < ng else '(deleted)'}: volume {pc.volume():.2f} mm3 - pequena demais, descartada"); continue
        pieces[k] = pc
        print(f"piece {names[k] if k < ng else '(deleted)'}: volume {pc.volume():.0f} mm3  ({time.time() - T0:.0f}s)")

    # ------------------------------------------------------------ corte plano: suave E reto (a face de corte assenta na mesa)
    # troca a superfície de corte curva de cada par de peças pelo plano que melhor passa por ela, só na região do corte.
    try:
        _cfg = json.load(open(f"{wd}/config.json", encoding="utf-8"))
    except Exception:
        _cfg = {}
    PLANO = bool((_cfg.get("joints") or {}).get("plano", True)) and not COR_SPLIT

    def faces_corte(k):
        """faces de corte da peça k agrupadas pela peça vizinha: {j: triângulos (n,3,3)}"""
        m = pieces[k].to_mesh(); V = np.asarray(m.vert_properties)[:, :3].astype(np.float64); Fk = np.asarray(m.tri_verts).astype(np.int64)
        rid = np.asarray(m.run_original_id); rix = np.asarray(m.run_index); src = np.zeros(len(Fk), np.int64)
        for r in range(len(rid)): src[rix[r] // 3:rix[r + 1] // 3] = rid[r]
        cut = (src != OID) & ~np.isin(src, list(DIRETO_IDS))
        if not cut.any(): return {}
        Q = V[Fk[cut]]; cen = Q.mean(1)
        ijk = np.clip(np.rint((cen - lo) / h).astype(int), 0, np.array([nx, ny, nz]) - 1)
        flat = np.ravel_multi_index(ijk.T, (nx, ny, nz)); pp = pos[flat]
        tgt = lab_near.ravel()[flat].astype(np.int64)
        dn = pp >= 0; q = pp[dn]; tgt[dn] = np.where(TOPL1[q] == k, TOPL2[q], TOPL1[q])
        ruim = tgt < 0; tgt[ruim] = lab_near.ravel()[flat[ruim]]
        return {int(j): Q[tgt == j] for j in np.unique(tgt) if j >= 0 and j != VOID and j != k and j in pieces}

    def npedacos(m):
        T = np.asarray(m.to_mesh().tri_verts).astype(np.int64)
        if not len(T): return 0
        nv = int(T.max()) + 1
        g = sp.coo_matrix((np.ones(len(T) * 2), (np.r_[T[:, 0], T[:, 1]], np.r_[T[:, 1], T[:, 2]])), shape=(nv, nv))
        return int(connected_components(g, directed=False)[0]) - int((np.bincount(T.ravel(), minlength=nv) == 0).sum())

    def concluir(k, j, Pk, Pj, nk, nj, n, dmax, rotulo):
        un = lambda L: mf.Manifold.batch_boolean(L, mf.OpType.Add) if len(L) > 1 else (L[0] if L else mf.Manifold())
        if nk.status() != mf.Error.NoError or nj.status() != mf.Error.NoError: return "falhou"
        def limpa(novo, velho):
            """a operação booleana deixa cascas de volume zero: tira, e só o que sobrar de pedaço novo conta"""
            if npedacos(novo) <= npedacos(velho): return novo
            cs = [cm for cm in novo.decompose() if cm.volume() > 2.0]
            return un(cs) if cs else novo
        nk, nj = limpa(nk, Pk), limpa(nj, Pj)
        if nk.status() != mf.Error.NoError or nj.status() != mf.Error.NoError: return "falhou"
        if npedacos(nk) > npedacos(Pk) or npedacos(nj) > npedacos(Pj): return "estilhaçaria a peça"        # achatar nunca pode criar pedaço solto
        for novo, velho in ((nk, Pk), (nj, Pj)):
            bn, bv = np.array(novo.bounding_box()), np.array(velho.bounding_box())
            tol = 2.0 + 1.5 * dmax                                         # o que a fatia pode mesmo mover
            if (bn[:3] < bv[:3] - tol).any() or (bn[3:] > bv[3:] + tol).any(): return "empurraria material pra fora da peça"
        dk, dj = nk.volume() - Pk.volume(), nj.volume() - Pj.volume()
        # a peça k pode perder a "bolha" que tinha entrado na j (é material da j); ganhar pouco. A j quase não muda.
        if dk < -0.6 * Pk.volume() or dk > 0.15 * Pk.volume() or abs(dj) > 0.15 * Pj.volume(): return f"mudaria demais ({dk:+.0f} / {dj:+.0f} mm3)"
        pieces[k], pieces[j] = mf.Manifold(nk.to_mesh()), mf.Manifold(nj.to_mesh())   # consolida (senão cada corte seguinte refaz a cadeia toda)
        ang = np.degrees(np.arccos(min(1.0, abs(n[2]))))
        return (rotulo + ", " if rotulo else "") + f"plano ({'horizontal' if ang < 0.01 else f'{ang:.0f}° da horizontal'}, antes ondulava {dmax:.1f} mm)"

    def aplainar_varias(k, j, Q, Pq, Pu, borda, lacos, N0, At):
        """corte com várias costuras (várias patas no chão, ligadas por baixo): só no caso deitado. Cada pata fica com a
        sola plana na altura da SUA costura; tudo que era de k abaixo dos planos (inclusive a ligação por baixo) vai pra j."""
        n = np.array([0.0, 0.0, np.sign(N0[2]) or -1.0])
        if abs(N0[2]) < np.cos(np.radians(35)): return f"várias costuras e inclinado: fica como está"
        from shapely.geometry import Polygon as _P, LineString as _L
        from shapely.ops import unary_union as _uu, polygonize as _pz
        c = Pu[np.unique(borda)].mean(0)
        A_ = np.array([1.0, 0.0, 0.0]); B_ = np.cross(n, A_)
        uvp = lambda P_: np.stack([(P_ - c) @ A_, (P_ - c) @ B_], 1)
        d = (Pq - c) @ n; ub = uvp(Pu)
        pegada = _uu([p for p in (_P(t) for t in uvp(Pq).reshape(-1, 3, 2)) if p.area > 1e-9]).buffer(0.5)
        pl = []
        for l_ in lacos:
            eb = borda[l_]; rim = Pu[np.unique(eb)]; di = float(((rim - c) @ n).mean())
            if float(np.ptp((rim - c) @ n)) > 2.0: continue                             # costura dessa pata ondula demais: não mexe nela
            poly = _uu(list(_pz(_uu([_L(ub[list(e_)]) for e_ in eb]))))
            if poly.is_empty or poly.area < 3.0: continue
            pl.append((poly, di))
        if not pl: return "várias costuras, nenhuma fecha"
        def prisma(forma, z0, z1):
            rings = []
            for pg in (list(forma.geoms) if hasattr(forma, "geoms") else [forma]):
                if pg.is_empty or pg.area < 1e-6: continue
                ext = np.asarray(pg.exterior.coords)[:-1]; rings.append(ext if _P(ext).exterior.is_ccw else ext[::-1])
                for hole in pg.interiors:
                    hh = np.asarray(hole.coords)[:-1]; rings.append(hh[::-1] if _P(hh).exterior.is_ccw else hh)
            if not rings or z1 <= z0: return None
            return mf.Manifold.extrude(mf.CrossSection(rings, mf.FillRule.Positive), z1 - z0).translate((0, 0, z0)).transform(np.c_[A_, B_, n, c])
        un = lambda L: mf.Manifold.batch_boolean([x for x in L if x is not None], mf.OpType.Add) if len([x for x in L if x is not None]) > 1 else next((x for x in L if x is not None), mf.Manifold())
        fundo = float(d.max()) + 1.0; topo = float(d.min()) - 1.0; dmax_pl = max(di for _, di in pl)
        Sd = un([prisma(poly.buffer(0.3), di, fundo) for poly, di in pl] +
                [prisma(pegada.difference(_uu([poly.buffer(0.3) for poly, _ in pl])), dmax_pl, fundo)])   # a ligação por baixo do chão
        Su = un([prisma(poly.buffer(0.2), topo, di) for poly, di in pl])
        Pk, Pj = pieces[k], pieces[j]
        nk = (Pk - Sd) + (Pj ^ Su); nj = (Pj - Su) + (Pk ^ Sd)
        dmax = float(np.abs(d).max())
        return concluir(k, j, Pk, Pj, nk, nj, n, dmax, f"{len(pl)} costuras planas")

    def aplainar(k, j, Q):
        """troca a superfície de corte k|j por um plano NA ALTURA DA COSTURA (onde a peça encontra a outra na superfície).
        Abaixo do plano (lado de j), tudo que era de k volta pra j; acima dele, só DENTRO do contorno da costura, o que era de j
        vai pra k. Nada fora do contorno muda (antes o plano ia na altura média da 'bolha' e levava uma placa de pedra junto)."""
        tn = np.cross(Q[:, 1] - Q[:, 0], Q[:, 2] - Q[:, 0]); a = np.linalg.norm(tn, axis=1) / 2; At = a.sum()
        if At < 12.0: return "pequeno"
        N0 = tn.sum(0); coer = np.linalg.norm(N0) / (2 * At); N0 /= np.linalg.norm(N0)
        quase_deitado = abs(N0[2]) > np.cos(np.radians(20))
        if coer < (0.5 if quase_deitado else 0.8): return f"curvo demais ({coer:.2f})"      # corte em U / contornando uma dobra: fica como está
        # a costura = borda da superfície de corte (aresta usada por um triângulo só)
        Pq = Q.reshape(-1, 3); _, vid = np.unique(np.round(Pq / 1e-4).astype(np.int64), axis=0, return_inverse=True); vid = vid.ravel()
        F = vid.reshape(-1, 3); Pu = np.zeros((vid.max() + 1, 3)); Pu[vid] = Pq
        e = np.sort(np.r_[F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]], 1); ue, ce = np.unique(e, axis=0, return_counts=True); borda = ue[ce == 1]
        if len(borda) < 6: return "sem costura aberta"
        # várias costuras num corte só (4 patas que se ligam por baixo do chão): cada costura ganha o próprio plano
        nvb = int(borda.max()) + 1
        _, cb = connected_components(sp.coo_matrix((np.ones(len(borda)), (borda[:, 0], borda[:, 1])), shape=(nvb, nvb)), directed=False)
        laco_e = cb[borda[:, 0]]; lacos = [np.flatnonzero(laco_e == l_) for l_ in np.unique(laco_e)]
        lacos = [l_ for l_ in lacos if len(l_) >= 6]
        if len(lacos) > 1: return aplainar_varias(k, j, Q, Pq, Pu, borda, lacos, N0, At)
        Rp = Pu[np.unique(borda)]; c = Rp.mean(0)
        Xr = Rp - c; n = np.linalg.eigh(Xr.T @ Xr)[1][:, 0]                 # plano que melhor passa pela costura
        if n @ N0 < 0: n = -n
        horizontal = abs(n[2]) > np.cos(np.radians(12))
        if horizontal: n = np.array([0.0, 0.0, np.sign(n[2])])                              # quase deitado: fica exatamente na horizontal
        X = Pq - c; d = X @ n                                               # >0: lado de j
        drim = float(np.abs(Xr @ n).max()); dmax = float(np.abs(d).max())
        if not horizontal and dmax > 1.2: return f"inclinado e ondulado ({dmax:.1f} mm): fica como está"   # só achata o que assenta na mesa ou já era quase plano
        if drim > max(1.5, 0.25 * np.sqrt(At)): return f"costura ondula demais ({drim:.1f} mm)"
        if dmax > max(6.0, 0.6 * np.sqrt(At)): return f"ondula demais ({dmax:.1f} mm)"
        A_ = np.cross(n, [0, 0, 1] if abs(n[2]) < 0.9 else [1, 0, 0]); A_ /= np.linalg.norm(A_); B_ = np.cross(n, A_)
        from shapely.geometry import Polygon as _P, LineString as _L
        from shapely.ops import unary_union as _uu, polygonize as _pz
        uvp = lambda P_: np.stack([(P_ - c) @ A_, (P_ - c) @ B_], 1)
        uv = uvp(Pq).reshape(-1, 3, 2); ub = uvp(Pu)
        _t = time.time(); DBG = os.environ.get('VOXELCUT_DEBUG_PLANO')
        pegada = _uu([p for p in (_P(t) for t in uv) if p.area > 1e-9]).buffer(0.5)            # tudo que a superfície de corte cobre
        contorno = _uu(list(_pz(_uu([_L(ub[list(b)]) for b in borda]))))                     # dentro da costura (linhas unidas: se cruzam na projeção)
        if contorno.is_empty or contorno.area < max(3.0, 0.08 * At): return f"costura não fecha (corte {At:.0f} mm2, contorno {contorno.area:.1f} mm2, {len(borda)} arestas de borda, coer {coer:.2f})"
        contorno = contorno.buffer(0.2)
        if DBG: print(f'   [{names[k]}|{names[j]}] corte {At:.0f} mm2, pegada {pegada.area:.0f}, contorno {contorno.area:.0f} ({time.time()-_t:.1f}s)', flush=True)

        def prisma(forma, z0, z1):
            rings = []
            for pg in (list(forma.geoms) if hasattr(forma, "geoms") else [forma]):
                if pg.is_empty: continue
                ext = np.asarray(pg.exterior.coords)[:-1]; rings.append(ext if _P(ext).exterior.is_ccw else ext[::-1])
                for hole in pg.interiors:
                    hh = np.asarray(hole.coords)[:-1]; rings.append(hh[::-1] if _P(hh).exterior.is_ccw else hh)
            return mf.Manifold.extrude(mf.CrossSection(rings, mf.FillRule.Positive), z1 - z0).translate((0, 0, z0)).transform(np.c_[A_, B_, n, c])
        Sd = prisma(pegada, 0.0, max(float(d.max()), 0.0) + 1.0)        # lado de j, sob tudo que o corte cobre
        Su = prisma(contorno, min(float(d.min()), 0.0) - 1.0, 0.0)      # lado de k, só dentro da costura
        Pk, Pj = pieces[k], pieces[j]
        un = lambda L: mf.Manifold.batch_boolean(L, mf.OpType.Add) if len(L) > 1 else (L[0] if L else mf.Manifold())
        pra_j, pra_k = Pk ^ Sd, Pj ^ Su
        nk = (Pk - Sd) + pra_k; nj = (Pj - Su) + pra_j
        S = Sd + Su
        return concluir(k, j, Pk, Pj, nk, nj, n, dmax, None)

    if PLANO:
        for k in sorted(p for p in pieces if p < ng):
            for j, Q in faces_corte(k).items():
                if j <= k or j >= ng: continue
                # cada contato separado (cada pata, a cauda encostada...) ganha o próprio plano
                Pq_ = Q.reshape(-1, 3); _, vid_ = np.unique(np.round(Pq_ / 1e-4).astype(np.int64), axis=0, return_inverse=True); vid_ = vid_.ravel()
                F_ = vid_.reshape(-1, 3); nv_ = int(vid_.max()) + 1; ee_ = np.r_[F_[:, [0, 1]], F_[:, [1, 2]]]
                _, cvq = connected_components(sp.coo_matrix((np.ones(len(ee_)), (ee_[:, 0], ee_[:, 1])), shape=(nv_, nv_)), directed=False)
                ct = cvq[F_[:, 0]]; partes = sorted(np.unique(ct), key=lambda c_: -(ct == c_).sum())
                for i_, c_ in enumerate(partes):
                    Qc = Q[ct == c_]
                    try:
                        r = aplainar(k, j, Qc)
                    except Exception as e:
                        r = f"erro {e}"
                        if os.environ.get("VOXELCUT_DEBUG_PLANO"): import traceback; traceback.print_exc()
                    if r == "pequeno" and len(partes) > 1: continue
                    print(f"flat cut {names[k]} | {names[j]}{f' #{i_ + 1}' if len(partes) > 1 else ''}: {r}")
        print(f"flat cuts done  ({time.time() - T0:.0f}s)")

else:
    NL = ng; VOID = None
for k, ms in direto.items():                                   # cascas inteiras entram na peça delas
    extra = mf.Manifold.batch_boolean(ms, mf.OpType.Add) if len(ms) > 1 else ms[0]
    pieces[k] = pieces[k] + extra if k in pieces else extra
    print(f"piece {names[k]}: {len(ms)} whole shell(s), volume {pieces[k].volume():.0f} mm3")
# ---------------------------------------------------------------- saída no formato de separate_seg (peças + tampas)
caps_json = {n: [] for n in names}
for k in range(ng):
    if k not in pieces:
        np.save(f"{wd}/part_{k}_v.npy", np.zeros((0, 3))); np.save(f"{wd}/part_{k}_t.npy", np.zeros((0, 3), int))
        parts.append(dict(name=names[k], tris=0, open_edges=0, nonmanifold=0, cap_tris=0)); continue
    m = pieces[k].to_mesh(); V = np.asarray(m.vert_properties)[:, :3].astype(np.float64); Fk = np.asarray(m.tri_verts).astype(np.int64)
    # triângulos que vieram da região (= faces de corte) x da superfície original
    rid = np.asarray(m.run_original_id); rix = np.asarray(m.run_index)
    src = np.zeros(len(Fk), np.int64)
    for r in range(len(rid)): src[rix[r] // 3:rix[r + 1] // 3] = rid[r]
    cut = (src != OID) & ~np.isin(src, list(DIRETO_IDS))
    np.save(f"{wd}/part_{k}_v.npy", V); np.save(f"{wd}/part_{k}_t.npy", Fk)
    parts.append(dict(name=names[k], tris=int(len(Fk)), open_edges=0, nonmanifold=0, cap_tris=int(cut.sum())))
    if not cut.any(): continue
    Q = V[Fk[cut]]; cen = Q.mean(1)
    # com qual peça essa face encosta: maior valor do campo harmônico (fora do sólido: rótulo da superfície mais próxima)
    ijk = np.clip(np.rint((cen - lo) / h).astype(int), 0, np.array([nx, ny, nz]) - 1)
    flat = np.ravel_multi_index(ijk.T, (nx, ny, nz)); pp = pos[flat]
    tgt = lab_near.ravel()[flat].astype(np.int64)                                           # fora do sólido: rótulo da superfície
    dn = pp >= 0; q = pp[dn]; tgt[dn] = np.where(TOPL1[q] == k, TOPL2[q], TOPL1[q])
    ruim = tgt < 0; tgt[ruim] = lab_near.ravel()[flat[ruim]]
    Fc = Fk[cut]
    for j in np.unique(tgt):
        if j < 0 or j == VOID or j <= k: continue                                                # cada par uma vez (a peça de índice menor)
        sel = np.where(tgt == j)[0]; Fs = Fc[sel]
        e = np.sort(np.r_[Fs[:, [0, 1]], Fs[:, [1, 2]], Fs[:, [2, 0]]], 1); fid = np.tile(np.arange(len(Fs)), 3)
        key = e[:, 0] * (len(V) + 1) + e[:, 1]; o = np.argsort(key); key, fid = key[o], fid[o]; same = key[1:] == key[:-1]
        _, comp = connected_components(sp.coo_matrix((np.ones(same.sum()), (fid[:-1][same], fid[1:][same])), shape=(len(Fs), len(Fs))), directed=False)
        for c_ in np.unique(comp):
            F = Fs[comp == c_]
            Qc = V[F]; fn = np.cross(Qc[:, 1] - Qc[:, 0], Qc[:, 2] - Qc[:, 0]); area = np.linalg.norm(fn, axis=1).sum() / 2
            if area < 4.0: continue                                                          # lasquinhas: não viram encaixe (ficam coladas)
            if np.linalg.norm(fn.sum(0)) < 0.4 * area: continue                              # película dobrada sobre si mesma (sem direção): idem
            N = fn.sum(0); N /= np.linalg.norm(N) + 1e-12                                        # para fora da peça k = para dentro da peça j
            u, inv = np.unique(F, return_inverse=True); o_ = V[u].mean(0)
            A2 = np.cross(N, [0, 0, 1] if abs(N[2]) < 0.9 else [1, 0, 0]); A2 /= np.linalg.norm(A2); B2 = np.cross(N, A2)
            d = (V[u] - o_) @ N
            caps_json[names[k]].append(dict(normal=N.tolist(), origin=o_.tolist(), A=A2.tolist(), B=B2.tolist(),
                                            uv=np.c_[(V[u] - o_) @ A2, (V[u] - o_) @ B2].tolist(), tris=inv.reshape(-1, 3).tolist(),
                                            area=float(area), dev=[float(d.min()), float(d.max())], h=np.round(d, 4).tolist(), target=names[j]))
            print(f"seam {names[k]} -> {names[j]}: cut face {area:.1f} mm2 (volumetric)")
for p in parts: print("PART", p)
json.dump(parts, open(f"{wd}/parts.json", "w"), indent=1)
json.dump(caps_json, open(f"{wd}/caps.json", "w"))
print(f"volumetric split done in {time.time() - T0:.0f}s")
