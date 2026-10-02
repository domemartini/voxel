"""Write ONE Bambu Studio 3MF with the parts on plates (keeps the printer/process settings of a template 3MF,
e.g. the user's original file).
usage: python export_3mf_plates.py <out.3mf> <template.3mf|-> "Name=path.stl" ["Name2=path2.stl" ...] [--bed 256]
         [--layout layout.json [--prato k | --peca Nome]]
Without a layout each part is centered on its own plate, resting on z=0, in the orientation of the STL.
With a layout (engine/plates.py) parts go to the plate, position and orientation the user arranged; --prato / --peca
export only that plate / that piece (as plate 1). Extruder of each part = its filament in the layout.
Plate layout follows Bambu Studio: grid with ceil(sqrt(n)) columns, stride = bed * 1.2."""
import sys, os, re, math, json, struct, zipfile, uuid, numpy as np

args = sys.argv[1:]
bed = 256.0
opt = {}
for flag in ("--bed", "--layout", "--prato", "--peca"):
    if flag in args:
        i = args.index(flag); opt[flag] = args[i + 1]; args = args[:i] + args[i + 2:]
if "--bed" in opt: bed = float(opt["--bed"])
bed_h = bed; bed_grid = None
out, template, items = args[0], args[1], [a.split("=", 1) for a in args[2:]]

place = {}                                                     # name -> (plate, R, x, y, extruder)
if "--layout" in opt:
    L = json.load(open(opt["--layout"], encoding="utf-8"))
    bed, bed_h = float(L["mesa"]["w"]), float(L["mesa"]["h"])
    for it in L["itens"]:
        if "--prato" in opt and it["placa"] != int(opt["--prato"]): continue
        if "--peca" in opt and it["name"] != opt["--peca"]: continue
        place[it["name"]] = [it["placa"], np.array(it["R"], float), it["x"], it["y"], int(it.get("fil") or 1)]
    if "--peca" in opt:
        for v in place.values(): v[0], v[2], v[3] = 1, bed / 2, bed_h / 2
    ren = {k: i + 1 for i, k in enumerate(sorted({v[0] for v in place.values()}))}
    for v in place.values(): v[0] = ren[v[0]]
    items = [(n, p) for n, p in items if n in place]
    if not items: raise SystemExit("ERRO: nada pra exportar")


def read_stl(p):
    data = open(p, "rb").read()
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        tri = np.array(re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data), np.float32).reshape(-1, 3, 3)
    else:
        n = struct.unpack("<I", data[80:84])[0]
        dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        tri = np.frombuffer(data[84:84 + n * 50], dtype=dt)["v"]
    V, inv = np.unique(tri.reshape(-1, 3), axis=0, return_inverse=True)
    return V.astype(np.float64), inv.reshape(-1, 3)


def mesh_xml(oid, V, T):
    vs = "\n".join(f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in V)
    ts = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in T)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
            'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
            'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n'
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
            f'  <object id="{oid}" p:UUID="{uuid.uuid4()}" type="model">\n   <mesh>\n    <vertices>\n{vs}\n    </vertices>\n'
            f'    <triangles>\n{ts}\n    </triangles>\n   </mesh>\n  </object>\n </resources>\n</model>\n')


def esc(s):
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


# the plate grid spacing in Bambu Studio follows the bed of the printer in the project settings
tpl_settings = None
if template != "-" and os.path.exists(template):
    tz = zipfile.ZipFile(template)
    if "Metadata/project_settings.config" in tz.namelist():
        tpl_settings = tz.read("Metadata/project_settings.config")
        pa = re.search(r'"printable_area"\s*:\s*\[(.*?)\]', tpl_settings.decode(errors="ignore"), re.S)
        xy = np.array([[float(a), float(b)] for a, b in re.findall(r'"([-\d.]+)x([-\d.]+)"', pa.group(1))]) if pa else np.zeros((0, 2))
        if len(xy) and (np.ptp(xy[:, 0]) + 0.5 < bed or np.ptp(xy[:, 1]) + 0.5 < bed_h):
            print(f"WARNING template printer bed {np.ptp(xy[:, 0]):.0f}x{np.ptp(xy[:, 1]):.0f} is smaller than the layout: settings not copied")
            tpl_settings = None
        elif len(xy):
            bed_grid = float(np.ptp(xy[:, 0]))
nplates = max(v[0] for v in place.values()) if place else len(items)
cols = math.ceil(math.sqrt(nplates)); stride = (bed_grid or bed) * 1.2
z = zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6)
res, build, rels, cfg_obj, inst = [], [], [], [], []
for k, (name, path) in enumerate(items):
    V, T = read_stl(path)
    if name in place: V = V @ place[name][1].T               # orientation chosen on the plate
    mn, mx = V.min(0), V.max(0); ctr = (mn + mx) / 2
    V = V - [ctr[0], ctr[1], mn[2]]                       # local: centered XY, bottom at z=0
    size = mx - mn
    if size[0] > bed or size[1] > bed_h or size[2] > max(bed, 250):
        print(f"WARNING {name}: {size.round(1)} mm does not fit a {bed:.0f} mm bed")
    if name in place:
        pk, _, px, py, ext = place[name]
    else:
        pk, px, py, ext = k + 1, bed / 2, bed_h / 2, 1
    col, row = (pk - 1) % cols, (pk - 1) // cols
    tx, ty = px + col * stride, py - row * stride
    mesh_id, obj_id = 2 * k + 1, 2 * k + 2
    fname = f"3D/Objects/object_{k + 1}.model"
    z.writestr(fname, mesh_xml(mesh_id, V, T))
    rels.append(f' <Relationship Target="/{fname}" Id="rel-{k + 1}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>')
    res.append(f'  <object id="{obj_id}" p:UUID="{uuid.uuid4()}" type="model">\n   <components>\n'
               f'    <component p:path="/{fname}" objectid="{mesh_id}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
               f'   </components>\n  </object>')
    build.append(f'  <item objectid="{obj_id}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 {tx:.4f} {ty:.4f} 0" printable="1"/>')
    cfg_obj.append(f'  <object id="{obj_id}">\n    <metadata key="name" value="{esc(name)}"/>\n    <metadata key="extruder" value="{ext}"/>\n'
                   f'    <metadata face_count="{len(T)}"/>\n    <part id="{mesh_id}" subtype="normal_part">\n'
                   f'      <metadata key="name" value="{esc(name)}"/>\n      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                   f'      <mesh_stat face_count="{len(T)}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
                   f'    </part>\n  </object>')
    inst.append((pk, name, f'    <model_instance>\n      <metadata key="object_id" value="{obj_id}"/>\n'
                           f'      <metadata key="instance_id" value="0"/>\n      <metadata key="identify_id" value="{100 + k}"/>\n    </model_instance>'))
    print(f"plate {pk}: {name}  {size.round(1).tolist()} mm  {len(T)} tris")
cfg_plate = []
for pk in sorted({c[0] for c in inst}):
    here = [c for c in inst if c[0] == pk]
    pname = esc(here[0][1]) if len(here) == 1 and not place else ""
    cfg_plate.append(f'  <plate>\n    <metadata key="plater_id" value="{pk}"/>\n    <metadata key="plater_name" value="{pname}"/>\n'
                     f'    <metadata key="locked" value="false"/>\n' + "\n".join(c[2] for c in here) + '\n  </plate>')
root = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">\n'
        ' <metadata name="Application">BambuStudio-02.06.01.55</metadata>\n <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        ' <resources>\n' + "\n".join(res) + '\n </resources>\n <build>\n' + "\n".join(build) + '\n </build>\n</model>\n')
z.writestr("3D/3dmodel.model", root)
z.writestr("3D/_rels/3dmodel.model.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n' + "\n".join(rels) + "\n</Relationships>\n")
z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
           ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n')
z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
           ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
           ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
           ' <Default Extension="png" ContentType="image/png"/>\n <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
z.writestr("Metadata/model_settings.config", '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg_obj) + "\n" + "\n".join(cfg_plate) + "\n</config>\n")
if tpl_settings is not None:
    z.writestr("Metadata/project_settings.config", tpl_settings)
    if "Metadata/filament_sequence.json" in tz.namelist(): z.writestr("Metadata/filament_sequence.json", tz.read("Metadata/filament_sequence.json"))
z.close()
print("saved", out, f"{os.path.getsize(out) / 1e6:.1f} MB")
