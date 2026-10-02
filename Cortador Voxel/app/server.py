"""Voxel Cut - local app server (projects + interactive cutter).
usage: pythonw server.py [--port 8770] [--auto-exit]
Projects live in ../projetos/<id>/ (v.npy, t.npy, marks, seg, ...). Viewer files in ./viewer."""
import sys, os, json, threading, subprocess, time, re, traceback, shutil, uuid, numpy as np
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from scipy.spatial import cKDTree

HERE = os.path.dirname(os.path.abspath(__file__)); ENG = os.path.join(HERE, "engine"); VIEWER = os.path.join(HERE, "viewer")
ROOT = os.path.dirname(HERE)

def data_dir(root):
    """where projects and generated files live: next to the program when it runs from a plain folder
    (it already has 'projetos'), otherwise in the user's Documents (installed program folder is not for user data)"""
    if os.environ.get("CORTADOR_DATA"): return os.environ["CORTADOR_DATA"]
    if os.path.isdir(os.path.join(root, "projetos")) and not os.path.exists(os.path.join(root, "instalado.txt")): return root
    docs = None
    try:
        import ctypes; buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0: docs = buf.value      # CSIDL_PERSONAL = Documents
    except Exception:
        pass
    return os.path.join(docs or os.path.join(os.path.expanduser("~"), "Documents"), "Voxel Cut")


DATA = data_dir(ROOT)
sys.path.insert(0, HERE)
import licenca
LIC = {"req": licenca.required(ROOT), "st": None, "t": 0.0}


def lic_status(force=False):
    if not LIC["req"]: return {"ok": True, "required": False}
    if force or LIC["st"] is None or time.time() - LIC["t"] > 600:
        LIC["st"] = dict(licenca.status((DATA,)), required=True); LIC["t"] = time.time()
    return LIC["st"]
args = sys.argv[1:]
PROJ = args[args.index("--projects") + 1] if "--projects" in args else os.path.join(DATA, "projetos"); GEN = os.path.join(DATA, "Arquivos gerados")
os.makedirs(PROJ, exist_ok=True)
PORT = int(args[args.index("--port") + 1]) if "--port" in args else 8770
AUTO_EXIT = "--auto-exit" in args
_pd = os.path.dirname(sys.executable)          # o motor roda no python.exe de console (na versão portátil o programa é "Voxel Cut.exe")
PY = os.path.join(_pd, "python.exe") if os.name == "nt" and os.path.exists(os.path.join(_pd, "python.exe")) else sys.executable.replace("pythonw.exe", "python.exe")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
NOWIN = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW
try:
    VERSAO = open(os.path.join(HERE, "versao.txt"), encoding="utf-8").read().strip()
except OSError:
    VERSAO = "dev"
state = {"versao": VERSAO, "busy": False, "stage": "pronto", "log": [], "error": None, "files": [], "seams_version": 0, "project": None}
lock = threading.Lock()
LAST_PING = [time.time()]


def log(msg):
    with lock:
        state["log"].append(time.strftime("%H:%M:%S ") + msg); state["log"] = state["log"][-200:]
    try:
        print(msg, flush=True)
    except Exception:
        pass


FILHOS = set()                  # cálculos do motor rodando agora (encerrados junto quando o Voxel fecha)
JANELAS = {}                    # janela aberta -> último sinal de vida
JA_TEVE_JANELA = [False]


def encerrar():
    """fecha o Voxel de verdade: para os cálculos em andamento e sai"""
    for f in list(FILHOS):
        try: f.kill()
        except Exception: pass
    os._exit(0)


def run(cmd, stage):
    state["stage"] = stage; log(f"> {stage}")
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=ENV, creationflags=NOWIN)
    FILHOS.add(p)
    tail = []
    for line in p.stdout:
        line = line.rstrip(); tail = (tail + [line])[-15:]
        if re.search(r"straight|pin\(s\)|magnet|dovetail|label|key\(s\)|hole|JOINT|figure piece|PIECE|blobs|base:|GROUP|LOOP|plane|painted|group \d|RESULT|plug|socket|glue|piece|plate|saved|WARNING|Error|Trace|error|seam|PART|sponge|smoothed|undo|refine|cut through|view mesh|done", line):
            log("  " + line[:300])
    if p.wait() != 0:
        log("\n".join(tail[-8:]))
        causa = next((l.strip() for l in reversed(tail) if l.strip() and not l.startswith(" ")), "")   # última linha do erro (ex.: ImportError ...)
        raise RuntimeError(f"{stage} falhou (código {p.returncode})" + (f": {causa[:220]}" if causa else ""))


def safe(s, d="peca"):
    return re.sub(r"[^\w\- ]", "", s).strip() or d


# ---------- projects
def pj(pid): return os.path.join(PROJ, pid)
def meta(pid):
    f = os.path.join(pj(pid), "project.json")
    return json.load(open(f, encoding="utf-8-sig")) if os.path.exists(f) else None
def save_meta(pid, m): json.dump(m, open(os.path.join(pj(pid), "project.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def list_projects():
    out = []
    for pid in os.listdir(PROJ):
        m = meta(pid)
        if not m or not os.path.exists(os.path.join(pj(pid), "view_map.npy")): continue
        d = pj(pid); mk = os.path.join(d, "marks.json")
        mt = max(os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d))
        groups = len(json.load(open(mk, encoding="utf-8"))["groups"]) if os.path.exists(mk) else 0
        out.append(dict(id=pid, name=m["name"], source=m.get("source", ""), modified=mt, groups=groups, height=m.get("height_mm"),
                        tris=m.get("tris"), separated=os.path.exists(os.path.join(d, "seg_summary.json")),
                        generated=os.path.exists(os.path.join(d, "pieces.json")), thumb=os.path.exists(os.path.join(d, "thumb.jpg")), pasta=m.get("pasta", "")))
    return sorted(out, key=lambda x: -x["modified"])


lock_open = threading.Lock()
CUR = {"id": None, "wd": None, "MESH": None, "vmap": None}
PAINT = {"tree": None, "t": None, "undo": [], "dirty": False}


def open_project(pid):
    wd = pj(pid)
    vv = np.load(f"{wd}/view_v.npy").astype(np.float32); vt = np.load(f"{wd}/view_t.npy").astype(np.uint32)
    CUR.update(id=pid, wd=wd, vmap=np.load(f"{wd}/view_map.npy"),
               MESH=np.array([len(vv), len(vt)], np.uint32).tobytes() + vv.tobytes() + vt.tobytes())
    PAINT.update(tree=None, t=None, undo=[], dirty=False); DEL.update(undo=[], comp=None)
    m = meta(pid)
    files = []
    if os.path.isdir(m.get("out_dir", "")) and os.path.exists(f"{wd}/pieces.json"):
        files = [f for f in sorted(os.listdir(m["out_dir"])) if f.lower().endswith((".stl", ".3mf"))]
    state.update(project=pid, log=[], error=None, files=files, stage="pronto", seams_version=0)
    log(f"projeto aberto: {m['name']}")


def job_import(src, name, height, upload_ext=None, upload_tmp=None):
    pid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]; wd = pj(pid)
    try:
        state.update(busy=True, error=None, log=[], files=[], project=None)
        os.makedirs(wd)
        if upload_ext:                                  # file came from drag and drop
            src_file = os.path.join(wd, "original" + upload_ext); shutil.move(upload_tmp, src_file); out_dir = os.path.join(prefs()["saida"], safe(name, "modelo"))
            template = src_file if upload_ext == ".3mf" else "-"
        else:
            src_file = src; out_dir = os.path.join(prefs()["saida"], safe(name, "modelo"))          # na pasta escolhida (antes ia pro lado do arquivo, ex.: Downloads)
            template = src if src.lower().endswith(".3mf") else "-"
        run([PY, f"{ENG}/load_model.py", src_file, wd], "lendo o arquivo")
        v = np.load(f"{wd}/v.npy"); info = json.load(open(f"{wd}/info.json"))
        h0 = float(v[:, 2].max() - v[:, 2].min()) * info.get("export_scale", 1.0)
        if height and height > 0:
            s = height / (v[:, 2].max() - v[:, 2].min()); np.save(f"{wd}/v.npy", v * s)
            info["export_scale"] = 1.0; info["prescale"] = s; json.dump(info, open(f"{wd}/info.json", "w"), indent=1)
            log(f"  escala: {h0:.1f} mm -> {height:.1f} mm de altura")
        run([PY, f"{ENG}/prepare_view.py", wd], "preparando a visualização")
        state["stage"] = "mapeando a malha"
        fv = np.load(f"{wd}/v.npy"); ft = np.load(f"{wd}/t.npy")
        vv = np.load(f"{wd}/view_v.npy"); vt = np.load(f"{wd}/view_t.npy")
        _, mp = cKDTree(fv[ft].mean(1)).query(vv[vt].mean(1)); np.save(f"{wd}/view_map.npy", mp.astype(np.int64))
        save_meta(pid, dict(name=name, source=src, created=time.time(), out_dir=out_dir, template=template,
                            height_mm=round(float(height) if height else h0, 1), tris=int(len(ft))))
        open_project(pid); state["stage"] = "projeto pronto"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e)); log(traceback.format_exc()[-600:])
        shutil.rmtree(wd, ignore_errors=True)
    finally:
        state["busy"] = False


# ---------- desfazer: antes de cada operação que muda o resultado, guarda uma cópia do estado (pilha, até 20 passos)
ESTADO_ARQS = ("seg.npy", "field.npy", "paint.npy", "paint_names.json", "marks.json", "seg_summary.json", "loops.json")


def instantaneo(nome):
    import glob
    wd = CUR["wd"]; base = f"{wd}/_desfazer"; os.makedirs(base, exist_ok=True)
    ns = sorted(int(x) for x in os.listdir(base) if x.isdigit()); n = (ns[-1] + 1) if ns else 1
    d = f"{base}/{n}"; os.makedirs(d)
    for f in ESTADO_ARQS:
        if os.path.exists(f"{wd}/{f}"): shutil.copyfile(f"{wd}/{f}", f"{d}/{f}")
    for f in glob.glob(f"{wd}/loop_*.npy"): shutil.copyfile(f, f"{d}/{os.path.basename(f)}")
    json.dump({"nome": nome}, open(f"{d}/_passo.json", "w", encoding="utf-8"), ensure_ascii=False)
    for velho in ns[:-19]: shutil.rmtree(f"{base}/{velho}", ignore_errors=True)


def desfazer_passo():
    import glob
    wd = CUR["wd"]; base = f"{wd}/_desfazer"
    ns = sorted(int(x) for x in os.listdir(base) if x.isdigit()) if os.path.isdir(base) else []
    if not ns: return None
    d = f"{base}/{ns[-1]}"
    try:                                                       # passos gravados pela 1.7.7 estão em cp1252 (ç de "peças")
        bruto = open(f"{d}/_passo.json", "rb").read()
        try: nome = json.loads(bruto.decode("utf-8")).get("nome", "")
        except UnicodeDecodeError: nome = json.loads(bruto.decode("cp1252")).get("nome", "")
    except Exception:
        nome = "último passo"
    for f in ESTADO_ARQS:
        if os.path.exists(f"{d}/{f}"): shutil.copyfile(f"{d}/{f}", f"{wd}/{f}")
        elif os.path.exists(f"{wd}/{f}"): os.remove(f"{wd}/{f}")
    for f in glob.glob(f"{wd}/loop_*.npy"): os.remove(f)
    for f in glob.glob(f"{d}/loop_*.npy"): shutil.copyfile(f, f"{wd}/{os.path.basename(f)}")
    shutil.rmtree(d, ignore_errors=True)
    for f in ("seg_prev.npy", "field_prev.npy"):                   # o desfazer antigo (um passo só) não vale mais
        if os.path.exists(f"{wd}/{f}"): os.remove(f"{wd}/{f}")
    PAINT.update(undo=[], dirty=False); state["seams_version"] += 1
    log(f"desfeito: {nome}")
    return nome


def job_desfazer():
    try:
        state.update(busy=True, error=None); state["desfeito"] = desfazer_passo(); state["stage"] = "desfeito"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


def job_segment(marks):
    wd = CUR["wd"]
    try:
        state.update(busy=True, error=None)
        instantaneo("separar peças")
        json.dump(marks, open(f"{wd}/marks.json", "w"), indent=1)
        run([PY, f"{ENG}/mincut_multi.py", wd], "separando (corte mínimo)")
        state["stage"] = "separação pronta"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e)); log(traceback.format_exc()[-500:])
    finally:
        state["busy"] = False


def job_straight(params):
    wd = CUR["wd"]
    try:
        state.update(busy=True, error=None)
        instantaneo("corte reto")
        json.dump(params, open(f"{wd}/straight_params.json", "w"))
        if os.path.exists(f"{wd}/straight_report.json"): os.remove(f"{wd}/straight_report.json")
        run([PY, f"{ENG}/straighten.py", wd, f"{wd}/straight_params.json"], "deixando o corte reto")
        state["stage"] = "corte reto"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


def job_smooth(params):
    wd = CUR["wd"]
    try:
        state.update(busy=True, error=None)
        if params.get("undo"):
            desfazer_passo()
        else:
            instantaneo("esponja")
            json.dump(params, open(f"{wd}/smooth_params.json", "w"))
            run([PY, f"{ENG}/smooth_seg.py", wd, f"{wd}/smooth_params.json"], "passando a esponja")
        state["stage"] = "costuras suavizadas"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


# ---------- manual painting (exact, on the full-resolution mesh)
# ---------- delete mask ("xadrez"): parts of the model that go to no piece at all
DEL = {"undo": [], "comp": None}


def del_mask():
    f = f"{CUR['wd']}/del.npy"; t = paint_data()["t"]
    d = np.load(f) if os.path.exists(f) else np.zeros(len(t), bool)
    return d if len(d) == len(t) else np.zeros(len(t), bool)


def comp_labels():
    """connected pieces of the full model (loose bits, floating junk)"""
    if DEL["comp"] is None:
        import scipy.sparse as sp
        from scipy.sparse.csgraph import connected_components
        P_ = paint_data(); t = P_["t"]
        e = np.r_[t[:, [0, 1]], t[:, [1, 2]]]
        _, lab = connected_components(sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(P_["nV"], P_["nV"])), directed=False)
        tl = lab[t[:, 0]]
        fv = np.load(f"{CUR['wd']}/v.npy"); Q = fv[t]
        area = np.linalg.norm(np.cross(Q[:, 1] - Q[:, 0], Q[:, 2] - Q[:, 0]), axis=1) / 2
        DEL["comp"] = (tl, np.bincount(tl, weights=area))
    return DEL["comp"]


def do_delete(body):
    P_ = paint_data(); d = del_mask(); erase = bool(body.get("erase")); idx = np.zeros(0, int)
    if body.get("ops"):
        for op in body["ops"]:
            if op.get("points"):
                hit = P_["tree"].query_ball_point(np.array(op["points"]), float(op["radius"]))
                idx = np.r_[idx, np.concatenate([np.asarray(x, int) for x in hit] + [np.zeros(0, int)])]
    if body.get("component") is not None:                      # the whole loose piece under the click
        tl, _ = comp_labels(); _, j = P_["tree"].query(np.array(body["component"]))
        idx = np.where(tl == tl[j])[0]
    if body.get("auto"):                                       # every small floating bit
        tl, carea = comp_labels(); frac = float(body.get("frac", 0.03))
        small = np.where(carea < frac * carea.max())[0]
        idx = np.where(np.isin(tl, small))[0]
    idx = np.unique(idx); idx = idx[d[idx] != (not erase)]
    if not len(idx): return 0, int(d.sum())
    DEL["undo"].append((idx, d[idx].copy())); DEL["undo"] = DEL["undo"][-30:]
    d[idx] = not erase; np.save(f"{CUR['wd']}/del.npy", d)
    return int(len(idx)), int(d.sum())


def undo_delete():
    if not DEL["undo"]: return 0
    d = del_mask(); idx, old = DEL["undo"].pop(); d[idx] = old; np.save(f"{CUR['wd']}/del.npy", d); return int(len(idx))


def paint_data():
    if PAINT["tree"] is None:
        fv = np.load(f"{CUR['wd']}/v.npy"); ft = np.load(f"{CUR['wd']}/t.npy")
        PAINT.update(t=ft, nV=len(fv), tree=cKDTree(fv[ft].mean(1)))
    return PAINT


def do_paint(ops):
    wd = CUR["wd"]; P = paint_data(); t = P["t"]
    ng = len(json.load(open(f"{wd}/marks.json"))["groups"])
    seg = np.load(f"{wd}/seg.npy").astype(np.int8) if os.path.exists(f"{wd}/seg.npy") else np.full(len(t), ng - 1, np.int8)
    F = np.load(f"{wd}/field.npy") if os.path.exists(f"{wd}/field.npy") else None
    if F is not None and F.shape != (P["nV"], ng): F = None
    pf = f"{wd}/paint.npy"
    paint = np.load(pf) if os.path.exists(pf) else np.full(len(t), -1, np.int8)
    if len(paint) != len(t): paint = np.full(len(t), -1, np.int8)
    total = 0; undo = []
    for op in ops:
        lab = int(op["label"]); r = float(op["radius"])
        if not op.get("points"): continue
        idx = np.unique(np.concatenate([np.asarray(x, int) for x in P["tree"].query_ball_point(np.array(op["points"]), r)] + [np.zeros(0, int)]))
        idx = idx[seg[idx] != lab]
        if op.get("skip"): idx = idx[~np.isin(seg[idx], [int(x) for x in op["skip"]])]   # hidden pieces are not painted
        if not len(idx): continue
        idx2 = np.unique(np.concatenate([np.asarray(x, int) for x in P["tree"].query_ball_point(np.array(op["points"]), r)] + [np.zeros(0, int)]))
        idx2 = idx2[paint[idx2] != lab]
        if op.get("skip"): idx2 = idx2[~np.isin(seg[idx2], [int(x) for x in op["skip"]])]
        undo.append((idx, seg[idx].copy(), None if F is None else (np.unique(t[idx]), F[np.unique(t[idx])].copy()), idx2, paint[idx2].copy()))
        seg[idx] = lab; paint[idx2] = lab
        if F is not None:
            vv = np.unique(t[idx]); F[vv] = 0; F[vv, lab] = 1
        total += len(idx)
    if total:
        PAINT["undo"].append(undo); PAINT["undo"] = PAINT["undo"][-30:]
        np.save(f"{wd}/seg.npy", seg); np.save(pf, paint); save_paint_names()
        if F is not None: np.save(f"{wd}/field.npy", F.astype(np.float32))
        PAINT["dirty"] = True
    return total


def do_color_split(params):
    """Separar por cor: cada região de cor (ou cada cor) vira uma peça, travada como pintura à mão; depois o Separar só confirma."""
    sys.path.insert(0, ENG); import color_split
    wd = CUR["wd"]; info = json.load(open(f"{wd}/info.json"))
    v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); cor = np.load(f"{wd}/cor.npy")
    diag = float(np.linalg.norm(v.max(0) - v.min(0)))
    min_area = float(params.get("min_area") or max(10.0, (diag / 100) ** 2 * 4))      # ilhas menores que isso vão pra cor vizinha
    instantaneo("separar por cor")
    groups, lab = color_split.separar(v, t, cor, info["cores"], min_area)
    if params.get("modo") == "cor":                   # uma peça por cor (várias ilhas no mesmo STL)
        por = {}
        for i, g in enumerate(groups): por.setdefault(g["filamento"], []).append(i)
        ordem = sorted(por, key=lambda f: sum(groups[i]["area"] for i in por[f]))
        lut = np.zeros(len(groups), np.int16); novos = []
        for j, f in enumerate(ordem):
            idx = por[f]; lut[idx] = j; g0 = groups[idx[-1]]
            novos.append(dict(name=color_split.nome_cor(g0["color"]), color=g0["color"], points=[p for i in idx for p in groups[i]["points"]],
                              area=round(sum(groups[i]["area"] for i in idx), 1), filamento=f))
        groups, lab = novos, lut[lab]
    if len(groups) > 120: return {"error": f"{len(groups)} regiões de cor: é demais. Use 'Uma peça por cor'."}
    for f in ("seg.npy", "field.npy"):                   # a separação anterior não vale mais
        if os.path.exists(f"{wd}/{f}"): os.remove(f"{wd}/{f}")
    np.save(f"{wd}/paint.npy", lab.astype(np.int8)); PAINT.update(undo=[], dirty=True)
    marks = {"groups": [dict(name=g["name"], color=g["color"], points=g["points"]) for g in groups], "planes": [], "strokes": []}
    json.dump(marks, open(f"{wd}/marks.json", "w"), indent=1); save_paint_names()
    log(f"separar por cor: {len(groups)} peças ({params.get('modo') or 'regioes'}, ilhas < {min_area:.0f} mm² juntadas)")
    return {"ok": True, "groups": marks["groups"], "areas": [g["area"] for g in groups]}


def save_paint_names():
    names = [g["name"] for g in json.load(open(f"{CUR['wd']}/marks.json"))["groups"]]
    json.dump(names, open(f"{CUR['wd']}/paint_names.json", "w"))


def remap_paint(new_groups):
    """pieces renamed/reordered/removed: keep hand painting attached to the right piece (by name)."""
    wd = CUR["wd"]; pf = f"{wd}/paint.npy"; nf = f"{wd}/paint_names.json"
    if not (os.path.exists(pf) and os.path.exists(nf)): return
    old = json.load(open(nf)); new = [g["name"] for g in new_groups]
    if old == new: return
    if len(old) == len(new) and len(set(old) & set(new)) < len(new):   # same count, some renamed -> keep by position
        pass
    else:
        paint = np.load(pf); lut = np.full(max(len(old), 1) + 1, -1, np.int8)
        for i, n in enumerate(old):
            if n in new: lut[i] = new.index(n)
        m = paint >= 0; paint[m] = lut[paint[m]]; np.save(pf, paint)
    json.dump(new, open(nf, "w"))


def clear_paint():
    for f in ("paint.npy", "paint_names.json"):
        if os.path.exists(f"{CUR['wd']}/{f}"): os.remove(f"{CUR['wd']}/{f}")
    PAINT["undo"] = []


def undo_paint():
    wd = CUR["wd"]
    if not PAINT["undo"]: return 0
    seg = np.load(f"{wd}/seg.npy"); F = np.load(f"{wd}/field.npy") if os.path.exists(f"{wd}/field.npy") else None
    n = 0
    pf = f"{wd}/paint.npy"; paint = np.load(pf) if os.path.exists(pf) else None
    for idx, old, fold, pidx, pold in reversed(PAINT["undo"].pop()):
        seg[idx] = old; n += len(idx)
        if paint is not None and len(paint) == len(seg): paint[pidx] = pold
        if F is not None and fold is not None: F[fold[0]] = fold[1]
    np.save(f"{wd}/seg.npy", seg)
    if paint is not None: np.save(pf, paint)
    if F is not None: np.save(f"{wd}/field.npy", F)
    PAINT["dirty"] = True; return n


def refresher():
    while True:
        if PAINT["dirty"] and not state["busy"] and CUR["wd"]:
            PAINT["dirty"] = False
            r = subprocess.run([PY, f"{ENG}/seams_refresh.py", CUR["wd"]], capture_output=True, text=True, env=ENV, creationflags=NOWIN)
            if r.returncode == 0: state["seams_version"] += 1
            else: log("ERRO ao atualizar costuras: " + r.stderr[-300:])
        if AUTO_EXIT:
            agora = time.time()
            for w_, t_ in list(JANELAS.items()):
                if agora - t_ > 15: JANELAS.pop(w_, None)           # janela que parou de dar sinal (travou, foi fechada à força)
            if JA_TEVE_JANELA[0] and not JANELAS: encerrar()           # a última janela fechou: encerra
            if not JA_TEVE_JANELA[0] and agora - LAST_PING[0] > 120: encerrar()   # a janela nunca abriu
        time.sleep(0.4)


threading.Thread(target=refresher, daemon=True).start()


def seams_payload():
    wd = CUR["wd"]
    if not os.path.exists(f"{wd}/loops.json"): return []
    out = []
    for l in json.load(open(f"{wd}/loops.json")):
        f = f"{wd}/{l['file']}"
        if not os.path.exists(f): continue
        p = np.load(f)
        if len(p) > 800: p = p[np.linspace(0, len(p) - 1, 800).astype(int)]
        out.append({"a": l["a"], "b": l["b"], "simple": l.get("simple", True), "pts": np.round(p, 3).ravel().tolist()})
    return out


JUNTAS = "2026-10-01 ímã + rabo de andorinha + número do corte"   # muda quando só os encaixes mudam: refaz os encaixes, não a separação
MOTOR = "2026-09-30g volumétrica + corte reto por contato e por costura + parede do rebaixo abaixo do corte"                 # muda quando o motor de corte muda: as peças guardadas são refeitas


def build_signature(wd, params):
    """what the pieces depend on: segmentation state + joint settings"""
    sig = {"joints": params.get("joints") or {}, "min": params.get("plug_min_area", 8), "motor": MOTOR, "juntas": JUNTAS}
    for f in ("seg.npy", "field.npy", "paint.npy", "marks.json", "del.npy"):
        fp = f"{wd}/{f}"; sig[f] = os.path.getmtime(fp) if os.path.exists(fp) else 0
    return sig


def build_pieces(params):
    """separate + joints into workdir/_build (no files for the user yet). Reuses the last build if nothing changed."""
    wd = CUR["wd"]; m = meta(CUR["id"]); B = f"{wd}/_build"
    marks = json.load(open(f"{wd}/marks.json")); G = marks["groups"]
    used = set(); fixed = []
    for k, g in enumerate(G):                          # safe, unique file names
        n = safe(g["name"], f"parte{k + 1}"); base = n; i = 2
        while n.lower() in used: n = f"{base} {i}"; i += 1
        used.add(n.lower()); fixed.append(n); g["name"] = n
    if [g["name"] for g in json.load(open(f"{wd}/marks.json"))["groups"]] != fixed:
        json.dump(marks, open(f"{wd}/marks.json", "w"), indent=1)
    sig = build_signature(wd, params)
    if os.path.exists(f"{B}/sig.json") and json.load(open(f"{B}/sig.json")) == json.loads(json.dumps(sig)) and os.path.exists(f"{wd}/pieces.json"):
        log("  nada mudou desde a visualização: usando as peças já calculadas")
        return fixed
    figs = [{"name": fixed[k], "seed": g["points"][0] if g["points"] else [0, 0, 0], "seeds": g["points"]} for k, g in enumerate(G[:-1])]
    cfg = {"project": safe(m["name"], "modelo"), "out_dir": B, "joints": params.get("joints") or {},
           "plug_min_area": float(params.get("plug_min_area", 8)), "figures": figs, "base_name": fixed[-1]}
    json.dump(cfg, open(f"{wd}/config.json", "w"), indent=1)
    if os.path.isdir(B): shutil.rmtree(B, ignore_errors=True)
    os.makedirs(B, exist_ok=True)
    sep = "separate_seg.py" if os.environ.get("VOXELCUT_MOTOR") == "superficie" else "separate_vol.py"   # volumétrico (volta sozinho pro de superfície se precisar)
    # a separação (o passo demorado) só depende das marcações e do corte reto; mudou só pino/rebaixo? refaz só os encaixes
    sep_sig = {k: v for k, v in sig.items() if k not in ("joints", "min", "juntas")}; sep_sig["plano"] = bool((params.get("joints") or {}).get("plano", True))
    sf = f"{wd}/sep_sig.json"; sep_sig = json.loads(json.dumps(sep_sig))
    pronto = (os.path.exists(sf) and json.load(open(sf)) == sep_sig and os.path.exists(f"{wd}/caps.json") and os.path.exists(f"{wd}/parts.json")
              and all(os.path.exists(f"{wd}/part_{k}_v.npy") for k in range(len(fixed))))
    if pronto: log("  separação já calculada: refazendo só os encaixes")
    else:
        if os.path.exists(sf): os.remove(sf)
        run([PY, f"{ENG}/{sep}", wd], "montando as peças")
        json.dump(sep_sig, open(sf, "w"))
    run([PY, f"{ENG}/finish.py", wd], "rebaixos, pinos e encaixes")
    json.dump(sig, open(f"{B}/sig.json", "w"))
    return fixed


def estimar():
    """filamento, tempo, suporte e purga por peça (aproximado). Nunca derruba o resto."""
    try: run([PY, f"{ENG}/estimativas.py", CUR["wd"]], "estimando filamento e tempo")
    except Exception as e: log("  estimativa não calculada: " + str(e))


def job_preview(params):
    try:
        state.update(busy=True, error=None)
        build_pieces(params); estimar()
        state["joints"] = json.load(open(f"{CUR['wd']}/joints.json", encoding="utf-8")) if os.path.exists(f"{CUR['wd']}/joints.json") else []
        state["previewed"] = True; state["stage"] = "encaixes prontos pra conferir"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


def job_finalize(params):
    wd = CUR["wd"]; m = meta(CUR["id"])
    try:
        state.update(busy=True, error=None, files=[])
        OUT = m["out_dir"]; NAME = safe(m["name"], "modelo"); B = f"{wd}/_build"
        fmt = params.get("formats") or {"stl": True, "3mf": params.get("plates", True)}
        fixed = build_pieces(params)
        state["joints"] = json.load(open(f"{wd}/joints.json", encoding="utf-8")) if os.path.exists(f"{wd}/joints.json") else []
        os.makedirs(OUT, exist_ok=True)
        names = fixed + (["Pinos"] if os.path.exists(f"{B}/Pinos.stl") else [])
        files = []
        if fmt.get("stl", True):
            state["stage"] = "gravando os STL"
            for n in names:
                shutil.copyfile(f"{B}/{n}.stl", f"{OUT}/{n}.stl"); files.append(f"{n}.stl")
            log(f"  {len(names)} STL gravados em {OUT}")
        if fmt.get("3mf", True):
            ensure_layout(params)
            export_3mf(f"{OUT}/{NAME} - pratos.3mf")
            files.append(f"{NAME} - pratos.3mf")
        estimar()
        state["files"] = files; state["stage"] = "arquivos prontos"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


def layout_opts(extra=None):
    m = meta(CUR["id"]); o = {"template": m.get("template", "-")}
    o.update(extra or {}); return o


def ensure_layout(params):
    """pratos: calcula se ainda não tem, ou se as peças mudaram (o que o usuário arrumou fica)"""
    wd = CUR["wd"]; f = f"{wd}/layout.json"
    names = [p["name"] for p in json.load(open(f"{wd}/pieces.json", encoding="utf-8"))] + (["Pinos"] if os.path.exists(f"{wd}/_build/Pinos.stl") else [])
    if os.path.exists(f):
        L = json.load(open(f, encoding="utf-8"))
        if sorted(it["name"] for it in L["itens"]) == sorted(names) and os.path.getmtime(f) >= os.path.getmtime(f"{wd}/pieces.json"): return
    run([PY, f"{ENG}/plates.py", wd, json.dumps(layout_opts(params.get("pratos")))], "arrumando as peças nos pratos")


def job_layout(params):
    try:
        state.update(busy=True, error=None)
        if params.get("joints") is not None: build_pieces(params)
        if params.get("auto"):
            run([PY, f"{ENG}/plates.py", CUR["wd"], json.dumps(layout_opts(params.get("pratos")))], "arrumando as peças nos pratos")
        else:
            ensure_layout(params)
        estimar()
        state["stage"] = "pratos prontos"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


def arquivos_velhos():
    """o que já está na pasta ficou pra trás? (mexeu nos pratos ou refez os encaixes depois de Gerar arquivos)
    -> {"3mf": caminho} se o 3MF dos pratos precisa ser refeito, {"stl": True} se as peças mudaram"""
    wd = CUR["wd"]; m = meta(CUR["id"]); OUT = m["out_dir"]; fs_ = state.get("files") or []
    tm = [f for f in fs_ if f.endswith(" - pratos.3mf")]
    out = {}
    pf = f"{wd}/pieces.json"; lf = f"{wd}/layout.json"
    if tm and os.path.exists(os.path.join(OUT, tm[0])):
        t = os.path.getmtime(os.path.join(OUT, tm[0]))
        if any(os.path.exists(x) and os.path.getmtime(x) > t + 1 for x in (pf, lf)): out["3mf"] = os.path.join(OUT, tm[0])
    stls = [f for f in fs_ if f.lower().endswith(".stl") and os.path.exists(f"{wd}/_build/{f}")]     # peça que mudou de nome: só Gerar arquivos resolve
    if stls and os.path.exists(pf) and os.path.exists(os.path.join(OUT, stls[0])) and os.path.getmtime(pf) > os.path.getmtime(os.path.join(OUT, stls[0])) + 1: out["stl"] = True
    return out


def atualizar_arquivos():
    """refaz na pasta só o que ficou velho (3MF com os pratos de agora, STLs das peças de agora)"""
    v = arquivos_velhos()
    if not v: return False
    wd = CUR["wd"]; m = meta(CUR["id"]); OUT = m["out_dir"]; B = f"{wd}/_build"
    if v.get("stl"):
        for f in [f for f in (state.get("files") or []) if f.lower().endswith(".stl")]:
            if os.path.exists(f"{B}/{f}"): shutil.copyfile(f"{B}/{f}", os.path.join(OUT, f))
        log("  STL atualizados na pasta")
    if v.get("3mf"):
        ensure_layout({}); export_3mf(v["3mf"]); log("  3MF atualizado com os pratos de agora")
    return True


def export_3mf(out, extra=()):
    wd = CUR["wd"]; B = f"{wd}/_build"; m = meta(CUR["id"])
    L = json.load(open(f"{wd}/layout.json", encoding="utf-8"))
    parts = [f"{it['name']}={B}/{it['name']}.stl" for it in L["itens"]]
    run([PY, f"{ENG}/export_3mf_plates.py", out, m.get("template", "-")] + parts + ["--layout", f"{wd}/layout.json"] + list(extra), "gravando o 3MF com os pratos")


def job_export(params):
    """exportar só um prato ou só uma peça (o projeto inteiro é o Gerar arquivos)"""
    wd = CUR["wd"]; m = meta(CUR["id"])
    try:
        state.update(busy=True, error=None)
        OUT = m["out_dir"]; NAME = safe(m["name"], "modelo"); B = f"{wd}/_build"
        build_pieces(params); ensure_layout(params); os.makedirs(OUT, exist_ok=True)
        novos = []
        if params.get("what") == "prato":
            k = int(params["prato"]); fn = f"{NAME} - prato {k}.3mf"
            export_3mf(f"{OUT}/{fn}", ["--prato", str(k)]); novos.append(fn)
        elif params.get("what") == "peca":
            n = params["name"]; fn = f"{NAME} - {safe(n)}.3mf"
            export_3mf(f"{OUT}/{fn}", ["--peca", n]); novos.append(fn)
            shutil.copyfile(f"{B}/{n}.stl", f"{OUT}/{safe(n)}.stl"); novos.append(f"{safe(n)}.stl")
        state["files"] = sorted(set((state.get("files") or []) + novos)); state["exported"] = novos
        state["stage"] = "exportado"; log("  exportado: " + ", ".join(novos))
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


PALETTE = ["#f2c12e", "#9ca3af", "#3b82f6", "#ef4444", "#22c55e", "#a855f7", "#f97316", "#14b8a6", "#ec4899"]


def do_object_split():
    """arquivo com vários objetos (kit já separado pelo designer): cada objeto vira uma peça"""
    wd = CUR["wd"]; info = json.load(open(f"{wd}/info.json"))
    v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); part = np.load(f"{wd}/part.npy")
    obs = sorted(set(part.tolist()))
    if len(obs) < 2: return {"error": "este arquivo tem um objeto só"}
    if len(obs) > 120: return {"error": f"{len(obs)} objetos: é demais"}
    area = 0.5 * np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1)
    cen = v[t].mean(1); ar = {o: float(area[part == o].sum()) for o in obs}
    obs.sort(key=lambda o: ar[o])                       # o maior fica por último ("o que sobrar")
    nomes = info.get("objects") or {}; usados = set(); groups = []; lab = np.zeros(len(t), np.int8)
    cores = info.get("cores") or {}
    cor = np.load(f"{wd}/cor.npy") if os.path.exists(f"{wd}/cor.npy") else None
    for i, o in enumerate(obs):
        idx = np.flatnonzero(part == o); lab[idx] = i
        n0 = re.sub(r"\.(stl|obj|3mf|step)$", "", nomes.get(str(o), "") or "", flags=re.I)
        n0 = safe(n0, f"Peça {i + 1}"); n = n0; k = 2
        while n.lower() in usados: n = f"{n0} {k}"; k += 1
        usados.add(n.lower())
        cc = cen[idx]; kk = idx[np.argmin(np.linalg.norm(cc - cc.mean(0), axis=1))]
        c = cores.get(str(int(np.bincount(cor[idx]).argmax()))) if cor is not None else None
        groups.append(dict(name=n, color=c or PALETTE[i % len(PALETTE)], points=[cen[kk].round(3).tolist()]))
    instantaneo("cada objeto vira uma peça")
    for f in ("seg.npy", "field.npy"):
        if os.path.exists(f"{wd}/{f}"): os.remove(f"{wd}/{f}")
    np.save(f"{wd}/paint.npy", lab); PAINT.update(undo=[], dirty=True)
    marks = {"groups": groups, "planes": [], "strokes": []}
    json.dump(marks, open(f"{wd}/marks.json", "w"), indent=1); save_paint_names()
    log(f"um objeto por peça: {len(groups)} peças")
    return {"ok": True, "groups": groups}


def job_smart(params):
    wd = CUR["wd"]
    try:
        state.update(busy=True, error=None)
        run([PY, f"{ENG}/smart_split.py", wd, json.dumps(params)], "analisando o modelo")
        state["stage"] = "sugestão pronta"
    except Exception as e:
        state["error"] = str(e); log("ERRO: " + str(e))
    finally:
        state["busy"] = False


PREF_F = os.path.join(DATA, "preferencias.json")


def prefs():
    try: d = json.load(open(PREF_F, encoding="utf-8"))
    except Exception: d = {}
    d.setdefault("saida", GEN)                                   # pasta padrão dos arquivos prontos
    return d


def salvar_prefs(d):
    os.makedirs(DATA, exist_ok=True); json.dump(d, open(PREF_F, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def pick_folder(inicial=""):
    if sys.platform == "darwin":
        r = subprocess.run(["osascript", "-e", 'POSIX path of (choose folder with prompt "Onde salvar os arquivos prontos")'], capture_output=True, text=True)
        return r.stdout.strip().rstrip("/") if r.returncode == 0 else ""
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
    p = filedialog.askdirectory(parent=r, title="Onde salvar os arquivos prontos", initialdir=inicial if os.path.isdir(inicial) else None)
    r.destroy(); return os.path.normpath(p) if p else ""


def pick_file():
    if sys.platform == "darwin":                  # Mac: janela nativa do Finder (tkinter não roda fora da thread principal)
        r = subprocess.run(["osascript", "-e", 'POSIX path of (choose file with prompt "Abrir modelo 3D (.stl ou .3mf)" of type {"stl", "3mf", "public.item"})'],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    import tkinter as tk
    from tkinter import filedialog
    r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
    p = filedialog.askopenfilename(parent=r, title="Abrir modelo 3D", filetypes=[("Modelos 3D", "*.stl *.3mf"), ("Todos", "*.*")])
    r.destroy(); return p


def calc_sugestao(pid):
    """o que o Voxel Cut já sabe do projeto pra calculadora: gramas por cor e tempo (estimativa) + nome"""
    m = meta(pid)
    if not m: return None
    d = pj(pid); out = {"nome": m["name"], "fils": [], "min": 0}
    ef = f"{d}/estimativas.json"
    if not os.path.exists(ef): return out
    e = json.load(open(ef, encoding="utf-8")); out["min"] = int(e["total"]["min"])
    cores = {}
    try:
        info = json.load(open(f"{d}/info.json"))
        if info.get("cores") and os.path.exists(f"{d}/cor.npy"):                 # arquivo pintado pra AMS: um filamento por cor
            cores = {g["name"]: g["color"] for g in json.load(open(f"{d}/marks.json"))["groups"]}
    except Exception:
        pass
    por = {}
    for p_ in e["pecas"]:
        c = cores.get(p_["name"]) if cores else None
        por[c] = por.get(c, 0) + p_["g"]
    if len(por) > 1:
        out["fils"] = [dict(nome=f"Cor {i + 1}", cor=c, g=round(g)) for i, (c, g) in enumerate(sorted(por.items(), key=lambda x: -x[1]))]
    else:
        out["fils"] = [dict(nome="Filamento", cor=None, g=round(sum(por.values())))]
    return out


def fatiadores():
    """fatiadores instalados neste computador: [(nome, executável)]"""
    import glob
    if sys.platform == "darwin":
        apps = [("Bambu Studio", "BambuStudio.app"), ("OrcaSlicer", "OrcaSlicer.app"), ("PrusaSlicer", "PrusaSlicer.app"), ("UltiMaker Cura", "UltiMaker Cura.app"), ("Creality Print", "Creality Print.app")]
        return [(n, f"/Applications/{a}") for n, a in apps if os.path.isdir(f"/Applications/{a}")]
    bases = [os.environ.get(k, "") for k in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")]
    if os.environ.get("LOCALAPPDATA"): bases += [os.environ["LOCALAPPDATA"], os.path.join(os.environ["LOCALAPPDATA"], "Programs")]
    bases = [b for b in dict.fromkeys(bases) if b]
    alvo = [("Bambu Studio", ("Bambu Studio", "bambu-studio.exe")), ("OrcaSlicer", ("OrcaSlicer", "orca-slicer.exe")), ("PrusaSlicer", ("Prusa3D", "PrusaSlicer", "prusa-slicer.exe")),
            ("UltiMaker Cura", ("UltiMaker Cura*", "UltiMaker-Cura.exe")), ("Creality Print", ("Creality", "Creality Print*", "CrealityPrint.exe")),
            ("ElegooSlicer", ("ElegooSlicer", "elegoo-slicer.exe")), ("Anycubic Slicer", ("AnycubicSlicerNext", "AnycubicSlicerNext.exe"))]
    achados = []
    for nome, rel in alvo:
        for b in bases:
            g = sorted(glob.glob(os.path.join(b, *rel)))
            if g: achados.append((nome, g[-1])); break
    return achados


def abrir_no_fatiador(nome, arquivos):
    for n, exe in fatiadores():
        if n == nome:
            if sys.platform == "darwin": subprocess.Popen(["open", "-a", exe] + arquivos)
            else: subprocess.Popen([exe] + arquivos, creationflags=0x00000008)          # DETACHED: continua aberto se o Voxel fechar
            return True
    return False


def abrir_arquivo(f):
    if os.name == "nt": os.startfile(f)
    elif sys.platform == "darwin": subprocess.Popen(["open", f])
    else: subprocess.Popen(["xdg-open", f])


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)): body = json.dumps(body).encode()
        elif isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def follow_window(self):
        """each viewer window sends the project it shows; switch to it if another window changed it."""
        pid = self.headers.get("X-Project")
        if pid and pid != CUR["id"] and meta(os.path.basename(pid)) and not state["busy"]:
            with lock_open:
                if pid != CUR["id"]: open_project(os.path.basename(pid))

    def do_GET(self):
        self.follow_window()
        u = urlparse(self.path); p = u.path; wd = CUR["wd"]
        if p == "/": p = "/home.html"
        if p == "/cortar": p = "/index.html" if wd and lic_status()["ok"] else "/home.html"
        if p == "/calculadora": p = "/calculadora.html" if lic_status()["ok"] else "/home.html"
        if p == "/api/license": return self.send(200, lic_status(force=True))
        if p.startswith("/api/") and p != "/api/state" and not lic_status()["ok"]: return self.send(402, {"error": "licença"})
        if p == "/api/projects": return self.send(200, list_projects())
        if p == "/api/fatiadores": return self.send(200, [n for n, _ in fatiadores()])
        if p == "/api/calc":                                   # calculadora de preço: ajustes gerais + o que foi salvo no projeto + a estimativa
            pid = os.path.basename(parse_qs(u.query).get("projeto", [""])[0]); m = meta(pid) if pid else None
            return self.send(200, {"geral": prefs().get("calc"), "projeto": (m or {}).get("orcamento"), "sugestao": calc_sugestao(pid) if m else None,
                                   "projetos": [dict(id=x["id"], name=x["name"]) for x in list_projects()]})
        if p.startswith("/api/thumb/"):
            f = os.path.join(pj(os.path.basename(p[11:])), "thumb.jpg")
            return self.send(200, open(f, "rb").read(), "image/jpeg") if os.path.exists(f) else self.send(404, "x", "text/plain")
        if p == "/api/state":
            st = dict(state)
            if wd:
                m = meta(CUR["id"])
                st["marks"] = json.load(open(f"{wd}/marks.json")) if os.path.exists(f"{wd}/marks.json") else None
                st["summary"] = json.load(open(f"{wd}/seg_summary.json")) if os.path.exists(f"{wd}/seg_summary.json") else None
                st["loops"] = json.load(open(f"{wd}/loops.json")) if os.path.exists(f"{wd}/loops.json") else []
                st["name"] = m["name"]; st["out"] = m["out_dir"]; st["height"] = m.get("height_mm")
                pf = f"{wd}/paint.npy"
                st["painted"] = int((np.load(pf) >= 0).sum()) if os.path.exists(pf) else 0
                st["deleted"] = int(np.load(f"{wd}/del.npy").sum()) if os.path.exists(f"{wd}/del.npy") else 0
                st["pieces"] = json.load(open(f"{wd}/pieces.json")) if os.path.exists(f"{wd}/pieces.json") else None
                inf = f"{wd}/info.json"                      # 3MF pintado pra AMS: cores disponíveis pro "Separar por cor"
                info_ = json.load(open(inf)) if os.path.exists(inf) else {}
                st["cores"] = info_.get("cores") if os.path.exists(f"{wd}/cor.npy") else None
                st["objetos"] = len(info_.get("objects") or {}); st["placas_src"] = (info_.get("placas") or {}).get("n", 0)
                st["layout"] = os.path.exists(f"{wd}/layout.json")
                try: st["arquivos_velhos"] = bool(st.get("files")) and bool(arquivos_velhos())
                except Exception: st["arquivos_velhos"] = False
                ef = f"{wd}/estimativas.json"
                st["estimativas"] = json.load(open(ef, encoding="utf-8")) if os.path.exists(ef) and os.path.exists(f"{wd}/pieces.json") and os.path.getmtime(ef) >= os.path.getmtime(f"{wd}/pieces.json") else None
                try: st["joints_salvos"] = json.load(open(f"{wd}/config.json", encoding="utf-8")).get("joints")      # ajustes do encaixe usados por último
                except Exception: st["joints_salvos"] = None
                st["joints_padrao"] = prefs().get("juntas_padrao")               # o padrão que o usuário salvou (vale pros projetos novos)
            st["tutorial_visto"] = bool(prefs().get("tutorial_visto"))
            return self.send(200, st)
        if not wd and p.startswith("/api/"): return self.send(409, {"error": "nenhum projeto aberto"})
        if p == "/api/mesh": return self.send(200, CUR["MESH"], "application/octet-stream")
        if p == "/api/seams": return self.send(200, seams_payload())
        if p == "/api/straight_report":
            f = f"{wd}/straight_report.json"
            if not os.path.exists(f): return self.send(200, {})
            r = json.load(open(f, encoding="utf-8")); os.remove(f); return self.send(200, r)
        if p == "/api/smart":
            if not os.path.exists(f"{wd}/smart.json"): return self.send(404, {"error": "sem sugestão"})
            sm = json.load(open(f"{wd}/smart.json", encoding="utf-8"))
            sm["view"] = np.load(f"{wd}/smart_view.npy").astype(int).tolist(); return self.send(200, sm)
        if p == "/api/layout":
            f = f"{wd}/layout.json"; pf = f"{wd}/pieces.json"            # peças refeitas depois dos pratos: recalcula (o que foi arrumado fica)
            ok = os.path.exists(f) and os.path.exists(pf) and os.path.getmtime(f) >= os.path.getmtime(pf)
            return self.send(200, json.load(open(f, encoding="utf-8"))) if ok else self.send(404, {"error": "sem pratos"})
        if p == "/api/stl":
            n = os.path.basename(unquote(parse_qs(u.query).get("name", [""])[0])); f = f"{wd}/_build/{n}.stl"
            return self.send(200, open(f, "rb").read(), "application/octet-stream") if n and os.path.exists(f) else self.send(404, {"error": "?"})
        if p == "/api/placas_src":                       # pratos do arquivo original + objeto de cada triângulo da tela
            info = json.load(open(f"{wd}/info.json"))
            if not info.get("placas"): return self.send(404, {"error": "sem pratos"})
            return self.send(200, dict(info["placas"], escala=float(info.get("prescale", 1.0)), nomes=info.get("objects", {})))
        if p == "/api/view_part":
            return self.send(200, np.load(f"{wd}/part.npy")[CUR["vmap"]].astype(np.int32).tobytes(), "application/octet-stream")
        if p == "/api/pieces":
            f = f"{wd}/pieces.bin"
            return self.send(200, open(f, "rb").read(), "application/octet-stream") if os.path.exists(f) else self.send(404, {"error": "sem peças"})
        if p == "/api/del":
            f = f"{wd}/del.npy"
            d = np.load(f) if os.path.exists(f) else np.zeros(len(np.load(f"{wd}/t.npy", mmap_mode="r")), bool)
            return self.send(200, d[CUR["vmap"]].astype(np.uint8).tobytes(), "application/octet-stream")
        if p == "/api/seg":
            if not os.path.exists(f"{wd}/seg.npy"): return self.send(404, {"error": "sem resultado"})
            seg = np.load(f"{wd}/seg.npy"); return self.send(200, seg[CUR["vmap"]].astype(np.uint8).tobytes(), "application/octet-stream")
        f = os.path.normpath(os.path.join(VIEWER, p.lstrip("/")))
        if f.startswith(os.path.normpath(VIEWER)) and os.path.isfile(f):
            ct = {"html": "text/html", "js": "text/javascript", "css": "text/css", "png": "image/png", "svg": "image/svg+xml"}.get(f.rsplit(".", 1)[-1], "application/octet-stream")
            return self.send(200, open(f, "rb").read(), ct + ("; charset=utf-8" if ct.startswith("text") else ""))
        self.send(404, "not found", "text/plain")

    def do_POST(self):
        self.follow_window()
        u = urlparse(self.path); p = u.path; q = parse_qs(u.query)
        n = int(self.headers.get("Content-Length", 0))
        if p == "/api/license":
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if not LIC["req"]: return self.send(200, {"ok": True, "required": False})
            LIC["st"] = dict(licenca.activate(body.get("key", "")), required=True); LIC["t"] = time.time()
            return self.send(200, LIC["st"])
        if p in ("/api/ping", "/api/bye"):                     # cada janela avisa que está viva / que fechou
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            wid = str(body.get("janela") or "")
            LAST_PING[0] = time.time()
            if p == "/api/ping" and wid: JANELAS[wid] = time.time(); JA_TEVE_JANELA[0] = True
            if p == "/api/bye" and wid:
                JANELAS.pop(wid, None)
                if not JANELAS: JANELAS["_saindo"] = time.time() - 11       # 4 s pra outra página (troca de tela) se registrar; senão encerra
            return self.send(200, {"ok": True})
        if p == "/api/quit":                                   # o instalador pede para fechar antes de trocar os arquivos
            self.send(200, {"ok": True}); threading.Timer(0.3, encerrar).start(); return
        if p != "/api/ping" and not lic_status()["ok"]:
            if n: self.rfile.read(n)
            return self.send(402, {"error": "licença"})
        if p == "/api/upload":
            if state["busy"]: return self.send(409, {"error": "ocupado"})
            name = unquote(q.get("name", ["modelo"])[0]); ext = os.path.splitext(unquote(q.get("file", ["x.stl"])[0]))[1].lower()
            if ext not in (".stl", ".3mf"): return self.send(400, {"error": "use um arquivo .stl ou .3mf"})
            tmp = os.path.join(PROJ, "_upload" + ext)
            with open(tmp, "wb") as fo:
                left = n
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20)); fo.write(chunk); left -= len(chunk)
            h = float(q.get("height", ["0"])[0] or 0)
            state.update(busy=True, stage="começando", error=None)
            threading.Thread(target=job_import, args=("", name, h, ext, tmp), daemon=True).start(); return self.send(200, {"ok": True})
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if p == "/api/pick_file": return self.send(200, {"path": pick_file()})
        if p == "/api/prefs":                                  # pasta padrão dos arquivos prontos (vale pros projetos novos)
            d = prefs()
            if body.get("escolher"):
                q_ = pick_folder(d["saida"])
                if not q_: return self.send(200, dict(d, cancelado=True))
                d["saida"] = q_; salvar_prefs(d)
            return self.send(200, d)
        if p == "/api/calc":                                   # calculadora: salva os ajustes gerais e o orçamento do projeto
            d = prefs()
            if isinstance(body.get("geral"), dict): d["calc"] = body["geral"]; salvar_prefs(d)
            pid = os.path.basename(str(body.get("projeto_id") or "")); m = meta(pid) if pid else None
            if m is not None and isinstance(body.get("projeto"), dict): m["orcamento"] = body["projeto"]; save_meta(pid, m)
            return self.send(200, {"ok": True})
        if p == "/api/padrao":                                 # ajustes de encaixe padrão / tutorial visto
            d = prefs()
            if "juntas_padrao" in body: d["juntas_padrao"] = body["juntas_padrao"]
            if "tutorial_visto" in body: d["tutorial_visto"] = bool(body["tutorial_visto"])
            salvar_prefs(d); return self.send(200, {"ok": True})
        if p == "/api/calibracao":                             # teste de folga pra imprimir
            J_ = body.get("joints") or {}; tipo = J_.get("pin_type", "round")
            nome = {"magnet": "ímã", "none": "rebaixo", "round": "pino redondo", "square": "pino quadrado", "hex": "pino sextavado", "cone": "pino cônico", "center": "pino central"}.get(tipo, tipo)
            pasta = os.path.join(prefs()["saida"], "Teste de folga"); os.makedirs(pasta, exist_ok=True)
            arq = os.path.join(pasta, f"Teste de folga - {nome}.stl")
            r = subprocess.run([PY, f"{ENG}/calibracao.py", arq, json.dumps(J_)], capture_output=True, text=True, env=ENV, creationflags=NOWIN)
            if r.returncode != 0: return self.send(200, {"error": (r.stderr or r.stdout)[-300:]})
            log("teste de folga: " + arq)
            if body.get("abrir", True): abrir_arquivo(pasta)
            return self.send(200, {"ok": True, "arquivo": arq})
        if p == "/api/pasta":                                  # biblioteca: projeto numa pasta (vazio = sem pasta)
            pid_ = os.path.basename(body.get("id", "")); m = meta(pid_)
            if not m: return self.send(404, {"error": "projeto não existe"})
            m["pasta"] = str(body.get("pasta") or "").strip()[:60]; save_meta(pid_, m); return self.send(200, {"ok": True})
        if p == "/api/fatiador" and CUR["id"]:                 # abre os arquivos gerados no fatiador escolhido
            if state["busy"]: return self.send(200, {"error": "O programa está ocupado, espere terminar."})
            refeito = False
            try:
                state.update(busy=True, stage="atualizando os arquivos"); refeito = atualizar_arquivos()
            except Exception as e:
                state["busy"] = False; return self.send(200, {"error": "Não deu pra atualizar o 3MF: " + str(e)})
            state.update(busy=False, stage="arquivos prontos")
            m = meta(CUR["id"]); OUT = m["out_dir"]; fs_ = state.get("files") or []
            tm = [f for f in fs_ if f.endswith(" - pratos.3mf")] or [f for f in fs_ if f.endswith(".3mf")]
            arqs = [os.path.join(OUT, tm[0])] if tm else [os.path.join(OUT, f) for f in fs_ if f.lower().endswith(".stl")]
            arqs = [a for a in arqs if os.path.exists(a)]
            if not arqs: return self.send(200, {"error": "Gere os arquivos primeiro (botão Gerar arquivos)."})
            if body.get("app") == "_padrao": abrir_arquivo(arqs[0]); return self.send(200, {"ok": True, "refeito": refeito})
            return self.send(200, {"ok": abrir_no_fatiador(body.get("app"), arqs), "refeito": refeito})
        if p == "/api/guia" and CUR["id"]:                     # guia de montagem (imagem feita na tela)
            import base64
            m = meta(CUR["id"]); OUT = m["out_dir"]; os.makedirs(OUT, exist_ok=True)
            arq = os.path.join(OUT, f"{safe(m['name'], 'modelo')} - guia de montagem.png")
            open(arq, "wb").write(base64.b64decode(body["png"].split(",", 1)[1]))
            if body.get("abrir", True): abrir_arquivo(arq)
            return self.send(200, {"ok": True, "arquivo": arq})
        if p == "/api/out_dir" and CUR["id"]:                  # pasta dos arquivos deste projeto
            m = meta(CUR["id"]); q_ = pick_folder(m.get("out_dir", ""))
            if not q_: return self.send(200, {"out": m.get("out_dir"), "cancelado": True})
            m["out_dir"] = q_; save_meta(CUR["id"], m); state["files"] = []; return self.send(200, {"out": q_})
        if p == "/api/open_folder":
            target = meta(CUR["id"])["out_dir"] if body.get("what") == "out" and CUR["id"] else DATA
            os.makedirs(target, exist_ok=True)
            if sys.platform == "darwin": subprocess.Popen(["open", target])
            elif os.name == "nt": os.startfile(target)
            else: subprocess.Popen(["xdg-open", target])
            return self.send(200, {"ok": True})
        if p == "/api/thumb" and CUR["wd"]:
            import base64
            open(f"{CUR['wd']}/thumb.jpg", "wb").write(base64.b64decode(body["jpg"].split(",", 1)[1])); return self.send(200, {"ok": True})
        if p == "/api/marks" and CUR["wd"]:
            remap_paint(body.get("groups", []))
            json.dump(body, open(f"{CUR['wd']}/marks.json", "w"), indent=1); return self.send(200, {"ok": True})
        if p == "/api/paint_clear" and CUR["wd"]:
            clear_paint(); return self.send(200, {"ok": True})
        if p == "/api/paint" and CUR["wd"]:
            return self.send(200, {"ok": True, "changed": int(do_paint(body.get("ops", [])))})
        if p == "/api/del" and CUR["wd"]:
            n, tot = do_delete(body); return self.send(200, {"ok": True, "changed": n, "total": tot})
        if p == "/api/del_undo" and CUR["wd"]:
            return self.send(200, {"ok": True, "changed": undo_delete()})
        if p == "/api/del_clear" and CUR["wd"]:
            f = f"{CUR['wd']}/del.npy"
            if os.path.exists(f): d = np.load(f); DEL["undo"].append((np.where(d)[0], np.ones(int(d.sum()), bool))); os.remove(f)
            return self.send(200, {"ok": True})
        if p == "/api/paint_undo" and CUR["wd"]:
            return self.send(200, {"ok": True, "changed": int(undo_paint())})
        if state["busy"]: return self.send(409, {"error": "ocupado"})
        if p == "/api/import":
            src = body.get("path", "")
            if not os.path.isfile(src): return self.send(400, {"error": "arquivo não encontrado"})
            name = body.get("name") or os.path.splitext(os.path.basename(src))[0]
            state.update(busy=True, stage="começando", error=None)
            threading.Thread(target=job_import, args=(src, name, float(body.get("height") or 0)), daemon=True).start()
            return self.send(200, {"ok": True})
        if p == "/api/open":
            if not meta(body.get("id", "")): return self.send(404, {"error": "projeto não existe"})
            open_project(body["id"]); return self.send(200, {"ok": True})
        if p == "/api/rename":
            m = meta(body["id"]); m["name"] = body["name"]; save_meta(body["id"], m); return self.send(200, {"ok": True})
        if p == "/api/delete":
            pid = os.path.basename(body.get("id", ""))
            if pid and meta(pid):
                if CUR["id"] == pid: CUR.update(id=None, wd=None); state["project"] = None
                shutil.rmtree(pj(pid), ignore_errors=True)
            return self.send(200, {"ok": True})
        if not CUR["wd"]: return self.send(409, {"error": "nenhum projeto aberto"})
        if p == "/api/smart":
            threading.Thread(target=job_smart, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/segment":
            threading.Thread(target=job_segment, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/desfazer":
            threading.Thread(target=job_desfazer, daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/object_split":
            return self.send(200, do_object_split())
        if p == "/api/layout" and body.get("itens") is not None:
            f = f"{CUR['wd']}/layout.json"
            if not os.path.exists(f): return self.send(404, {"error": "sem pratos"})
            L = json.load(open(f, encoding="utf-8")); velho = {it["name"]: it for it in L["itens"]}
            for it in body["itens"]:
                o = velho.get(it.get("name"))
                if o is None: continue
                o["placa"] = max(1, int(it["placa"])); o["x"] = round(float(it["x"]), 2); o["y"] = round(float(it["y"]), 2)
                Rm = np.array(it["R"], float)
                if Rm.shape == (3, 3) and abs(np.linalg.det(Rm) - 1) < 0.02: o["R"] = Rm.round(6).tolist()
            usados = sorted({it["placa"] for it in L["itens"]}); ren = {k: i + 1 for i, k in enumerate(usados)}
            for it in L["itens"]: it["placa"] = ren[it["placa"]]
            L["n"] = len(usados); json.dump(L, open(f, "w", encoding="utf-8"), ensure_ascii=False)
            return self.send(200, L)
        if p == "/api/layout":
            threading.Thread(target=job_layout, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/export":
            threading.Thread(target=job_export, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/color_split":
            return self.send(200, do_color_split(body))
        if p == "/api/straight":
            threading.Thread(target=job_straight, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/smooth":
            threading.Thread(target=job_smooth, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/preview":
            threading.Thread(target=job_preview, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        if p == "/api/finalize":
            threading.Thread(target=job_finalize, args=(body,), daemon=True).start(); return self.send(200, {"ok": True})
        self.send(404, {"error": "?"})


if __name__ == "__main__":
    log(f"Voxel Cut {VERSAO} em http://localhost:{PORT} · projetos em {PROJ} · python {sys.version.split()[0]}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
