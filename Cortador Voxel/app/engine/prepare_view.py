"""Light display mesh for the viewer (quadric decimation, no Blender).
usage: python prepare_view.py <workdir> [target_tris=300000]   writes view_v.npy view_t.npy"""
import sys, os, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # módulos do motor (o Python embutido não põe a pasta do script no caminho)
import simplificar as fs                       # fast_simplification, ou numpy se o Windows bloquear a DLL

wd = sys.argv[1]; target = int(sys.argv[2]) if len(sys.argv) > 2 else 300000
v = np.load(f"{wd}/v.npy").astype(np.float32); t = np.load(f"{wd}/t.npy").astype(np.int32)
if len(t) > target:
    v, t = fs.simplify(v, t, target_reduction=1 - target / len(t))
np.save(f"{wd}/view_v.npy", np.asarray(v, np.float32)); np.save(f"{wd}/view_t.npy", np.asarray(t, np.int32))
print("view mesh", len(v), "verts", len(t), "tris")
