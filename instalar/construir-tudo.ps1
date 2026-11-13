# BRASIL+ - gera o PROGRAMA UNICO (banco, captura, Gemini, API, site e painel em um .exe).
# Rode uma vez (e de novo quando o codigo for atualizado). Precisa so do Python 3.12:
#   powershell -ExecutionPolicy Bypass -File instalar\construir-tudo.ps1
# Resultado: build-exe\dist\BRASILMais\BRASILMais.exe
# Seus dados ficam em  C:\Users\<voce>\BRASILMais  (banco, config, coletor, site), separados do programa:
# gerar o .exe de novo NUNCA apaga o banco.
$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $Aqui
Set-Location $Raiz

Get-Process -Name BRASILMais -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "== Instalando as bibliotecas (a primeira vez demora)" -ForegroundColor Cyan
py -3.12 -m pip install --user --quiet -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Host "Nao consegui instalar as bibliotecas." -ForegroundColor Red; exit 1 }

Write-Host "== Gerando o programa (alguns minutos)" -ForegroundColor Cyan
$dist = Join-Path $Raiz "build-exe\dist"
$obra = Join-Path $Raiz "build-exe\obra"
py -3.12 -m PyInstaller --noconfirm --clean --name BRASILMais --onedir `
    --paths "$Raiz\coletor" --distpath $dist --workpath $obra --specpath $obra `
    --collect-submodules uvicorn --collect-submodules alembic --collect-submodules apscheduler `
    --collect-submodules app --collect-submodules scripts `
    --add-data "$Raiz\app\dados;app/dados" --add-data "$Raiz\app\static;app/static" `
    --add-data "$Raiz\migrations;migrations" --add-data "$Raiz\alembic.ini;." `
    --add-data "$Raiz\coletor\vinculos;coletor/vinculos" `
    "$Raiz\executavel.py"
if ($LASTEXITCODE -ne 0) { Write-Host "O PyInstaller falhou." -ForegroundColor Red; exit 1 }

Write-Host "== Copiando a pasta do site para os seus dados (so o que falta)" -ForegroundColor Cyan
$base = Join-Path $env:USERPROFILE "BRASILMais"
New-Item -ItemType Directory -Force -Path $base | Out-Null
robocopy "$Raiz\site" (Join-Path $base "site") /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null

$exe = Join-Path $dist "BRASILMais\BRASILMais.exe"
Write-Host ""
Write-Host "PRONTO: $exe" -ForegroundColor Green
Write-Host "  Abrir agora:               & `"$exe`""
Write-Host "  Abrir ao ligar o Windows:  & `"$exe`" --iniciar-com-windows   (rode como administrador)"
Write-Host "  Seus dados:                $base"
Write-Host "  Chave do administrador:    linha ADMIN_TOKEN em $base\config.env"
