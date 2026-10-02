"""Versão SEM INSTALAR do Voxel Cut (Windows): uma pasta 'Voxel Cut' com o Voxel Cut.exe dentro, compactada em .zip.
O Voxel Cut.exe é o pythonw.exe do Python oficial (assinado pela Python Software Foundation), só renomeado; um gatilho
(.pth) faz ele abrir o programa. Assim o Windows (Controle Inteligente de Aplicativos) não barra um executável novo sem assinatura.
usage: python gerar_portatil.py [versao]"""
import os, sys, shutil, zipfile, compileall

B = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(os.path.dirname(B), "Cortador Voxel"); RT = os.path.join(B, "stage", "runtime")
VER = sys.argv[1] if len(sys.argv) > 1 else "1.1.1"
DST = os.path.join(B, "portatil", "Voxel Cut")

GATILHO = '''"""Abre o Voxel Cut quando o programa é iniciado pelo Voxel Cut.exe (versão sem instalar)."""
import os, sys


def _voxelcut():
    if os.path.basename(sys.executable).lower() != "voxel cut.exe": return
    if len(getattr(sys, "orig_argv", []) or []) > 1: return          # com argumentos = é o servidor ou o motor rodando
    raiz = os.path.dirname(sys.executable)
    try:
        import runpy
        runpy.run_path(os.path.join(raiz, "Voxel Cut.pyw"), run_name="__main__")
    except SystemExit:
        pass
    except Exception:
        import traceback
        try: open(os.path.join(raiz, "erro-ao-abrir.txt"), "w", encoding="utf-8").write(traceback.format_exc())
        except Exception: pass
    os._exit(0)


_voxelcut()
'''

LEIA = """VOXEL CUT (versão sem instalar)
===============================

COMO USAR
1) Clique com o botão direito no arquivo .zip > "Extrair tudo…" e escolha onde deixar a pasta
   (sugestão: Documentos). Não abra o programa de dentro do .zip sem extrair.
2) Abra a pasta "Voxel Cut" e dê dois cliques em "Voxel Cut.exe".
   Na primeira vez ele cria os atalhos "Voxel Cut" na área de trabalho e no menu Iniciar.
3) Cole a chave de licença que você recebeu.

Seus projetos e as peças geradas ficam em Documentos\\Voxel Cut (fora desta pasta).
Para atualizar: apague esta pasta e extraia a versão nova no mesmo lugar. Seus projetos continuam.
Não precisa de internet para usar.
"""


def main():
    shutil.rmtree(os.path.dirname(DST), ignore_errors=True)
    shutil.copytree(RT, DST, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(os.path.join(DST, "pythonw.exe"), os.path.join(DST, "Voxel Cut.exe"))          # mesmo arquivo assinado, outro nome
    sp = os.path.join(DST, "Lib", "site-packages")
    open(os.path.join(sp, "voxelcut_start.py"), "w", encoding="utf-8").write(GATILHO)
    open(os.path.join(sp, "voxelcut_start.pth"), "w", encoding="utf-8").write("import voxelcut_start\n")
    shutil.copytree(os.path.join(SRC, "app"), os.path.join(DST, "app"), ignore=shutil.ignore_patterns("__pycache__", "tools", "*.log", "smart_split_v1.py"))
    open(os.path.join(DST, "app", "versao.txt"), "w", encoding="utf-8").write(VER)
    shutil.copy2(os.path.join(SRC, "Cortador Voxel.pyw"), os.path.join(DST, "Voxel Cut.pyw"))
    open(os.path.join(DST, "instalado.txt"), "w").write("versão sem instalar\n")
    open(os.path.join(DST, "LEIA-ME.txt"), "w", encoding="utf-8").write(LEIA)
    compileall.compile_dir(os.path.join(DST, "app"), quiet=1)
    out = os.path.join(B, "saida", f"Voxel Cut {VER} (sem instalar).zip")
    # na pasta só ficam à vista o Voxel Cut.exe e o LEIA-ME: o resto vai marcado como oculto (atributo do Windows no zip;
    # o programa confere e esconde de novo na primeira vez que abre, caso o descompactador ignore o atributo)
    visiveis = {"voxel cut.exe", "leia-me.txt"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for d in sorted(os.listdir(DST)):
            if os.path.isdir(os.path.join(DST, d)):
                zi = zipfile.ZipInfo(f"Voxel Cut/{d}/"); zi.create_system = 0; zi.external_attr = 0x10 | 0x02; z.writestr(zi, b"")
        for root, _, fs in os.walk(DST):
            for f in fs:
                p = os.path.join(root, f); rel = os.path.relpath(p, os.path.dirname(DST)).replace(os.sep, "/")
                zi = zipfile.ZipInfo.from_file(p, rel); zi.compress_type = zipfile.ZIP_DEFLATED; zi.create_system = 0
                topo = os.path.dirname(p) == DST
                zi.external_attr = 0x20 | (0x02 if topo and f.lower() not in visiveis else 0)
                with open(p, "rb") as fh: z.writestr(zi, fh.read(), compresslevel=6)
        z.writestr("LEIA-ME.txt", LEIA)
    print("pronto:", out, round(os.path.getsize(out) / 1e6), "MB")


if __name__ == "__main__":
    main()
