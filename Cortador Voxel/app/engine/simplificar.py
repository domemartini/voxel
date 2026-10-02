"""Reduz triângulos de uma malha. Usa o fast_simplification (quádricas) quando dá; se o Windows bloquear a DLL dele
(Controle Inteligente de Aplicativos bloqueia _simplify.pyd em alguns PCs), cai num agrupamento de vértices em grade,
só com numpy: um pouco mais grosseiro, mas serve pra tela e pra análise."""
import os
import numpy as np

# se o Windows bloqueou a DLL uma vez, não tenta de novo (cada tentativa mostra o aviso "Parte deste aplicativo foi bloqueada")
_MARCA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sem_fast_simplification.txt")
_fs = None
if not os.path.exists(_MARCA):
    try:
        import fast_simplification as _fs
    except Exception as e:            # ImportError / OSError "DLL load failed" / bloqueio de política
        _fs = None
        try:
            open(_MARCA, "w", encoding="utf-8").write(f"fast_simplification não carregou: {e}\napague este arquivo para tentar de novo\n")
        except OSError:
            pass


def _grade(v, t, alvo):
    v = np.asarray(v, np.float64); t = np.asarray(t, np.int64)
    lo = v.min(0); ext = float(np.ptp(v, 0).max()) or 1.0
    a, b = ext / 4000, ext / 20                                  # busca o tamanho de célula que dá ~alvo triângulos
    best = None
    for _ in range(18):
        h = (a * b) ** 0.5
        c = np.floor((v - lo) / h).astype(np.int64)
        key = (c[:, 0] * 1000003 + c[:, 1]) * 1000003 + c[:, 2]
        uk, cl = np.unique(key, return_inverse=True)
        tt = cl[t]; ok = (tt[:, 0] != tt[:, 1]) & (tt[:, 1] != tt[:, 2]) & (tt[:, 0] != tt[:, 2]); tt = tt[ok]
        tt = np.unique(np.sort(tt, 1), axis=0, return_index=True)[1]
        n = len(tt)
        if n > alvo: a = h
        else: b = h; best = (h, cl)
        if best is not None and abs(n - alvo) < 0.05 * alvo: break
    h, cl = best if best is not None else (a, None)
    if cl is None:
        c = np.floor((v - lo) / h).astype(np.int64); cl = np.unique((c[:, 0] * 1000003 + c[:, 1]) * 1000003 + c[:, 2], return_inverse=True)[1]
    nc = int(cl.max()) + 1
    nv = np.zeros((nc, 3)); np.add.at(nv, cl, v); nv /= np.bincount(cl, minlength=nc)[:, None]
    tt = cl[t]; ok = (tt[:, 0] != tt[:, 1]) & (tt[:, 1] != tt[:, 2]) & (tt[:, 0] != tt[:, 2]); tt = tt[ok]
    _, idx = np.unique(np.sort(tt, 1), axis=0, return_index=True); tt = tt[np.sort(idx)]      # mantém a orientação
    usa = np.unique(tt); lut = np.full(nc, -1, np.int64); lut[usa] = np.arange(len(usa))
    return nv[usa].astype(np.float32), lut[tt].astype(np.int32)


def simplify(v, t, target_reduction):
    if target_reduction <= 0: return v, t
    if _fs is not None:
        try:
            return _fs.simplify(np.asarray(v, np.float32), np.asarray(t, np.int32), target_reduction=target_reduction)
        except Exception:
            pass
    return _grade(v, t, max(100, int(len(t) * (1 - target_reduction))))
