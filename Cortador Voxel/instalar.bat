@echo off
chcp 65001 >nul
title Instalar Cortador Voxel
cd /d "%~dp0"
echo.
echo  === Instalando o Cortador Voxel ===
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo  Python nao encontrado. Instalando o Python 3.12 pelo winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo  Python instalado. FECHE esta janela e rode o instalar.bat de novo.
  pause
  exit /b
)
echo  Instalando as bibliotecas (numpy, scipy, shapely, manifold3d, fast-simplification, scikit-image)...
python -m pip install --upgrade numpy scipy shapely manifold3d fast-simplification scikit-image
if errorlevel 1 ( echo  ERRO ao instalar as bibliotecas. & pause & exit /b )
echo.
echo  Criando atalhos na area de trabalho e no menu Iniciar...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$A=(Get-Location).Path; $py=(Get-Command python).Source; $pyw=Join-Path (Split-Path $py) 'pythonw.exe'; $ws=New-Object -ComObject WScript.Shell;" ^
  "foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'),$A)){ $s=$ws.CreateShortcut((Join-Path $d 'Cortador Voxel.lnk')); $s.TargetPath=$pyw; $s.Arguments='\"'+$A+'\Cortador Voxel.pyw\"'; $s.WorkingDirectory=$A; $s.IconLocation=$A+'\app\icone.ico,0'; $s.Save() }"
if not exist projetos mkdir projetos
echo.
echo  Pronto! Abra pelo atalho "Cortador Voxel" na area de trabalho.
pause
