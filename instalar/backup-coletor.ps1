# BRASIL+ - copia diaria do que o coletor guarda (arquivos originais captados e o manifesto).
# O backup diario do banco ja existe (pasta backups). Este cobre a pasta coletor\dados, que e insubstituivel:
# os arquivos originais so podem ser captados de novo se a fonte ainda os oferecer.
$Aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$Raiz = Split-Path -Parent $Aqui
$Origem = Join-Path $Raiz "coletor\dados"
$Destino = Join-Path $Raiz "backups\coletor-dados"
if (-not (Test-Path $Origem)) { exit 0 }
New-Item -ItemType Directory -Force -Path $Destino | Out-Null

# Arquivos originais: so acrescenta (nunca apaga nada no backup).
robocopy (Join-Path $Origem "raw") (Join-Path $Destino "raw") /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy (Join-Path $Origem "corrigido") (Join-Path $Destino "corrigido") /E /XO /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null

# Manifesto (SQLite): copia consistente pelo proprio SQLite, mesmo com o coletor rodando. Guarda os ultimos 7 dias.
$db = Join-Path $Origem "manifesto.db"
if (Test-Path $db) {
    $saida = Join-Path $Destino ("manifesto-" + (Get-Date -Format "yyyyMMdd") + ".db")
    & py -3.12 -c "import sqlite3,sys; a=sqlite3.connect(sys.argv[1]); b=sqlite3.connect(sys.argv[2]); a.backup(b); b.close(); a.close()" $db $saida
    Get-ChildItem $Destino -Filter "manifesto-*.db" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force
}
exit 0
