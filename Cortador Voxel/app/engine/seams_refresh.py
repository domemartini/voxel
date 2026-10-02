"""Recompute seam lines + summary after manual painting (cuts through triangles if field.npy exists).
usage: python seams_refresh.py <workdir>"""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seams import write_loops
from refine import refine

wd = sys.argv[1]
v = np.load(f"{wd}/v.npy"); t = np.load(f"{wd}/t.npy"); seg = np.load(f"{wd}/seg.npy").astype(np.int8)
names = [g["name"] for g in json.load(open(f"{wd}/marks.json"))["groups"]]
if os.path.exists(f"{wd}/field.npy"):
    F = np.load(f"{wd}/field.npy").astype(np.float64)
    if F.shape == (len(v), len(names)): v, t, seg = refine(v, t, F)
loops = write_loops(wd, v, t, seg, names)
print("seams refreshed:", len(loops))
