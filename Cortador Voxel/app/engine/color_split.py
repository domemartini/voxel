"""Separar por cor: transforma a pintura multicor (cor.npy) em peças.
Cada região conectada de uma cor vira uma peça; ilhas pequenas (área < min_area mm²) vão pra cor vizinha com a maior fronteira.
Saída: dict com groups (nome, cor, pontos) e o rótulo travado de cada triângulo (vai pro paint.npy, que o Separar respeita)."""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

NOMES = [("Preto", (20, 20, 20)), ("Branco", (245, 245, 245)), ("Cinza", (150, 150, 150)), ("Vermelho", (220, 50, 50)), ("Laranja", (245, 140, 30)),
         ("Amarelo", (250, 210, 40)), ("Dourado", (215, 180, 100)), ("Verde", (40, 180, 60)), ("Verde-água", (0, 200, 190)), ("Azul", (40, 90, 220)),
         ("Azul-claro", (90, 180, 240)), ("Roxo", (140, 60, 190)), ("Rosa", (245, 130, 200)), ("Marrom", (120, 75, 40)), ("Bege", (225, 200, 160)), ("Pele", (240, 190, 160))]


def nome_cor(hexa):
    r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
    return min(NOMES, key=lambda n: sum((a - c) ** 2 for a, c in zip(n[1], (r, g, b))))[0]


def adjacencia(t):
    """pares de triângulos vizinhos (compartilham aresta) e o comprimento da aresta fica por conta de quem chama"""
    nt = len(t); e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]]); e.sort(1)
    tri = np.tile(np.arange(nt), 3); key = e[:, 0].astype(np.int64) * (int(e.max()) + 1) + e[:, 1]
    o = np.argsort(key, kind="stable"); k = key[o]; same = np.flatnonzero(k[1:] == k[:-1])
    return tri[o][same], tri[o][same + 1], e[o][same]


def separar(v, t, cor, cores_hex, min_area=25.0):
    nt = len(t); a, b, ed = adjacencia(t)
    area = 0.5 * np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1)
    elen = np.linalg.norm(v[ed[:, 0]] - v[ed[:, 1]], axis=1)
    m = cor[a] == cor[b]
    G = coo_matrix((np.ones(m.sum()), (a[m], b[m])), shape=(nt, nt))
    nreg, reg = connected_components(G, directed=False)
    reg_cor = np.zeros(nreg, int); reg_cor[reg] = cor
    reg_area = np.bincount(reg, area, nreg)
    # funde ilhas pequenas na vizinha com a maior fronteira (repete até estabilizar)
    for _ in range(50):
        pequenas = np.flatnonzero((reg_area < min_area) & (reg_area > 0))
        if not len(pequenas): break
        ra, rb = reg[a], reg[b]; d = ra != rb
        fr = {}
        for x, y, L in zip(ra[d], rb[d], elen[d]):
            fr[(x, y)] = fr.get((x, y), 0) + L; fr[(y, x)] = fr.get((y, x), 0) + L
        viz = {}
        for (x, y), L in fr.items():
            if reg_area[x] < min_area and (x not in viz or L > viz[x][1]): viz[x] = (y, L)
        if not viz: break
        lut = np.arange(nreg)
        for x in sorted(viz, key=lambda r: reg_area[r]):          # das menores pras maiores, sem encadear no mesmo passo
            y = viz[x][0]
            if lut[y] != y: continue
            lut[x] = y
        reg = lut[reg]; reg_area = np.bincount(reg, area, nreg); reg_cor[lut != np.arange(nreg)] = -1
    vivas = [r for r in np.unique(reg) if reg_area[r] > 0]
    vivas.sort(key=lambda r: reg_area[r])                          # a maior fica por último ("o que sobrar")
    rot = np.full(nreg, -1, np.int16)
    for i, r in enumerate(vivas): rot[r] = i
    label = rot[reg]
    cont = {}; groups = []
    cen = v[t].mean(1)
    for i, r in enumerate(vivas):
        idx = np.flatnonzero(reg == r); c = int(np.bincount(cor[idx]).argmax())
        hexa = cores_hex.get(str(c), "#9CA3AF"); base = nome_cor(hexa); cont[base] = cont.get(base, 0) + 1
        # ponto: triângulo da região mais perto do centro dela (garante que o ponto cai na peça)
        cc = cen[idx]; k = idx[np.argmin(np.linalg.norm(cc - cc.mean(0), axis=1))]
        groups.append(dict(name=base, color=hexa, points=[cen[k].round(3).tolist()], area=round(float(reg_area[r]), 1), filamento=c))
    for g in groups:                                               # numera cores repetidas
        if cont[g["name"]] > 1:
            n = sum(1 for h in groups[:groups.index(g) + 1] if h["name"].split(" ")[0] == g["name"].split(" ")[0] and h is not g) + 1
            g["name"] = f"{g['name']} {n}"
    return groups, label


if __name__ == "__main__":
    import sys, json, time
    wd = sys.argv[1]; t0 = time.time()
    v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); cor = np.load(f"{wd}/cor.npy"); info = json.load(open(f"{wd}/info.json"))
    g, lab = separar(v, t, cor, info["cores"], float(sys.argv[2]) if len(sys.argv) > 2 else 25.0)
    print(f"{len(g)} peças em {time.time() - t0:.1f}s")
    for x in g: print("  ", x["name"], x["color"], x["area"], "mm²")
