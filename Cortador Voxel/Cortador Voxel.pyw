"""Abre o Voxel Cut: liga o servidor local (se ainda não estiver ligado) e abre a janela do app."""
import os, sys, subprocess, time, urllib.request, urllib.error

PORT = int(os.environ.get("VOXELCUT_PORT", "8770")); URL = f"http://localhost:{PORT}/"
HERE = os.path.dirname(os.path.abspath(__file__))

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


DATA = data_dir(HERE)


def up():
    try:
        urllib.request.urlopen(URL, timeout=1); return True
    except urllib.error.HTTPError:
        return True                                  # respondeu (ex.: pedindo licença): está ligado
    except Exception:
        return False


def criar_atalho(lnk, alvo, pasta, icone, descricao="Voxel Cut"):
    """escreve um atalho .lnk do Windows (formato MS-SHLLINK) sem precisar de PowerShell nem COM"""
    import struct
    def cstr(s): b = s.encode("utf-16-le"); return struct.pack("<H", len(s)) + b
    import ctypes
    pidl = ctypes.c_void_p(); idl = b""                          # identificador do caminho, gerado pelo próprio Windows
    if ctypes.windll.shell32.SHParseDisplayName(ctypes.c_wchar_p(alvo), None, ctypes.byref(pidl), 0, None) == 0 and pidl.value:
        ctypes.windll.shell32.ILGetSize.restype = ctypes.c_uint
        idl = ctypes.string_at(pidl.value, ctypes.windll.shell32.ILGetSize(pidl)); ctypes.windll.ole32.CoTaskMemFree(pidl)
    flags = (0x1 if idl else 0) | 0x2 | 0x4 | 0x10 | 0x40 | 0x80      # IDList, LinkInfo, Name, WorkingDir, IconLocation, Unicode
    head = struct.pack("<I16sIIQQQIiIH2xII", 0x4C, bytes.fromhex("0114020000000000c000000000000046"), flags, 0x20, 0, 0, 0, 0, 0, 1, 0, 0, 0)
    if idl: head += struct.pack("<H", len(idl)) + idl
    vol = struct.pack("<IIII", 17, 3, 0, 0x10) + b"\0"
    ansi = alvo.encode("mbcs", "replace") + b"\0"; uni = alvo.encode("utf-16-le") + b"\0\0"
    hdr = 0x24; o_vol = hdr; o_base = o_vol + len(vol); o_suf = o_base + len(ansi); o_ubase = o_suf + 1; o_usuf = o_ubase + len(uni)
    body = vol + ansi + b"\0" + uni + b"\0\0"
    info = struct.pack("<IIIIIIIII", hdr + len(body), hdr, 1, o_vol, o_base, 0, o_suf, o_ubase, o_usuf) + body
    data = head + info + cstr(descricao) + cstr(pasta) + cstr(icone) + b"\0\0\0\0"
    os.makedirs(os.path.dirname(lnk), exist_ok=True); open(lnk, "wb").write(data)


def atalhos_portatil():
    """versão portátil (Voxel Cut.exe na pasta): cria/atualiza os atalhos da área de trabalho e do menu Iniciar"""
    if os.name != "nt" or os.path.basename(sys.executable).lower() != "voxel cut.exe" or os.environ.get("VOXELCUT_SEM_ATALHOS"): return
    try:
        import ctypes; buf = ctypes.create_unicode_buffer(260); desk = None
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0: desk = buf.value          # CSIDL_DESKTOPDIRECTORY
        progs = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs")
        ico = os.path.join(HERE, "app", "icone.ico")
        for d in filter(None, (desk, progs)): criar_atalho(os.path.join(d, "Voxel Cut.lnk"), sys.executable, HERE, ico)
    except Exception:
        pass


def esconder_sistema():
    """versão portátil: na pasta só ficam à vista o Voxel Cut.exe e o LEIA-ME; o resto (Python, motor) fica oculto"""
    if os.name != "nt" or os.path.basename(sys.executable).lower() != "voxel cut.exe": return
    try:
        import ctypes
        get, put = ctypes.windll.kernel32.GetFileAttributesW, ctypes.windll.kernel32.SetFileAttributesW
        for nome in os.listdir(HERE):
            if nome.lower() in ("voxel cut.exe", "leia-me.txt"): continue
            f = os.path.join(HERE, nome); a = get(f)
            if a != 0xFFFFFFFF and not a & 0x2: put(f, a | 0x2)            # FILE_ATTRIBUTE_HIDDEN
    except Exception:
        pass


atalhos_portatil()
esconder_sistema()
ligando = not up()
if ligando:
    MAC = sys.platform == "darwin"
    pyw = sys.executable if MAC or sys.executable.lower().endswith("pythonw.exe") else sys.executable.replace("python.exe", "pythonw.exe")
    os.makedirs(DATA, exist_ok=True)
    log = open(os.path.join(DATA, "servidor.log"), "w", encoding="utf-8")
    subprocess.Popen([pyw, os.path.join(HERE, "app", "server.py"), "--port", str(PORT), "--auto-exit"], cwd=os.path.join(HERE, "app"),
                     stdout=log, stderr=log, **({"start_new_session": True} if MAC else {"creationflags": 0x00000008 | 0x00000200}))   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    if os.environ.get("VOXELCUT_SEM_JANELA"):                   # (testes) espera o servidor e sai
        for _ in range(100):
            if up(): break
            time.sleep(0.2)
# a janela abre na hora: com o programa ainda ligando, mostra a tela de carregamento, que entra sozinha quando ele responde
from pathlib import Path
ABRIR = (Path(HERE, "app", "viewer", "abrindo.html").as_uri() + "?u=" + URL) if ligando else URL

if os.environ.get("VOXELCUT_SEM_JANELA"): sys.exit(0)          # (testes) liga só o servidor
if sys.platform == "darwin":                     # Mac: janela própria no Chrome/Edge/Brave; sem eles, o navegador padrão
    for nome in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
        if os.path.isdir(f"/Applications/{nome}.app") or os.path.isdir(os.path.expanduser(f"~/Applications/{nome}.app")):
            subprocess.Popen(["open", "-na", nome, "--args", f"--app={ABRIR}", "--window-size=1500,950"]); break
    else:
        if ligando:
            for _ in range(100):
                if up(): break
                time.sleep(0.2)
        subprocess.Popen(["open", URL])
    sys.exit(0)


# ------------------------------------------------------------------ Windows: tela de carregamento no centro, programa maximizado
def _win():
    import ctypes, ctypes.wintypes as wt
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)              # coordenadas em pixels reais (telas com zoom 125%, 150%…)
    except Exception:
        try: ctypes.windll.user32.SetProcessDPIAware()
        except Exception: pass
    return ctypes, wt, ctypes.windll.user32


def janelas():
    """janelas visíveis do Edge/Chrome: {hwnd: título}"""
    ctypes, wt, u = _win(); res = {}
    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if u.IsWindowVisible(h):
            cls = ctypes.create_unicode_buffer(64); u.GetClassNameW(h, cls, 64)
            if cls.value == "Chrome_WidgetWin_1":
                n = u.GetWindowTextLengthW(h); t = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, t, n + 1); res[h] = t.value
        return True
    u.EnumWindows(cb, 0); return res


def centralizar(h, w=520, a=360):
    """põe a janela no meio da área útil do monitor onde ela está (sem a barra de tarefas)"""
    ctypes, wt, u = _win()
    class MI(ctypes.Structure): _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
    mi = MI(); mi.cbSize = ctypes.sizeof(MI)
    if not u.GetMonitorInfoW(u.MonitorFromWindow(h, 2), ctypes.byref(mi)): return
    try: s = u.GetDpiForWindow(h) / 96 or 1
    except Exception: s = 1
    r = mi.rcWork; w, a = int(w * s), int(a * s)
    u.ShowWindow(h, 9)                                                # SW_RESTORE (se o Edge lembrou dela maximizada/encaixada)
    u.SetWindowPos(h, 0, r.left + (r.right - r.left - w) // 2, r.top + (r.bottom - r.top - a) // 2, w, a, 0x0004 | 0x0040)   # NOZORDER | SHOWWINDOW


def abrir_windows(browser):
    antes = set(janelas())
    tam = "--window-size=520,360" if ligando else "--start-maximized"
    subprocess.Popen([browser, f"--app={ABRIR}", tam])
    try:
        h = None
        for _ in range(150):                                          # acha a janela nova (até 15 s)
            h = next((k for k, t in janelas().items() if k not in antes and "Voxel Cut" in t), None)
            if h: break
            time.sleep(0.1)
        if not h: return
        _, _, u = _win()
        if ligando:
            centralizar(h)
            for _ in range(1200):                                     # quando a tela de carregamento dá lugar ao programa (até 2 min)
                t = janelas().get(h)
                if t is None: return                                  # fecharam a janela
                if not t.startswith("Abrindo"): break
                time.sleep(0.1)
        u.ShowWindow(h, 3)                                            # SW_MAXIMIZE
    except Exception:
        pass


edge = [p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)]
chrome = [p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)]
browser = (edge or chrome or [None])[0]
if browser:
    abrir_windows(browser)
else:
    import webbrowser; webbrowser.open(ABRIR)
