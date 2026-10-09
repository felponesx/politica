#!/bin/sh
# Roda só na criação do banco: cria o usuário que a API usa (só consegue LER).
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE brasil_leitura LOGIN PASSWORD '${DB_LEITURA_SENHA}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO brasil_leitura;
GRANT USAGE ON SCHEMA public TO brasil_leitura;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO brasil_leitura;
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT SELECT ON TABLES TO brasil_leitura;
SQL
