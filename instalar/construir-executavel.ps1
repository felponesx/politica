# BRASIL+ - transforma o coletor em um programa (coletor\coletor.exe), sem precisar do Python para rodar.
# Rode uma vez (e de novo quando o coletor for atualizado):
#   powershell -ExecutionPolicy Bypass -File instalar\construir-executavel.ps1
# O programa fica ao lado do coletor.py e usa a mesma pasta de dados, os vinculos, o .env e o destinos.toml.
# Obs.: alguns antivirus estranham programas feitos com PyInstaller. O codigo e o do proprio coletor.py.
$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $Aqui
$Pasta = Join-Path $Raiz "coletor"
Set-Location $Pasta

py -3.12 -m pip install --user --quiet pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Host "Nao consegui instalar o PyInstaller." -ForegroundColor Red; exit 1 }

$tmp = Join-Path $env:TEMP "coletor-build"
py -3.12 -m PyInstaller --onefile --noconfirm --clean --name coletor --distpath "." --workpath $tmp --specpath $tmp coletor.py
if ($LASTEXITCODE -ne 0) { Write-Host "O PyInstaller falhou." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Pronto: coletor\coletor.exe" -ForegroundColor Green
Write-Host "A tarefa automatica passa a usar o .exe sozinha. Para testar:  cd coletor ; .\coletor.exe status"
