"""Load a .3mf (Bambu/Prusa, with components/assemble info) or .stl into numpy arrays.
usage: python load_model.py <input.3mf|.stl> <workdir> [--raw]
writes: workdir/v.npy (float64 Nx3), t.npy (int64 Mx3), part.npy (object id per tri), info.json
Coordinates = assembled model frame (mm). info.json["export_scale"] = uniform scale the project
uses on the plate (multiply when exporting so parts come out at the size the user prints)."""
import sys, os, re, json, zipfile, struct, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cores

src, wd = sys.argv[1], sys.argv[2]
RAW = "--raw" in sys.argv   # ignore Bambu assemble transforms (mesh frame, export_scale = plate scale)
os.makedirs(wd, exist_ok=True)


def M(s):
    return np.array(s.split(), float).reshape(4, 3)


def apply(m, p):
    return p @ m[:3] + m[3]


info = {"source": src}
if src.lower().endswith(".stl"):
    data = open(src, "rb").read()
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        tri = np.array(re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data), float).reshape(-1, 3, 3)
    else:
        n = struct.unpack("<I", data[80:84])[0]
        dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        tri = np.frombuffer(data[84:84 + n * 50], dtype=dt)["v"].astype(float)
    flat = tri.reshape(-1, 3).round(5)
    V, inv = np.unique(flat, axis=0, return_inverse=True)
    T = inv.reshape(-1, 3); PART = np.zeros(len(T), int)
    info["export_scale"] = 1.0
else:
    # 3MF: follow the spec - build items -> objects -> (mesh | components, possibly in other .model files via p:path)
    z = zipfile.ZipFile(src)
    rootname = "3D/3dmodel.model"
    try:
        m_ = re.search(r'Target="/?([^"]+\.model)"', z.read("_rels/.rels").decode(errors="ignore"))
        if m_: rootname = m_.group(1)
    except KeyError:
        pass
    if rootname not in z.namelist():
        rootname = next(n for n in z.namelist() if n.lower().endswith(".model"))
    try:
        cfg = z.read("Metadata/model_settings.config").decode(errors="ignore")
    except KeyError:
        cfg = ""
    I4 = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]], float)
    asm = {int(a): M(b) for a, b in re.findall(r'<assemble_item object_id="(\d+)" instance_id="0" transform="([^"]+)"', cfg)}
    names = dict(re.findall(r'<object id="(\d+)">\s*<metadata key="name" value="([^"]+)"', cfg))
    files = {}

    def load_file(path):
        if path not in files:
            d = z.read(path).decode(errors="ignore"); objs = {}
            for oid, body in re.findall(r'<object\b[^>]*?\bid="(\d+)"[^>]*>(.*?)</object>', d, re.S):
                if "<mesh" in body:
                    v = np.array(re.findall(r'<vertex\b[^>]*?\bx="([^"]+)"[^>]*?\by="([^"]+)"[^>]*?\bz="([^"]+)"', body), float).reshape(-1, 3)
                    tags = re.findall(r'<triangle\b([^>]*?)/?>', body)
                    t = np.array([re.search(r'\bv1="(\d+)"[^>]*?\bv2="(\d+)"[^>]*?\bv3="(\d+)"', g).groups() for g in tags], np.int64).reshape(-1, 3)
                    p = np.array([cores.estado(m.group(1)) if m else 0 for m in
                                  (re.search(r'(?:paint_color|slic3rpe:mmu_segmentation)="([0-9A-Fa-f]+)"', g) for g in tags)], np.int16)
                    objs[int(oid)] = ("mesh", v, t, p)
                else:
                    comps = []
                    for c in re.findall(r'<component\b([^>]*)>', body):
                        cid = int(re.search(r'\bobjectid="(\d+)"', c).group(1))
                        pm = re.search(r'p:path="([^"]+)"', c); tm = re.search(r'\btransform="([^"]+)"', c)
                        comps.append((pm.group(1).lstrip("/") if pm else path, cid, M(tm.group(1)) if tm else I4))
                    objs[int(oid)] = ("comp", comps)
            files[path] = (objs, d)
        return files[path]

    EXT = cores.extrusoras(cfg)

    def collect(path, oid, mats, out, depth=0, ext=1):
        o = load_file(path)[0].get(oid)
        if o is None or depth > 10: return
        ext = EXT.get(oid, ext)
        if o[0] == "mesh":
            v = o[1]
            for m in mats: v = apply(m, v)
            out.append((v, o[2], np.where(o[3] > 0, o[3], ext)))       # pintura > cor da parte > cor do objeto
        else:
            for cpath, cid, cm in o[1]: collect(cpath, cid, [cm] + mats, out, depth + 1, ext)

    root = load_file(rootname)[1]
    bsec = re.search(r'<build\b[^>]*>(.*?)</build>', root, re.S)
    items = []
    for it in re.findall(r'<item\b([^>]*)>', bsec.group(1) if bsec else ""):
        oid = int(re.search(r'\bobjectid="(\d+)"', it).group(1)); tm = re.search(r'\btransform="([^"]+)"', it)
        items.append((oid, M(tm.group(1)) if tm else I4))
    if not items:
        items = [(k, I4) for k in load_file(rootname)[0]]
    V, T, PART, COR, n0 = [], [], [], [], 0
    use_asm = bool(asm) and not RAW and len(items) > 1          # 1 objeto só: posição da placa (como se imprime); vários: montagem junta as peças
    if bool(asm) and not RAW and len(items) == 1 and items[0][0] in asm:
        Ra, Rp = asm[items[0][0]][:3], items[0][1][:3]            # impresso de cabeça pra baixo na placa? então mostra em pé (montagem)
        up = np.array([0.0, 0.0, 1.0]) @ np.linalg.inv(Ra) @ Rp
        if up[2] < -0.5 * np.linalg.norm(up): use_asm = True
    info["orientacao"] = "montagem" if use_asm else "placa"
    # pratos do arquivo (Bambu): em que prato está cada objeto e a matriz modelo carregado -> prato (coordenadas do prato, mm)
    placa_de = {}
    for k, pb in enumerate(re.findall(r'<plate>(.*?)</plate>', cfg, re.S)):
        pidm = re.search(r'key="plater_id" value="(\d+)"', pb); pid_ = int(pidm.group(1)) if pidm else k + 1
        for o_ in re.findall(r'key="object_id" value="(\d+)"', pb): placa_de[int(o_)] = pid_
    mesa = {"w": 256.0, "h": 256.0, "excluir": []}
    try:
        ps = z.read("Metadata/project_settings.config").decode(errors="ignore")
        pa = re.search(r'"printable_area"\s*:\s*\[(.*?)\]', ps, re.S)
        if pa:
            xy = np.array([[float(a), float(b)] for a, b in re.findall(r'"([-\d.]+)x([-\d.]+)"', pa.group(1))])
            if len(xy): mesa["w"], mesa["h"] = float(np.ptp(xy[:, 0])), float(np.ptp(xy[:, 1]))
        be = re.search(r'"bed_exclude_area"\s*:\s*\[(.*?)\]', ps, re.S)
        if be:
            xy = [[float(a), float(b)] for a, b in re.findall(r'"([-\d.]+)x([-\d.]+)"', be.group(1))]
            if len(xy) >= 3: mesa["excluir"] = [xy]
        pm = re.search(r'"printer_model"\s*:\s*"([^"]*)"', ps)
        if pm: mesa["impressora"] = pm.group(1)
    except KeyError:
        pass
    npl = max(placa_de.values()) if placa_de else 1; cols = int(np.ceil(np.sqrt(npl))); passo = 1.2 * mesa["w"]
    placas = {}
    for oid, bm in items:
        if oid in asm and use_asm:
            Ai = np.linalg.inv(asm[oid][:3]); R3 = Ai @ bm[:3]; tr = bm[3] - asm[oid][3] @ Ai @ bm[:3]
        elif RAW:
            R3, tr = bm[:3].copy(), bm[3].copy()
        else:
            R3, tr = np.eye(3), np.zeros(3)
        k = placa_de.get(oid, 1)
        tr = tr - np.array([((k - 1) % cols) * passo, -((k - 1) // cols) * passo, 0.0])     # tira o deslocamento do prato na grade do Bambu
        placas[str(oid)] = {"placa": k, "M": np.vstack([R3, tr]).round(6).tolist()}
    if placa_de or len(items) > 1:
        info["placas"] = {"n": npl, "mesa": mesa, "objetos": placas}
    for oid, bm in items:
        out = []
        top = [asm[oid]] if (use_asm and oid in asm) else ([] if RAW else [bm])
        collect(rootname, oid, top, out)
        for v, t, c in out:
            if not len(t): continue
            V.append(v); T.append(t + n0); PART += [oid] * len(t); COR.append(c); n0 += len(v)
    if not V:
        raise SystemExit("ERRO: nenhuma malha encontrada neste 3MF")
    V = np.vstack(V); T = np.vstack(T); PART = np.array(PART); COR = np.concatenate(COR).astype(np.int16)
    usadas = sorted(set(COR.tolist()))
    if len(usadas) > 1:                                   # modelo multicor: guarda a cor (filamento) de cada triângulo
        np.save(f"{wd}/cor.npy", COR); fil = cores.filamentos(z)
        info["cores"] = {str(k): (fil[k - 1] if 0 < k <= len(fil) else "#9CA3AF") for k in usadas}
        info["cores_tris"] = {str(k): int((COR == k).sum()) for k in usadas}
    sc = [float(np.linalg.norm(m[0])) for _, m in items] or [1.0]
    info["frame"] = "raw" if RAW else "assembled"
    info["export_scale"] = sc[0] if RAW else 1.0
    info["build_scales"] = sc
    info["objects"] = {str(k): names.get(str(k), "") for k in sorted(set(PART.tolist()))}
np.save(f"{wd}/v.npy", V); np.save(f"{wd}/t.npy", T); np.save(f"{wd}/part.npy", PART)
e = np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), 1)
_, c = np.unique(e[:, 0] * 10**8 + e[:, 1], return_counts=True)
info.update(verts=int(len(V)), tris=int(len(T)), bbox_min=V.min(0).round(2).tolist(), bbox_max=V.max(0).round(2).tolist(),
            nonmanifold_edges=int((c != 2).sum()))
json.dump(info, open(f"{wd}/info.json", "w"), indent=1)
print(json.dumps(info, indent=1))
