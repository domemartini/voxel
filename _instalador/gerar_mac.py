"""Monta o Voxel Cut para Mac (Apple Silicon) daqui do Windows: 'Voxel Cut.app' dentro de um .zip.
Python próprio (python-build-standalone) + bibliotecas em versão macOS arm64 + o código atual de ../Cortador Voxel.
usage: python gerar_mac.py [versao]"""
import os, sys, io, json, re, shutil, tarfile, zipfile, subprocess, urllib.request, compileall, py_compile, tempfile

B = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(os.path.dirname(B), "Cortador Voxel")
MAC = os.path.join(B, "mac"); CACHE = os.path.join(MAC, "cache"); SITE = os.path.join(MAC, "site-packages")
VER = sys.argv[1] if len(sys.argv) > 1 else "1.1.0"
LIBS = ["numpy", "scipy", "shapely", "manifold3d", "fast-simplification", "scikit-image"]
APP = "Voxel Cut.app/Contents"
os.makedirs(CACHE, exist_ok=True)


def baixar_python():
    """python-build-standalone 3.12 para aarch64-apple-darwin (install_only)"""
    have = [f for f in os.listdir(CACHE) if f.startswith("cpython-3.12") and f.endswith(".tar.gz")]
    if have: return os.path.join(CACHE, have[0])
    rel = json.load(urllib.request.urlopen("https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"))
    asset = next(a for a in rel["assets"] if re.match(r"cpython-3\.12\.\d+\+\d+-aarch64-apple-darwin-install_only\.tar\.gz$", a["name"]))
    dst = os.path.join(CACHE, asset["name"]); print("  baixando", asset["name"], round(asset["size"] / 1e6), "MB")
    urllib.request.urlretrieve(asset["browser_download_url"], dst); return dst


def baixar_libs():
    if os.path.isdir(SITE) and os.listdir(SITE): return
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "--target", SITE, "--only-binary=:all:",
                    "--platform", "macosx_12_0_arm64", "--python-version", "3.12", "--implementation", "cp", "--abi", "cp312"] + LIBS, check=True)
    for d in ("bin",): shutil.rmtree(os.path.join(SITE, d), ignore_errors=True)
    for root, dirs, _ in os.walk(SITE):                      # testes das bibliotecas não vão no app
        for d in list(dirs):
            if d in ("tests", "test"): shutil.rmtree(os.path.join(root, d)); dirs.remove(d)
    compileall.compile_dir(SITE, quiet=1, workers=0)          # .pyc é igual em qualquer sistema (mesmo Python 3.12)


def icns(dst):
    from PIL import Image, ImageDraw
    lg = Image.open(os.path.join(SRC, "app", "viewer", "logo.png")).convert("RGBA")
    s = 1024; bg = Image.new("RGBA", (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(bg)
    d.rounded_rectangle([80, 80, s - 80, s - 80], 190, fill=(11, 14, 20, 255))
    lg.thumbnail((620, 620)); bg.alpha_composite(lg, ((s - lg.width) // 2, (s - lg.height) // 2)); bg.save(dst)


LAUNCH = """#!/bin/bash
# Voxel Cut (Mac): liga o programa com o Python que vem dentro do app
R="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec "$R/python/bin/python3" "$R/Voxel Cut.pyw"
"""

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Voxel Cut</string>
  <key>CFBundleDisplayName</key><string>Voxel Cut</string>
  <key>CFBundleIdentifier</key><string>com.voxel.voxelcut</string>
  <key>CFBundleExecutable</key><string>Voxel Cut</string>
  <key>CFBundleIconFile</key><string>icone</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{v}</string>
  <key>CFBundleVersion</key><string>{v}</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSDocumentsFolderUsageDescription</key><string>O Voxel Cut guarda seus projetos e as peças geradas em Documentos/Voxel Cut.</string>
</dict></plist>
"""

LEIA = """VOXEL CUT PARA MAC (Apple Silicon: M1, M2, M3, M4)
==================================================

INSTALAR
1) Dê dois cliques no .zip (se ainda não abriu) e arraste "Voxel Cut" para a pasta Aplicativos.
2) Na primeira vez, o Mac avisa que o app é de um desenvolvedor não identificado. Para liberar:
   - Clique com o botão direito em "Voxel Cut" > Abrir > Abrir.
   - Se não aparecer a opção: Ajustes do Sistema > Privacidade e Segurança > role até o fim > "Abrir Mesmo Assim".
   - Se aparecer "está danificado": abra o Terminal e cole a linha abaixo, depois abra de novo:
       xattr -dr com.apple.quarantine "/Applications/Voxel Cut.app"
3) Se o Mac pedir acesso à pasta Documentos, clique em Permitir (é onde ficam seus projetos).

USAR
- O programa abre numa janela própria do Chrome (ou Edge/Brave). Sem esses navegadores, abre no navegador padrão.
- Na primeira abertura ele pede a chave de licença.
- Seus projetos e as peças geradas ficam em Documentos/Voxel Cut.
"""


def zip_add(z, name, data=None, path=None, mode=0o644, link=None):
    zi = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)); zi.create_system = 3
    if link is not None:
        zi.external_attr = (0o120777 << 16); z.writestr(zi, link); return
    zi.external_attr = ((0o100000 | mode) << 16); zi.compress_type = zipfile.ZIP_DEFLATED
    if path: data = open(path, "rb").read()
    z.writestr(zi, data)


def execmode(name): return 0o755 if name.endswith((".so", ".dylib")) or "/bin/" in name else 0o644


def montar():
    py = baixar_python(); baixar_libs()
    out = os.path.join(B, "saida", f"Voxel Cut {VER} para Mac (Apple Silicon).zip"); os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = tempfile.mkdtemp(); ic = os.path.join(tmp, "icone.icns"); icns(ic)
    # código do app pré-compilado
    app_tmp = os.path.join(tmp, "app"); shutil.copytree(os.path.join(SRC, "app"), app_tmp, ignore=shutil.ignore_patterns("__pycache__", "tools", "*.log", "smart_split_v1.py")); open(os.path.join(app_tmp, "versao.txt"), "w", encoding="utf-8").write(VER)
    compileall.compile_dir(app_tmp, quiet=1)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        zip_add(z, f"{APP}/Info.plist", PLIST.format(v=VER).encode())
        zip_add(z, f"{APP}/MacOS/Voxel Cut", LAUNCH.encode(), mode=0o755)
        zip_add(z, f"{APP}/Resources/icone.icns", path=ic)
        zip_add(z, f"{APP}/Resources/Voxel Cut.pyw", path=os.path.join(SRC, "Cortador Voxel.pyw"))
        zip_add(z, f"{APP}/Resources/instalado.txt", b"instalado no Mac\n")
        zip_add(z, "LEIA-ME (Mac).txt", LEIA.encode("utf-8"))
        for root, _, fs in os.walk(app_tmp):
            for f in fs:
                p = os.path.join(root, f); rel = os.path.relpath(p, tmp).replace("\\", "/"); zip_add(z, f"{APP}/Resources/{rel}", path=p)
        # Python para Mac, direto do .tar.gz (mantém permissões e links simbólicos)
        with tarfile.open(py) as t:
            for m in t.getmembers():
                name = f"{APP}/Resources/{m.name}"
                if "/test/" in m.name or "/idlelib/" in m.name or "/tkinter/" in m.name or "/turtledemo/" in m.name: continue
                if m.isdir(): continue
                if m.issym(): zip_add(z, name, link=m.linkname); continue
                if m.isfile(): zip_add(z, name, t.extractfile(m).read(), mode=m.mode & 0o777)
        # bibliotecas (numpy, scipy, manifold3d…) para macOS arm64
        pyver = "python3.12"
        for root, _, fs in os.walk(SITE):
            for f in fs:
                p = os.path.join(root, f); rel = os.path.relpath(p, SITE).replace("\\", "/")
                name = f"{APP}/Resources/python/lib/{pyver}/site-packages/{rel}"; zip_add(z, name, path=p, mode=execmode(name))
    shutil.rmtree(tmp, ignore_errors=True)
    print("pronto:", out, round(os.path.getsize(out) / 1e6), "MB")
    return out


if __name__ == "__main__":
    montar()
