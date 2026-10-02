"""Pintura multicor dos 3MF (Bambu Studio / Orca / PrusaSlicer: atributo paint_color / slic3rpe:mmu_segmentation).
Cada triângulo pode estar subdividido; o texto hex guarda a árvore de subdivisão (formato do TriangleSelector):
nibbles lidos do fim pro começo, bits do menos pro mais significativo. Nó: 2 bits = lados divididos (0 = folha);
folha: 2 bits de estado (3 = estendido: +4 bits, estado = 3 + valor); nó dividido: 2 bits do lado especial e (lados+1) filhos.
Estado 0 = cor do objeto/parte; estado k = filamento k (1 = primeiro)."""
import re, json


def estado_dominante(s):
    """estado que cobre a maior área do triângulo"""
    bits = []
    for ch in reversed(s):
        n = int(ch, 16); bits += [(n >> i) & 1 for i in range(4)]
    pos = 0; acc = {}

    def rd(k):
        nonlocal pos
        v = 0
        for i in range(k): v |= (bits[pos + i] if pos + i < len(bits) else 0) << i
        pos += k; return v

    def no(w, prof=0):
        lados = rd(2)
        if lados == 0 or prof > 12:
            st = rd(2)
            if st == 3: st = 3 + rd(4)
            acc[st] = acc.get(st, 0.0) + w; return
        rd(2)
        n = lados + 1
        for _ in range(n): no(w / n, prof + 1)
    try: no(1.0)
    except Exception: return 0
    return max(acc, key=acc.get) if acc else 0


_cache = {}


def estado(s):
    if not s: return 0
    r = _cache.get(s)
    if r is None: r = _cache[s] = estado_dominante(s)
    return r


def filamentos(z):
    """cores dos filamentos do projeto (lista '#RRGGBB'), se houver"""
    for nome in ("Metadata/project_settings.config", "Metadata/Slic3r_PE.config"):
        try: d = z.read(nome).decode(errors="ignore")
        except KeyError: continue
        try:
            js = json.loads(d); c = js.get("filament_colour") or js.get("filament_color")
            if c: return [x[:7] for x in c]
        except ValueError:
            m = re.search(r"filament_colou?r\s*=\s*(.+)", d)
            if m: return [x.strip()[:7] for x in re.split(r"[;,]", m.group(1)) if x.strip()]
    return []


def extrusoras(cfg):
    """extrusora de cada objeto e de cada parte (model_settings.config) → {id: n}"""
    ext = {}
    for bloco in re.findall(r"<(?:object|part)\b[^>]*\bid=\"(\d+)\"[^>]*>(.*?)(?=<(?:object|part)\b|</object>)", cfg, re.S):
        oid, corpo = bloco
        m = re.search(r'<metadata key="extruder" value="(\d+)"', corpo)
        if m: ext[int(oid)] = int(m.group(1))
    return ext
