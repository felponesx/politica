# BRASIL+ - um ciclo do coletor: captar, conferir (regras + Gemini) e publicar na pasta que o BRASIL+ le.
# Chamado pela tarefa automatica do Windows a cada 5 minutos. Pode ser rodado a mao tambem.
$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $Aqui
$Pasta = Join-Path $Raiz "coletor"
Set-Location $Pasta

$Log = Join-Path $Pasta "ciclo.log"
if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 5MB)) { Move-Item -Force $Log ($Log + ".antigo") }

$Exe = Join-Path $Pasta "coletor.exe"
function Rodar([string]$comando) {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $comando" | Out-File -Append -Encoding utf8 $Log
    if (Test-Path $Exe) { & $Exe $comando 2>&1 | Out-File -Append -Encoding utf8 $Log }
    else { & py -3.12 coletor.py $comando 2>&1 | Out-File -Append -Encoding utf8 $Log }
}

Rodar "coletar"
Rodar "verificar"
Rodar "publicar"
