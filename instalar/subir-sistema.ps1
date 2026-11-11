# BRASIL+ - sobe o sistema (banco, agendador, API e backup) quando voce entra no Windows.
# Espera o Docker Desktop ficar pronto (ate 5 minutos) e roda "docker compose up -d".
$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $Aqui
Set-Location $Raiz

$pronto = $false
for ($i = 0; $i -lt 30; $i++) {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { $pronto = $true; break }
    Start-Sleep -Seconds 10
}
if (-not $pronto) { exit 1 }
docker compose -f docker-compose.local.yml --env-file .env.local up -d
