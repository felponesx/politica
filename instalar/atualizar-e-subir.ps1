# Atualiza o BRASIL+ neste PC e abre de novo, em um comando so.
# Uso (PowerShell, na pasta do projeto):
#   powershell -ExecutionPolicy Bypass -File instalar\atualizar-e-subir.ps1
# Seus dados (pasta BRASILMais, banco, chaves) NAO sao tocados: so o programa e gerado de novo.
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
function Passo($t) { Write-Host "== $t" -ForegroundColor Cyan }
function Falha($t) { Write-Host "ERRO: $t" -ForegroundColor Red; exit 1 }

Passo "1/4 Baixando a versao nova (o programa continua aberto ate aqui)"
git pull --ff-only origin ingestao-coletor-celular
if ($LASTEXITCODE -ne 0) { Falha "o git nao conseguiu atualizar. Nada foi alterado no programa." }

Passo "2/4 Fechando o BRASIL+ (se estiver aberto)"
Get-Process BRASILMais -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

Passo "3/4 Gerando o programa novo (alguns minutos)"
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "construir-tudo.ps1")
if ($LASTEXITCODE -ne 0) { Falha "nao consegui gerar o programa. Rode este comando de novo; seus dados estao intactos." }
$exe = Join-Path $raiz "build-exe\dist\BRASILMais\BRASILMais.exe"
if (-not (Test-Path $exe)) { Falha "o programa novo nao apareceu em $exe" }

Passo "4/4 Abrindo o BRASIL+"
Start-Process $exe
Write-Host ""
Write-Host "Pronto. Painel no PC: http://127.0.0.1:8000/painel" -ForegroundColor Green
Write-Host "No celular (Tailscale): https://desktop-6u78g9u.tail12b04d.ts.net/painel"
