#!/bin/sh
# Backup diário do banco às 03:30 (UTC-3 ≈ 06:30 UTC), guardando os últimos 7.
set -e
while true; do
  agora=$(date -u +%H%M)
  if [ "$agora" = "0630" ]; then
    arquivo="/backups/brasilplus-$(date -u +%Y%m%d).sql.gz"
    pg_dump -h db -U brasil brasilplus | gzip > "$arquivo.tmp" && mv "$arquivo.tmp" "$arquivo"
    ls -1t /backups/brasilplus-*.sql.gz | tail -n +8 | xargs -r rm -f
    echo "backup ok: $arquivo"
    sleep 60
  fi
  sleep 30
done
