"""Training bench: run the smart splitter on every model of a folder and score it against the designer's
own split when the file brings its parts already in assembled position.
usage: python treino.py <folder> [--levels medio,muitas] [--out <report dir>]
Ground truth = objects of a 3MF (or separate shells of an STL) that touch each other (assembled kit).
Scores (area weighted, on the view mesh):
  purity   = how much each suggested piece stays inside ONE designer piece (no piece spanning two parts)
  coverage = how much each designer piece stays inside ONE suggested piece (designer parts not chopped)
  F        = harmonic mean of both
writes <out>/report.json, <out>/report.html and one picture per model"""
import sys, os, json, subprocess, time, glob, numpy as np
from scipy.spatial import cKDTree
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components

HERE = os.path.dirname(os.path.abspath(__file__)); ENG = os.path.join(os.path.dirname(HERE), "engine")
args = sys.argv[1:]; folder = args[0]
LEVELS = (args[args.index("--levels") + 1] if "--levels" in args else "medio,muitas").split(",")
OUT = args[args.index("--out") + 1] if "--out" in args else os.path.join(folder, "_relatorio")
WORK = os.path.join(OUT, "_work"); os.makedirs(WORK, exist_ok=True)
PY = sys.executable


def ground_truth(wd):
    """designer parts per full-res triangle if they are assembled (touching), else None."""
    v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); part = np.load(f"{wd}/part.npy")
    ids = np.unique(part)
    if len(ids) < 2:   # one object: maybe an STL with several separate shells
        e = np.r_[t[:, [0, 1]], t[:, [1, 2]]]
        n, lab = connected_components(sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(v), len(v))), directed=False)
        part = lab[t[:, 0]]; ids, cnt = np.unique(part, return_counts=True)
        big = ids[cnt > 0.01 * len(t)]
        if len(big) < 2: return None, "sem peças do designer"
        part = np.where(np.isin(part, big), part, -1)
        ids = big
    # assembled? every part must touch (or overlap) another one
    samp = {k: v[np.unique(t[part == k])] for k in ids}
    samp = {k: s_[np.random.default_rng(0).choice(len(s_), min(len(s_), 4000), replace=False)] for k, s_ in samp.items()}
    diag = np.linalg.norm(v.max(0) - v.min(0))
    touching = 0
    for k in ids:
        others = np.vstack([samp[j] for j in ids if j != k])
        d = cKDTree(others).query(samp[k])[0].min()
        touching += d < max(1.0, 0.01 * diag)
    if touching < 0.8 * len(ids): return None, f"{len(ids)} peças, mas espalhadas (não montadas)"
    # variants stacked in the same place (option A / option B) are not an assembly
    for k in ids:
        others = np.vstack([samp[j] for j in ids if j != k])
        if (cKDTree(others).query(samp[k])[0] < 0.2).mean() > 0.3: return None, f"{len(ids)} peças, mas são variantes sobrepostas"
    return part, f"{len(ids)} peças do designer, montadas"


def score(wd, gt_full):
    v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy")
    vv = np.load(f"{wd}/view_v.npy"); vt = np.load(f"{wd}/view_t.npy"); pred = np.load(f"{wd}/smart_view.npy").astype(int)
    _, j = cKDTree(v[t].mean(1)).query(vv[vt].mean(1)); gt = gt_full[j]
    P = vv[vt]; area = np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1) / 2
    ok = (gt >= 0) & (pred >= 0); gt, pred, area = gt[ok], pred[ok], area[ok]
    gi = np.unique(gt, return_inverse=True)[1]; pi = np.unique(pred, return_inverse=True)[1]
    M = sp.coo_matrix((area, (pi, gi))).toarray()        # overlap area pred x gt
    purity = M.max(1).sum() / M.sum(); coverage = M.max(0).sum() / M.sum()
    return dict(purity=round(float(purity), 3), coverage=round(float(coverage), 3),
                F=round(float(2 * purity * coverage / (purity + coverage + 1e-9)), 3), pred=int(M.shape[0]), gt=int(M.shape[1]))


files = sorted(glob.glob(os.path.join(folder, "*.stl")) + glob.glob(os.path.join(folder, "*.3mf")))
if "--only" in args:
    keys = args[args.index("--only") + 1].lower().split(",")
    files = [f for f in files if any(k in os.path.basename(f).lower() for k in keys)]
report = []
for f in files:
    name = os.path.splitext(os.path.basename(f))[0]; wd = os.path.join(WORK, name)
    row = dict(file=os.path.basename(f))
    try:
        if not os.path.exists(f"{wd}/view_t.npy"):
            subprocess.run([PY, f"{ENG}/load_model.py", f, wd], check=True, capture_output=True)
            subprocess.run([PY, f"{ENG}/prepare_view.py", wd], check=True, capture_output=True)
        gt, why = ground_truth(wd); row["gabarito"] = why
        if gt is None and ("espalhadas" in why or "variantes" in why):
            row["gabarito"] += " - já vem cortado, pulei"; print(json.dumps(row, ensure_ascii=False), flush=True); report.append(row); continue
        for L in LEVELS:
            t0 = time.time()
            r = subprocess.run([PY, f"{ENG}/smart_split.py", wd, json.dumps({"level": L})], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0: row[L] = dict(erro=r.stdout[-300:] + r.stderr[-300:]); continue
            sm = json.load(open(f"{wd}/smart.json", encoding="utf-8"))
            res = dict(pecas=len(sm["pieces"]), segundos=round(time.time() - t0), nomes=[p["name"] for p in sm["pieces"]])
            if gt is not None: res.update(score(wd, gt))
            subprocess.run([PY, os.path.join(HERE, "render_smart.py"), wd, os.path.join(OUT, f"{name}_{L}.png")], capture_output=True)
            row[L] = res
        print(json.dumps(row, ensure_ascii=False), flush=True)
    except Exception as e:
        row["erro"] = str(e); print(json.dumps(row, ensure_ascii=False), flush=True)
    report.append(row)
    json.dump(report, open(os.path.join(OUT, "report.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)

# small html report
rows = []
for r in report:
    cells = [f"<td>{r['file']}<br><small>{r.get('gabarito', r.get('erro', ''))}</small></td>"]
    for L in LEVELS:
        x = r.get(L, {})
        sc = f"<b>F {x['F']:.2f}</b><br>pureza {x['purity']:.2f} · cobertura {x['coverage']:.2f}<br>" if "F" in x else ""
        img = f"{os.path.splitext(r['file'])[0]}_{L}.png"
        cells.append(f"<td>{sc}{x.get('pecas', '?')} peças · {x.get('segundos', '?')}s<br><img src='{img}' width=360></td>")
    rows.append("<tr>" + "".join(cells) + "</tr>")
Fs = [r[L]["F"] for r in report for L in LEVELS if isinstance(r.get(L), dict) and "F" in r[L]]
html = (f"<html><meta charset=utf-8><body style='font-family:sans-serif;background:#16181d;color:#ddd'><h2>Bancada do separador</h2>"
        f"<p>{len(report)} modelos · nota média F = {np.mean(Fs):.2f} ({len(Fs)} avaliações com gabarito)</p>" if Fs else
        f"<html><meta charset=utf-8><body style='font-family:sans-serif;background:#16181d;color:#ddd'><h2>Bancada do separador</h2><p>{len(report)} modelos (sem gabarito)</p>")
html += "<table border=1 cellpadding=6 style='border-collapse:collapse'><tr><th>modelo</th>" + "".join(f"<th>{L}</th>" for L in LEVELS) + "</tr>" + "".join(rows) + "</table></body></html>"
open(os.path.join(OUT, "report.html"), "w", encoding="utf-8").write(html)
print("relatorio:", os.path.join(OUT, "report.html"))
