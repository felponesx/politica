#!/bin/sh
# Roda a suíte inteira num Postgres descartável e vazio (os testes deixam dados no banco: um banco sujo faz testes falharem).
# Uso: PGHOST=/tmp PGPORT=5544 PGUSER=postgres sh scripts/testar_postgres.sh
set -e
BD=${BD:-teste_$$}
psql -q -d postgres -c "drop database if exists $BD" -c "create database $BD"
psql -q -d "$BD" -c "create extension unaccent" -c "create extension pg_trgm"
DATABASE_URL="postgresql+psycopg://${PGUSER:-postgres}@${PGHOST_TCP:-localhost}:${PGPORT:-5432}/$BD" python -m pytest -q "$@"
psql -q -d postgres -c "drop database $BD"
