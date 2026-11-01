#!/bin/sh
# Prova que um backup restaura: cria um banco TEMPORÁRIO, restaura o arquivo, compara a contagem de linhas
# de cada tabela com o banco de origem e apaga só o banco temporário. Nunca toca no banco de origem além de ler.
# Uso: PGHOST=… PGPORT=… PGUSER=… sh infra/testar_restauracao.sh <arquivo.sql.gz> [banco_de_origem]
set -e
arq="$1"; origem="${2:-brasilplus}"; tmp="restauracao_teste_$$"
[ -f "$arq" ] || { echo "informe o arquivo de backup"; exit 2; }
if [ -f "$arq.sha256" ]; then (cd "$(dirname "$arq")" && sha256sum -c "$(basename "$arq").sha256"); fi
gzip -t "$arq"
psql -q -d postgres -c "create database $tmp"
trap 'psql -q -d postgres -c "drop database if exists $tmp" >/dev/null' EXIT
gunzip -c "$arq" | psql -q -v ON_ERROR_STOP=1 -d "$tmp" >/dev/null
conta() { psql -At -d "$1" -c "select format('%s=%s', relname, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', schemaname, relname), false, true, '')))[1]::text) from pg_stat_user_tables order by relname"; }
conta "$origem" > "/tmp/origem_$$.txt"; conta "$tmp" > "/tmp/restaurado_$$.txt"
if diff -q "/tmp/origem_$$.txt" "/tmp/restaurado_$$.txt" >/dev/null; then
  echo "RESTAURAÇÃO OK: $(wc -l < /tmp/origem_$$.txt) tabelas com a mesma contagem de linhas"; ec=0
else
  echo "RESTAURAÇÃO DIFERENTE:"; diff "/tmp/origem_$$.txt" "/tmp/restaurado_$$.txt" || true; ec=1
fi
rm -f "/tmp/origem_$$.txt" "/tmp/restaurado_$$.txt"
exit $ec
