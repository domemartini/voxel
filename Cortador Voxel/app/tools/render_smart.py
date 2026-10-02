"""quick software render of view mesh colored by smart_view labels. usage: render_smart.py <wd> <out.png>"""
import sys, json, numpy as np
from PIL import Image, ImageDraw
wd, out = sys.argv[1], sys.argv[2]
v = np.load(f"{wd}/view_v.npy"); t = np.load(f"{wd}/view_t.npy"); lab = np.load(f"{wd}/smart_view.npy")
pcs = json.load(open(f"{wd}/smart.json"))["pieces"]
cols = np.array([[int(pc["color"][i:i + 2], 16) for i in (1, 3, 5)] for pc in pcs] + [[80, 80, 80]], float)
W = 560; ims = []
for az in (-60, 30, 120, 210):
    a = np.radians(az); el = np.radians(20)
    R = np.array([[np.cos(a), np.sin(a), 0], [-np.sin(a) * np.sin(el), np.cos(a) * np.sin(el), np.cos(el)], [np.sin(a) * np.cos(el), -np.cos(a) * np.cos(el), np.sin(el)]])
    q = (v - v.mean(0)) @ R.T; s = W * 0.9 / (np.ptp(q[:, :2], 0).max())
    xy = np.c_[q[:, 0] * s + W / 2, -q[:, 1] * s + W / 2]
    P = q[t]; n = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]); n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    vis = np.ones(len(t), bool)
    shade = np.clip(0.35 + 0.65 * np.abs(n[:, 2]), 0, 1)
    order = np.argsort(P[:, :, 2].mean(1))[::-1]
    im = Image.new("RGB", (W, W), (22, 24, 29)); d = ImageDraw.Draw(im)
    for i in order:
        if not vis[i]: continue
        c = cols[lab[i]] * shade[i]
        d.polygon([tuple(xy[j]) for j in t[i]], fill=tuple(int(x) for x in c))
    ims.append(im)
big = Image.new("RGB", (W * 2, W * 2))
for k, im in enumerate(ims): big.paste(im, ((k % 2) * W, (k // 2) * W))
d = ImageDraw.Draw(big)
for k, pc in enumerate(pcs): d.text((10, 10 + 16 * k), f"{pc['name']} {pc.get('volume_cm3', '')}", fill=pc["color"])
big.save(out)
