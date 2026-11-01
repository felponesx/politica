#!/bin/sh
# Backup diário do banco às 03:30 (UTC-3 ≈ 06:30 UTC), guardando os últimos 7.
# Arquivos só legíveis pelo dono (umask 077), conferidos com gzip -t e com soma SHA-256 ao lado.
# Para provar que o backup restaura: sh infra/testar_restauracao.sh <arquivo.sql.gz>
set -e
umask 077
while true; do
  agora=$(date -u +%H%M)
  if [ "$agora" = "0630" ]; then
    arquivo="/backups/brasilplus-$(date -u +%Y%m%d).sql.gz"
    pg_dump -h db -U brasil --no-owner brasilplus | gzip > "$arquivo.tmp"
    gzip -t "$arquivo.tmp"                       # arquivo íntegro? (se falhar, o `set -e` interrompe e o antigo fica)
    mv "$arquivo.tmp" "$arquivo"
    (cd /backups && sha256sum "$(basename "$arquivo")" > "$(basename "$arquivo").sha256")
    ls -1t /backups/brasilplus-*.sql.gz | tail -n +8 | xargs -r rm -f
    ls -1t /backups/brasilplus-*.sql.gz.sha256 | tail -n +8 | xargs -r rm -f
    echo "backup ok: $arquivo"
    sleep 60
  fi
  sleep 30
done
