"""Tampa lisa para um corte: em vez de ligar só os pontos da borda (triângulos longos que "amassam" a tampa),
preenche o contorno com uma malha fina e regular e dá a ela a forma de uma película esticada (superfície harmônica).
A borda continua sendo exatamente a costura da peça, então as duas peças do corte usam a mesma tampa e encaixam.

smooth_cap(uv, h, tris, L=None, proibidas=())
  uv: (n,2) borda projetada no plano do corte (na ordem do contorno) · h: (n,) altura de cada ponto da borda sobre o plano
  tris: triangulação inicial (CDT) só com os pontos da borda · proibidas: pares (i,j) da borda que não podem virar aresta
  devolve (uv_novos (k,2), h_novos (k,), tris (m,3)) — índices < n são a borda, >= n são os pontos novos"""
import heapq, math
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve


def _orient(P, t):
    a, b, c = P[t[0]], P[t[1]], P[t[2]]
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _incircle(a, b, c, d):
    """> 0 se d está dentro do círculo de (a,b,c) no sentido anti-horário"""
    m = np.array([[a[0] - d[0], a[1] - d[1], (a[0] - d[0]) ** 2 + (a[1] - d[1]) ** 2],
                  [b[0] - d[0], b[1] - d[1], (b[0] - d[0]) ** 2 + (b[1] - d[1]) ** 2],
                  [c[0] - d[0], c[1] - d[1], (c[0] - d[0]) ** 2 + (c[1] - d[1]) ** 2]])
    return np.linalg.det(m)


def smooth_cap(uv, h, tris, L=None, proibidas=(), max_pts=2500):
    n = len(uv); P = [tuple(p) for p in np.asarray(uv, float)]
    T = [list(map(int, t)) for t in tris]
    for t in T:                                               # tudo anti-horário no plano
        if _orient(P, t) < 0: t[1], t[2] = t[2], t[1]
    blen = np.linalg.norm(np.roll(uv, -1, 0) - uv, axis=1)
    area = abs(sum(_orient(P, t) for t in T)) / 2
    L = L or max(1.3 * float(np.median(blen)), math.sqrt(area / (0.43 * 1500)))
    bset = {tuple(sorted((i, (i + 1) % n))) for i in range(n)}
    forb = {tuple(sorted(e)) for e in proibidas}
    E = {}                                                    # aresta -> triângulos
    def add(ti):
        a, b, c = T[ti]
        for e in ((a, b), (b, c), (c, a)): E.setdefault(tuple(sorted(e)), set()).add(ti)
    def rem(ti):
        a, b, c = T[ti]
        for e in ((a, b), (b, c), (c, a)):
            s = E.get(tuple(sorted(e)))
            if s: s.discard(ti)
            if s is not None and not s: del E[tuple(sorted(e))]
    for i in range(len(T)): add(i)
    dist = lambda e: math.dist(P[e[0]], P[e[1]])
    heap = [(-(1e9 if e in forb else dist(e)), e) for e in E if e not in bset]; heapq.heapify(heap)

    # 1) divide as arestas internas longas (e as "proibidas") no meio: a borda nunca é mexida
    while heap and len(P) < n + max_pts:
        negl, e = heapq.heappop(heap)
        if e not in E or len(E[e]) != 2: continue
        if -negl < L and e not in forb: break
        a, b = e; t1, t2 = list(E[e])
        if abs(-negl - dist(e)) > 1e-9 and e not in forb: heapq.heappush(heap, (-dist(e), e)); continue      # prioridade velha
        if min(_orient(P, T[t1]), _orient(P, T[t2])) <= 1e-6 * dist(e) ** 2: continue                         # triângulo achatado: não divide
        m = len(P); P.append(((P[a][0] + P[b][0]) / 2, (P[a][1] + P[b][1]) / 2))
        for ti in (t1, t2):
            tri = T[ti]; k = [v for v in tri if v not in e][0]
            i = tri.index(k); x, y = tri[(i + 1) % 3], tri[(i + 2) % 3]   # tri = (k, x, y) anti-horário, aresta x-y = a-b
            rem(ti); T[ti] = [k, x, m]; add(ti)
            T.append([k, m, y]); add(len(T) - 1)
        for ne in {tuple(sorted(x)) for ti in (t1, t2, len(T) - 1, len(T) - 2) for x in ((T[ti][0], T[ti][1]), (T[ti][1], T[ti][2]), (T[ti][2], T[ti][0]))}:
            if ne not in bset and ne in E: heapq.heappush(heap, (-dist(ne), ne))

    # 2) troca de diagonais (Delaunay) para deixar os triângulos bem formados
    tol = 1e-6 * L * L
    for _ in range(30):
        mudou = 0
        for e in list(E):
            if e in bset or e not in E or len(E[e]) != 2: continue
            t1, t2 = list(E[e]); a, b = e
            c = [v for v in T[t1] if v not in e][0]; d = [v for v in T[t2] if v not in e][0]
            ne = tuple(sorted((c, d)))
            if ne in E or (c < n and d < n and ne in forb): continue
            tri = T[t1]; i = tri.index(c); x, y = tri[(i + 1) % 3], tri[(i + 2) % 3]
            if _incircle(P[c], P[x], P[y], P[d]) <= 1e-12: continue
            if _orient(P, [c, x, d]) <= tol or _orient(P, [c, d, y]) <= tol: continue   # quadrilátero não convexo (ou quase reto: evita triângulo achatado)
            rem(t1); rem(t2); T[t1] = [c, x, d]; T[t2] = [c, d, y]; add(t1); add(t2); mudou += 1
        if not mudou: break

    # 3) altura dos pontos novos: película esticada (Laplace com pesos cotangentes, borda fixa)
    P = np.array(P); T = np.array(T); N = len(P)
    I, J, W = [], [], []
    for t in T:
        for k in range(3):
            i, j, o = t[k], t[(k + 1) % 3], t[(k + 2) % 3]
            u, w = P[i] - P[o], P[j] - P[o]
            cr = abs(u[0] * w[1] - u[1] * w[0]); cot = (u @ w) / max(cr, 1e-12)
            cot = max(cot, 1e-3)
            I += [i, j]; J += [j, i]; W += [cot / 2, cot / 2]
    Wm = sp.coo_matrix((W, (I, J)), shape=(N, N)).tocsr()
    Lp = sp.diags(np.asarray(Wm.sum(1)).ravel()) - Wm
    inn = np.arange(n, N); h = np.asarray(h, float); um = h.ndim == 1
    H = np.zeros((N,) + h.shape[1:]); H[:n] = h
    if len(inn):
        Lii = Lp[inn][:, inn].tocsc(); rhs = -(Lp[inn][:, :n] @ H[:n])
        sol = spsolve(Lii, rhs); H[inn] = sol.reshape(H[inn].shape)
    return P[n:], H[n:], T


def disk_cap(P3, proibidas_fn=None):
    """costura muito curva (não dá pra achatar num plano): desenrola a borda num círculo, faz a malha fina ali
    e calcula a posição 3D de cada ponto novo como película esticada entre as bordas reais"""
    import shapely
    from shapely.geometry import Polygon
    n = len(P3); seg = np.linalg.norm(np.roll(P3, -1, 0) - P3, axis=1)
    ang = np.r_[0, np.cumsum(seg)[:-1]] / seg.sum() * 2 * np.pi
    uv = np.c_[np.cos(ang), np.sin(ang)]
    idx = {tuple(np.round(p, 12)): k for k, p in enumerate(uv)}
    tri = shapely.constrained_delaunay_triangles(Polygon(uv))
    T0 = np.array([[idx[tuple(np.round(q, 12))] for q in list(g.exterior.coords)[:3]] for g in tri.geoms])
    forb = proibidas_fn(T0) if proibidas_fn else ()
    U, X, T = smooth_cap(uv, P3, T0, proibidas=forb)
    return X, T
