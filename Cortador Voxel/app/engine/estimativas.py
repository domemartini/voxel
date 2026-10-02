"""Estimativa por peça (aproximada: o fatiador dá o número exato): filamento (g e m), tempo, quanto de suporte e,
quando o arquivo veio pintado pra AMS, quanta purga e quantas trocas de cor a separação por cor economiza.
A peça é medida deitada como está nos pratos (layout.json); sem pratos, na melhor face pra deitar.
usage: python estimativas.py <workdir>
grava: workdir/estimativas.json"""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plates import read_stl, faces_boas

DENS = 1.24            # g/cm³ (PLA)
DIAM = 1.75            # mm do filamento
PAREDE = 0.84          # 2 perímetros de 0,42 mm
PREENCH = 0.15         # preenchimento
CAMADA = 0.2
PURGA_G = 0.2          # g por troca de cor no AMS (descarga típica)
VEL = dict(parede=6.0, preench=14.0, suporte=10.0)   # mm³/s médios (parede de figura é lenta)
SEG_CAMADA = 4.0       # troca de camada, retrações, viagens

wd = sys.argv[1]
pecas = json.load(open(f"{wd}/pieces.json", encoding="utf-8"))
nomes = [p["name"] for p in pecas]
if os.path.exists(f"{wd}/_build/Pinos.stl"): nomes.append("Pinos")
L = None
if os.path.exists(f"{wd}/layout.json") and os.path.getmtime(f"{wd}/layout.json") >= os.path.getmtime(f"{wd}/pieces.json"):
    L = {it["name"]: it for it in json.load(open(f"{wd}/layout.json", encoding="utf-8"))["itens"]}
SCALE = json.load(open(f"{wd}/info.json")).get("export_scale", 1.0) if os.path.exists(f"{wd}/info.json") else 1.0

out = []; zfaixa = {}
for nm in nomes:
    f = f"{wd}/_build/{nm}.stl"
    if not os.path.exists(f): continue
    V, T = read_stl(f); tri = V[T]
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]); area = 0.5 * np.linalg.norm(cr, axis=1)
    vol = abs(float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum()) / 6)
    zfaixa[nm] = (float(V[:, 2].min()), float(V[:, 2].max()))
    R = np.array(L[nm]["R"]) if L and nm in L else faces_boas(V, T)[0][0]
    P = V @ R.T; tp = P[T]; n = np.cross(tp[:, 1] - tp[:, 0], tp[:, 2] - tp[:, 0]); nn = n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-20)
    zmin = P[:, 2].min(); zc = tp[:, :, 2].mean(1)
    pend = (nn[:, 2] < -0.707) & (zc > zmin + 0.3)                       # pendurado mais de 45° e fora da mesa
    proj = area * np.abs(nn[:, 2])
    sup_vol = float((proj[pend] * (zc[pend] - zmin)).sum()) * 0.15       # suporte em árvore/grade: ~15% do volume embaixo
    sup_cm2 = float(proj[pend].sum()) / 100
    v_par = min(vol, float(area.sum()) * PAREDE); v_pre = (vol - v_par) * PREENCH
    g = DENS * (v_par + v_pre + sup_vol) / 1000
    m = (g / DENS * 1000) / (np.pi * (DIAM / 2) ** 2) / 1000
    alt = float(P[:, 2].max() - zmin)
    seg = v_par / VEL["parede"] + v_pre / VEL["preench"] + sup_vol / VEL["suporte"] + alt / CAMADA * SEG_CAMADA
    nivel = "nenhum" if sup_cm2 < 0.5 else "pouco" if sup_cm2 < 8 else "médio" if sup_cm2 < 30 else "muito"
    out.append(dict(name=nm, g=round(g, 1), m=round(m, 2), min=round(seg / 60), suporte=nivel, sup_cm2=round(sup_cm2, 1), alt_mm=round(alt * SCALE, 1)))

tot = dict(g=round(sum(p["g"] for p in out), 1), m=round(sum(p["m"] for p in out), 2), min=sum(p["min"] for p in out))
# purga: arquivo pintado pra AMS e peças de cores diferentes. Inteiro, cada camada com k cores troca k-1 vezes; separado, nenhuma.
purga = None
try:
    info = json.load(open(f"{wd}/info.json"))
    if info.get("cores") and os.path.exists(f"{wd}/cor.npy"):
        cores = {g_["name"]: g_["color"].lower() for g_ in json.load(open(f"{wd}/marks.json"))["groups"]}
        usadas = {nm: cores.get(nm) for nm in zfaixa if cores.get(nm)}
        if len(set(usadas.values())) > 1:
            z0 = min(a for a, _ in zfaixa.values()); z1 = max(b for _, b in zfaixa.values()); trocas = 0
            for z in np.arange(z0, z1, CAMADA / SCALE):
                k = len({c for nm, c in usadas.items() if zfaixa[nm][0] <= z <= zfaixa[nm][1]})
                trocas += max(k - 1, 0)                     # a camada seguinte começa na última cor usada
            purga = dict(trocas=int(trocas), g=round(trocas * PURGA_G))
except Exception as e:
    print("purga: não calculada", e)
json.dump(dict(pecas=out, total=tot, purga=purga, aproximado=True), open(f"{wd}/estimativas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"RESULT estimativas: {len(out)} peças, {tot['g']} g, {tot['m']} m, ~{tot['min'] // 60}h{tot['min'] % 60:02d}" + (f", purga evitada ~{purga['g']} g ({purga['trocas']} trocas)" if purga else ""))
