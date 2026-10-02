"""Licença do Voxel Cut: chave assinada (Ed25519) com nome do cliente e data de validade.
Só quem tem a chave secreta (no PC da Voxel) consegue gerar licenças; o programa só confere com a chave pública.
Formato:  VOXEL.<dados em base64>.<assinatura em base64>"""
import os, json, base64, hashlib, datetime

PUBLIC_KEY = "ecd8fca3fdc1af1716baa8f2b62e81529e0434f0a73d8b9485358f9687758f8c"
VENDEDOR = "Voxel"                     # quem vende (aparece na tela de ativação)

# ---------------------------------------------------------------- Ed25519 (RFC 8032), puro Python
_p = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_I = pow(2, (_p - 1) // 4, _p)


def _inv(x): return pow(x, _p - 2, _p)


def _xrecover(y, sign):
    xx = (y * y - 1) * _inv(_d * y * y + 1) % _p
    x = pow(xx, (_p + 3) // 8, _p)
    if (x * x - xx) % _p: x = x * _I % _p
    if (x * x - xx) % _p: raise ValueError("ponto inválido")
    if x & 1 != sign: x = _p - x
    return x


_By = 4 * _inv(5) % _p; _Bx = _xrecover(_By, 0); _B = (_Bx, _By, 1, _Bx * _By % _p)


def _add(P, Q):
    x1, y1, z1, t1 = P; x2, y2, z2, t2 = Q
    A = (y1 - x1) * (y2 - x2) % _p; B = (y1 + x1) * (y2 + x2) % _p
    C = t1 * 2 * _d * t2 % _p; D = z1 * 2 * z2 % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s:
        if s & 1: Q = _add(Q, P)
        P = _add(P, P); s >>= 1
    return Q


def _enc(P):
    x, y, z, _ = P; zi = _inv(z); x, y = x * zi % _p, y * zi % _p
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _dec(b):
    y = int.from_bytes(b, "little"); sign = y >> 255; y &= (1 << 255) - 1
    if y >= _p: raise ValueError("ponto inválido")
    x = _xrecover(y, sign); return (x, y, 1, x * y % _p)


def _h(m): return int.from_bytes(hashlib.sha512(m).digest(), "little")


def _expand(seed):
    h = hashlib.sha512(seed).digest(); a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8; a |= 1 << 254; return a, h[32:]


def public_key(seed): return _enc(_mul(_expand(seed)[0], _B))


def sign(seed, msg):
    a, prefix = _expand(seed); A = _enc(_mul(a, _B))
    r = _h(prefix + msg) % _L; R = _enc(_mul(r, _B))
    s = (r + _h(R + A + msg) % _L * a) % _L
    return R + s.to_bytes(32, "little")


def verify(pub, msg, sig):
    try:
        if len(sig) != 64: return False
        A = _dec(pub); R = _dec(sig[:32]); s = int.from_bytes(sig[32:], "little")
        if s >= _L: return False
        P1 = _mul(s, _B); P2 = _add(R, _mul(_h(sig[:32] + pub + msg) % _L, A))
        return (P1[0] * P2[2] - P2[0] * P1[2]) % _p == 0 and (P1[1] * P2[2] - P2[1] * P1[2]) % _p == 0
    except Exception:
        return False


# ---------------------------------------------------------------- chaves de licença
def _b64(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")
def _unb64(s): return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


ALFA = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"                   # sem I, O, 0 e 1 (não confunde ao ditar)


def codigo_pc():
    """código curto deste computador (ex.: K7QM-3XRP), tirado da identidade do Windows / do Mac"""
    import sys
    raw = ""
    try:
        if sys.platform == "win32":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            raw = winreg.QueryValueEx(k, "MachineGuid")[0]
        elif sys.platform == "darwin":
            import subprocess, re
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True, text=True).stdout
            m = re.search(r'"IOPlatformUUID" = "([^"]+)"', out); raw = m.group(1) if m else ""
        else:
            raw = open("/etc/machine-id").read().strip()
    except Exception:
        pass
    n = int.from_bytes(hashlib.sha256(("voxelcut|" + (raw or "desconhecido").lower()).encode()).digest()[:5], "big")
    s = "".join(ALFA[(n >> (5 * i)) & 31] for i in range(8))
    return s[:4] + "-" + s[4:]


def normaliza_pc(c):
    c = "".join(ch for ch in str(c).upper() if ch in ALFA)
    return c[:4] + "-" + c[4:8] if len(c) == 8 else None


def make_key(seed, nome, contato, ate, lid=None, pcs=None):
    """(só no gerador) cria a chave de licença; ate = 'AAAA-MM-DD'; pcs = códigos dos computadores liberados"""
    data = dict(v=1, id=lid or os.urandom(4).hex(), nome=nome, contato=contato, emit=datetime.date.today().isoformat(), ate=ate)
    pcs = [p for p in (normaliza_pc(x) for x in (pcs or [])) if p]
    if pcs: data["pc"] = pcs
    msg = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    return "VOXEL." + _b64(msg) + "." + _b64(sign(seed, msg))


def read_key(key):
    """confere a assinatura; devolve os dados da licença ou None"""
    try:
        key = "".join(key.split())
        tag, msg, sig = key.split(".")
        if tag != "VOXEL": return None
        msg = _unb64(msg)
        if not verify(bytes.fromhex(PUBLIC_KEY), msg, _unb64(sig)): return None
        return json.loads(msg.decode())
    except Exception:
        return None


# ---------------------------------------------------------------- licença instalada neste PC
def _dir():
    import sys
    if sys.platform == "darwin": return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Voxel Cut")
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Voxel Cut")


def required(root):
    """a licença só é pedida na versão instalada (a cópia de desenvolvimento da Voxel não pede)"""
    return os.path.exists(os.path.join(root, "instalado.txt")) or os.environ.get("CORTADOR_LICENCA") == "1"


def status(extra=()):
    """extra: outras pastas onde um licenca.txt também vale (ex.: Documentos\\Voxel Cut)"""
    pc = codigo_pc(); base = dict(ok=False, vendedor=VENDEDOR, codigo=pc)
    fs = [os.path.join(d, "licenca.txt") for d in (_dir(),) + tuple(extra)]
    fs = [f for f in fs if os.path.exists(f)]
    if not fs: return dict(base, motivo="sem_licenca")
    lics = [read_key(open(f, encoding="utf-8").read()) for f in fs]
    if not any(lics): return dict(base, motivo="invalida")
    deste = [l for l in lics if l and (not l.get("pc") or pc in l["pc"])]           # chave presa a outro computador não vale aqui
    if not deste: l0 = next(l for l in lics if l); return dict(base, motivo="outro_pc", nome=l0["nome"])
    lic = max(deste, key=lambda l: l.get("ate", ""))                                  # a que vence mais tarde
    hoje = datetime.date.today()
    # relógio atrasado de propósito? guarda o último dia em que o programa foi usado
    fu = os.path.join(_dir(), "uso.txt")
    try:
        ult = datetime.date.fromisoformat(open(fu).read().strip())
    except Exception:
        ult = None
    if ult and hoje < ult - datetime.timedelta(days=2):
        return dict(base, motivo="relogio", nome=lic["nome"], ate=lic["ate"])
    if not ult or hoje > ult:
        try: open(fu, "w").write(hoje.isoformat())
        except Exception: pass
    ate = datetime.date.fromisoformat(lic["ate"]); dias = (ate - hoje).days
    info = dict(base, nome=lic["nome"], contato=lic.get("contato", ""), ate=lic["ate"], id=lic["id"], dias=dias)
    if dias < 0: return dict(info, motivo="vencida")
    return dict(info, ok=True)


def activate(key):
    lic = read_key(key); pc = codigo_pc()
    if not lic: return dict(ok=False, motivo="invalida", vendedor=VENDEDOR, codigo=pc)
    if lic.get("pc") and pc not in lic["pc"]: return dict(ok=False, motivo="outro_pc", vendedor=VENDEDOR, codigo=pc, nome=lic["nome"])
    os.makedirs(_dir(), exist_ok=True)
    open(os.path.join(_dir(), "licenca.txt"), "w", encoding="utf-8").write("".join(key.split()))
    return status()
