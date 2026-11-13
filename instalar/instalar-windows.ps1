# BRASIL+ - instalador do PC principal (Windows). Rode UMA vez, como ADMINISTRADOR:
#   duplo clique em instalar\instalar-windows.cmd
# ou:  powershell -ExecutionPolicy Bypass -File instalar\instalar-windows.ps1
#
# Pode rodar de novo sem medo: nao troca senha que ja existe e nao apaga dados.
# O que faz: confere os programas, cria as senhas, guarda a chave do Gemini, cria a pasta de dados,
# agenda o coletor (a cada 5 min), sobe o sistema ao ligar o Windows, faz backup diario,
# impede o PC de dormir (na tomada) e sobe o BRASIL+.

$ErrorActionPreference = "Continue"

function Passo([string]$t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok([string]$t) { Write-Host "   ok: $t" -ForegroundColor Green }
function Aviso([string]$t) { Write-Host "   atencao: $t" -ForegroundColor Yellow }
function Falha([string]$t) { Write-Host ""; Write-Host "PAROU: $t" -ForegroundColor Red; exit 1 }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Falha "Abra o PowerShell como ADMINISTRADOR (botao direito > Executar como administrador) e rode de novo." }

$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $Aqui
Set-Location $Raiz
$Utf8 = New-Object System.Text.UTF8Encoding($false)

# ---------------------------------------------------------------------------
Passo "1. Conferindo os programas"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Falha "Falta o Docker Desktop." }
docker info *> $null
if ($LASTEXITCODE -ne 0) { Falha "O Docker nao esta rodando. Abra o Docker Desktop e espere aparecer 'Engine running'." }
Ok "Docker rodando"
& py -3.12 --version *> $null
if ($LASTEXITCODE -ne 0) { Falha "Falta o Python 3.12 (o comando 'py -3.12' nao funcionou)." }
Ok "Python 3.12"
if (-not (Test-Path (Join-Path $Raiz "docker-compose.local.yml"))) { Falha "Nao achei docker-compose.local.yml. Rode este script de dentro da pasta do projeto." }

# ---------------------------------------------------------------------------
Passo "2. Senhas e configuracao (.env.local)"
function Novo-Segredo([int]$n) {
    $alfabeto = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789".ToCharArray()
    $bytes = New-Object byte[] $n
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    return (-join ($bytes | ForEach-Object { $alfabeto[$_ % $alfabeto.Length] }))
}

function Ler-Linhas([string]$arquivo) {
    if (Test-Path $arquivo) { return , [string[]][System.IO.File]::ReadAllLines($arquivo) }
    return , [string[]]@()
}
function Valor-De($linhas, [string]$chave) {
    foreach ($l in $linhas) { if ($l -match ("^\s*" + [regex]::Escape($chave) + "\s*=(.*)$")) { return $Matches[1].Trim() } }
    return ""
}
function Definir($linhas, [string]$chave, [string]$valor) {
    $lista = New-Object System.Collections.Generic.List[string]
    $achou = $false
    foreach ($l in $linhas) {
        if (-not $achou -and $l -match ("^\s*" + [regex]::Escape($chave) + "\s*=")) { $lista.Add($chave + "=" + $valor); $achou = $true }
        else { $lista.Add($l) }
    }
    if (-not $achou) { $lista.Add($chave + "=" + $valor) }
    return , [string[]]$lista.ToArray()
}

$envLocal = Join-Path $Raiz ".env.local"
$linhas = Ler-Linhas $envLocal
foreach ($chave in @("DB_SENHA", "DB_LEITURA_SENHA")) {
    $atual = Valor-De $linhas $chave
    if ($atual -eq "") { $linhas = Definir $linhas $chave (Novo-Segredo 24); Ok "$chave criada" }
    elseif ($atual -match "[^A-Za-z0-9]") { Aviso "$chave tem simbolos (como @). Isso quebra a conexao com o banco. Troque por letras e numeros e rode de novo com o banco apagado (docker compose down -v)." }
    else { Ok "$chave ja existia (mantida)" }
}
$token = Valor-De $linhas "ADMIN_TOKEN"
if ($token.Length -lt 24) { $linhas = Definir $linhas "ADMIN_TOKEN" (Novo-Segredo 40); Ok "ADMIN_TOKEN criada (40 caracteres)" }
else { Ok "ADMIN_TOKEN ja existia (mantida)" }
[System.IO.File]::WriteAllLines($envLocal, $linhas, $Utf8)
Write-Host "   A chave do administrador (ADMIN_TOKEN) esta no arquivo .env.local. Abra-o para copiar quando for cadastrar fontes." -ForegroundColor Gray

# ---------------------------------------------------------------------------
Passo "3. Chave do Gemini (a conferencia dos dados)"
$envColetor = Join-Path $Raiz "coletor\.env"
$linhasC = Ler-Linhas $envColetor
if ((Valor-De $linhasC "GEMINI_API_KEY") -ne "") { Ok "chave do Gemini ja guardada" }
else {
    Write-Host "   Cole a chave do Gemini e aperte Enter (nao aparece na tela). Para pular, so aperte Enter." -ForegroundColor Gray
    $seg = Read-Host "   Chave do Gemini" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($seg)
    $chave = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    if ($chave.Trim() -ne "") {
        $linhasC = Definir $linhasC "GEMINI_API_KEY" $chave.Trim()
        [System.IO.File]::WriteAllLines($envColetor, $linhasC, $Utf8)
        Ok "chave guardada em coletor\.env (fica so neste PC)"
    }
    else { Aviso "sem chave do Gemini: o coletor confere so pelas regras locais. Depois, ponha GEMINI_API_KEY=... em coletor\.env." }
}

# ---------------------------------------------------------------------------
Passo "4. Pasta de dados e destino do coletor"
$pastaDados = Join-Path $Raiz "coletor-dados"
New-Item -ItemType Directory -Force -Path $pastaDados | Out-Null
$dest = Join-Path $Raiz "coletor\destinos.toml"
$precisa = $true
if (Test-Path $dest) { $txt = [System.IO.File]::ReadAllText($dest); if ($txt -match 'tipo\s*=\s*"pasta"' -and $txt -notmatch "caminho.para") { $precisa = $false } }
if ($precisa) {
    $escapada = $pastaDados.Replace("\", "\\")
    $conteudo = @("[[destino]]", 'nome = "PC"', 'tipo = "pasta"', ('pasta = "' + $escapada + '"'))
    [System.IO.File]::WriteAllLines($dest, $conteudo, $Utf8)
    Ok "destinos.toml criado (sem o marcador invisivel do Windows)"
}
else { Ok "destinos.toml ja estava certo" }

# ---------------------------------------------------------------------------
Passo "5. Tarefas automaticas do Windows"
function Registrar-Tarefa([string]$nome, [string]$script, $gatilho) {
    $acao = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"')
    $config = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
    Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config -Force | Out-Null
}
$g1 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
Registrar-Tarefa "BRASILMAIS Coletor" (Join-Path $Aqui "ciclo-coletor.ps1") $g1
Ok "BRASILMAIS Coletor: capta, confere e publica a cada 5 minutos"
$g2 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Registrar-Tarefa "BRASILMAIS Sistema" (Join-Path $Aqui "subir-sistema.ps1") $g2
Ok "BRASILMAIS Sistema: sobe o BRASIL+ quando voce entra no Windows"
$g3 = New-ScheduledTaskTrigger -Daily -At 3:30am
Registrar-Tarefa "BRASILMAIS Backup" (Join-Path $Aqui "backup-coletor.ps1") $g3
Ok "BRASILMAIS Backup: copia diaria do que o coletor guarda, as 3:30"
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
Ok "o PC nao dorme mais enquanto estiver na tomada"

# ---------------------------------------------------------------------------
Passo "6. Subindo o BRASIL+ (a primeira vez demora alguns minutos)"
docker compose -f docker-compose.local.yml --env-file .env.local up -d --build
if ($LASTEXITCODE -ne 0) { Falha "o docker compose nao subiu. Rode: docker compose -f docker-compose.local.yml --env-file .env.local logs" }
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/pronto" -TimeoutSec 5
        if ($r.status -eq "ok") { $ok = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
}
if ($ok) { Ok "BRASIL+ respondendo em http://127.0.0.1:8000" }
else { Aviso "o BRASIL+ ainda nao respondeu em /pronto. Veja: docker compose -f docker-compose.local.yml --env-file .env.local logs api" }

$ts = "C:\Program Files\Tailscale\tailscale.exe"
if (Test-Path $ts) {
    & $ts serve --bg 8000 *> $null
    Ok "acesso pelo celular (Tailscale) ligado"
}
else { Aviso "Tailscale nao encontrado: para o celular, instale o Tailscale e rode: tailscale serve --bg 8000" }

Start-ScheduledTask -TaskName "BRASILMAIS Coletor"

Write-Host ""
Write-Host "PRONTO." -ForegroundColor Green
Write-Host "  Painel:   http://127.0.0.1:8000/painel"
Write-Host "  Site:     http://127.0.0.1:8000"
Write-Host "  Proximo:  confira o Gemini com:  cd coletor ; py -3.12 coletor.py gemini-teste"
Write-Host "  Fontes:   cadastre pelo painel (a chave do administrador esta em .env.local, linha ADMIN_TOKEN)."
