"""2D outlines of every cap, grown by 0.03 (plug) and by the socket clearance, via shapely.
usage: python outlines.py <workdir>     needs caps.json config.json -> outlines.json"""
import sys, json, numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

wd = sys.argv[1]; caps = json.load(open(f"{wd}/caps.json")); cfg = json.load(open(f"{wd}/config.json"))
CLEAR = cfg.get("clear", 0.15)


def polys(g):
    return [] if g.is_empty else (list(g.geoms) if isinstance(g, MultiPolygon) else [g])


out = {}
for name, groups in caps.items():
    out[name] = []
    for g in groups:
        uv = np.array(g["uv"]); tris = np.array(g["tris"])
        shape = unary_union([Polygon(uv[t]) for t in tris if Polygon(uv[t]).area > 1e-9]).buffer(0.001)

        def rings(d):
            return [dict(ext=list(p.exterior.coords)[:-1]) for p in polys(shape.buffer(d, join_style="round", quad_segs=4).simplify(0.01)) if p.area > 0.02]
        out[name].append(dict(normal=g["normal"], origin=g["origin"], A=g["A"], B=g["B"], dev=g["dev"], target=g.get("target", "Base"),
                              plug=rings(0.03), sock=rings(CLEAR), area=shape.area))
    print(name, [round(x["area"], 1) for x in out[name]])
json.dump(out, open(f"{wd}/outlines.json", "w"))
