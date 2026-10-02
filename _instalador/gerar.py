"""Refaz o instalador com o código atual de ../Cortador Voxel.
usage: python gerar.py [versao]      (o runtime/ do stage é reaproveitado; apague stage/runtime para refazer o Python)"""
import os, sys, shutil, re, subprocess

B = os.path.dirname(os.path.abspath(__file__)); SRC = os.path.join(os.path.dirname(B), "Cortador Voxel"); S = os.path.join(B, "stage")
if not os.path.isdir(os.path.join(S, "runtime")): sys.exit("stage/runtime não existe: monte o Python embutido primeiro")
for d in ("engine", "viewer"):
    shutil.rmtree(os.path.join(S, "app", d), ignore_errors=True)
    shutil.copytree(os.path.join(SRC, "app", d), os.path.join(S, "app", d), ignore=shutil.ignore_patterns("__pycache__"))
for f in ("server.py", "licenca.py", "icone.ico", "parar.py"): shutil.copy2(os.path.join(SRC, "app", f), os.path.join(S, "app", f))
shutil.copy2(os.path.join(SRC, "Cortador Voxel.pyw"), os.path.join(S, "Voxel Cut.pyw"))
if os.path.exists(os.path.join(S, "Cortador Voxel.pyw")): os.remove(os.path.join(S, "Cortador Voxel.pyw"))
if os.path.exists(os.path.join(S, "app", "parar.ps1")): os.remove(os.path.join(S, "app", "parar.ps1"))
iss = os.path.join(B, "CortadorVoxel.iss")
if len(sys.argv) > 1: open(os.path.join(S, "app", "versao.txt"), "w", encoding="utf-8").write(sys.argv[1])   # aparece na tela inicial e no servidor.log

# ---- assinatura digital (Smart App Control / SmartScreen). Preencha assinatura.json quando tiver o certificado.
import json, glob
CFG = os.path.join(B, "assinatura.json")
if not os.path.exists(CFG):
    json.dump({"ativo": False, "certificado": "nome que aparece no certificado (ex.: Domenico ...)", "signtool": "",
               "timestamp": "http://time.certum.pl"}, open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
cfg = json.load(open(CFG, encoding="utf-8"))
extra = []
if cfg.get("ativo"):
    st = cfg.get("signtool") or next(iter(sorted(glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe"), reverse=True)), "")
    if not os.path.exists(st): sys.exit("signtool.exe não encontrado: instale o Windows SDK ou indique o caminho em assinatura.json")
    base = [st, "sign", "/n", cfg["certificado"], "/fd", "sha256", "/tr", cfg["timestamp"], "/td", "sha256"]
    alvos = [p for p in glob.glob(os.path.join(S, "**", "*"), recursive=True) if p.lower().endswith((".exe", ".dll", ".pyd"))]
    sem = [p for p in alvos if subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-AuthenticodeSignature -LiteralPath '{p}').Status"], capture_output=True, text=True).stdout.strip() != "Valid"]
    print(f"assinando {len(sem)} arquivos sem assinatura…")
    for i in range(0, len(sem), 40): subprocess.run(base + sem[i:i + 40], check=True)
    q = '$q'; extra = ["/DASSINAR", f"/Sassinar={q}{st}{q} sign /n {q}{cfg['certificado']}{q} /fd sha256 /tr {cfg['timestamp']} /td sha256 {q}$f{q}"]
if len(sys.argv) > 1:
    s = open(iss, encoding="utf-8").read(); s = re.sub(r'#define AppVersion "[^"]*"', f'#define AppVersion "{sys.argv[1]}"', s)
    open(iss, "w", encoding="utf-8").write(s)
iscc = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Inno Setup 6", "ISCC.exe")
subprocess.run([iscc, "/Q"] + extra + [iss], check=True, cwd=B)
print("pronto:", os.listdir(os.path.join(B, "saida")))
