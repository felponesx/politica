"""Busca unificada em português.

Postgres: full-text search com dicionário 'portuguese' (stemming: "educação" acha "educacional")
+ unaccent (sem acento acha com acento) e trigramas para nomes de pessoas.
SQLite (dev/testes/programa único): LIKE simples.
Nos nomes de pessoa e município, quando há poucos resultados exatos, completa com nomes parecidos (app/nomes.py):
pronúncia do português + erro de digitação, nos dois bancos e sem IA.
Os índices correspondentes são criados na migração 0002.
"""
import logging
import time

from sqlalchemy import bindparam, text

from app.nomes import IndiceNomes

log = logging.getLogger("brasilplus.busca")

# tabela -> (expressão de texto, modo, título, subtítulo)
ENTIDADES = {
    "parlamentares": ("nome", "nome", "nome", "casa || ' · ' || coalesce(partido, '') || '-' || coalesce(uf, '')"),
    "candidatos": ("coalesce(nome_urna, '') || ' ' || coalesce(nome, '')", "nome", "coalesce(nome_urna, nome)",
                   "coalesce(cargo, '') || ' · ' || coalesce(partido, '') || ' · ' || ano"),
    "proposicoes": ("coalesce(sigla_tipo, '') || ' ' || coalesce(numero, '') || ' ' || coalesce(ementa, '')", "texto",
                    "coalesce(sigla_tipo, '') || ' ' || coalesce(numero, '') || '/' || coalesce(cast(ano as varchar), '')",
                    "coalesce(ementa, '')"),
    "normas": ("coalesce(tipo, '') || ' ' || coalesce(numero, '') || ' ' || coalesce(ementa, '')", "texto",
               "coalesce(tipo, '') || ' ' || coalesce(numero, '') || '/' || coalesce(cast(ano as varchar), '')",
               "coalesce(ementa, '')"),
    "votacoes": ("coalesce(materia, '') || ' ' || coalesce(descricao, '') || ' ' || coalesce(ementa, '')", "texto",
                 "coalesce(materia, descricao, '')", "casa || ' · ' || coalesce(cast(data as varchar), '')"),
    "contratos": ("coalesce(objeto, '') || ' ' || coalesce(fornecedor, '') || ' ' || coalesce(orgao, '')", "texto",
                  "coalesce(objeto, '')", "coalesce(orgao, '') || ' · ' || coalesce(uf, '')"),
    "municipios": ("nome", "nome", "nome", "'Município · ' || uf"),
    "obras": ("coalesce(nome, '') || ' ' || coalesce(descricao, '')", "texto", "coalesce(nome, '')",
              "coalesce(situacao, '') || ' · ' || coalesce(uf, '')"),
}


def tsvector(expr: str) -> str:
    return f"to_tsvector('portuguese'::regconfig, f_unaccent({expr}))"


def _sem_curinga(q: str) -> str:
    """% e _ digitados pelo usuário valem como letras comuns nos LIKE/ILIKE (senão uma busca só com '%' varre a tabela inteira)."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_INDICES: dict[str, tuple[float, IndiceNomes | None]] = {}   # tabela -> (quando expira, índice de nomes)
_VALIDADE_S = 600          # o índice dos nomes é refeito a cada 10 minutos (coleta nova entra sozinha)
_MAX_NOMES = 400_000       # tabela maior que isso (ex.: todas as candidaturas) fica sem busca aproximada: não cabe na memória à toa


def _indice(db, tabela: str, expr: str) -> IndiceNomes | None:
    agora = time.monotonic()
    guardado = _INDICES.get(tabela)
    if guardado and guardado[0] > agora:
        return guardado[1]
    linhas = db.execute(text(f"SELECT id, {expr} AS nome FROM {tabela} LIMIT {_MAX_NOMES + 1}")).all()
    indice = None
    if len(linhas) > _MAX_NOMES:
        log.warning("busca aproximada desligada em %s: mais de %s nomes", tabela, _MAX_NOMES)
    else:
        indice = IndiceNomes([(i, n) for i, n in linhas if n])
    _INDICES[tabela] = (agora + _VALIDADE_S, indice)
    return indice


def _aproximados(db, tabela: str, expr: str, titulo: str, sub: str, q: str, quantos: int, ja: set) -> list[dict]:
    """Nomes parecidos com a consulta (erro de digitação ou de grafia: Nicolas/Nikolas, Ferrera/Ferreira), sem IA e sem custo."""
    indice = _indice(db, tabela, expr)
    if indice is None:
        return []
    achados = [(i, n) for i, _nome, n in indice.buscar(q, quantos + len(ja)) if i not in ja][:quantos]
    if not achados:
        return []
    nota = {i: n for i, n in achados}
    sql = text(f"SELECT id, {titulo} AS titulo, {sub} AS subtitulo FROM {tabela} WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))
    linhas = [dict(l) for l in db.execute(sql, {"ids": list(nota)}).mappings().all()]
    for l in linhas:
        l["relevancia"], l["aproximado"] = nota[l["id"]], True
    return sorted(linhas, key=lambda l: -l["relevancia"])


def buscar(db, q: str, tipos: list[str] | None = None, limite: int = 10) -> dict:
    q = q.replace("\x00", "").strip()[:120]  # NUL derruba o Postgres (erro 500)
    postgres = db.bind.dialect.name == "postgresql"
    resultado = {}
    for tabela in tipos or ENTIDADES:
        expr, modo, titulo, sub = ENTIDADES[tabela]
        if postgres and modo == "texto":
            sql = (f"SELECT id, {titulo} AS titulo, {sub} AS subtitulo, ts_rank({tsvector(expr)}, consulta) AS relevancia "
                   f"FROM {tabela}, websearch_to_tsquery('portuguese'::regconfig, f_unaccent(:q)) consulta "
                   f"WHERE {tsvector(expr)} @@ consulta ORDER BY relevancia DESC LIMIT :lim")
        elif postgres:
            # parte do nome (ILIKE) OU parecido (trigramas, usa o índice gin): "Zulmira" acha "Zulmíra" e "Zulmra"
            parecido = f" OR f_unaccent({expr}) % f_unaccent(:q)" if len(q) >= 4 else ""
            sql = (f"SELECT id, {titulo} AS titulo, {sub} AS subtitulo, similarity(f_unaccent({expr}), f_unaccent(:q)) AS relevancia "
                   f"FROM {tabela} WHERE f_unaccent({expr}) ILIKE '%' || f_unaccent(:qlike) || '%' ESCAPE '\\'{parecido} "
                   f"ORDER BY relevancia DESC LIMIT :lim")
        else:
            sql = (f"SELECT id, {titulo} AS titulo, {sub} AS subtitulo, 1.0 AS relevancia "
                   f"FROM {tabela} WHERE {expr} LIKE '%' || :qlike || '%' ESCAPE '\\' LIMIT :lim")
        lim = max(1, min(int(limite), 50))
        linhas = [dict(l) for l in db.execute(text(sql), {"q": q, "qlike": _sem_curinga(q), "lim": lim}).mappings().all()]
        if modo == "nome" and len(q) >= 3 and len(linhas) < lim:   # poucos resultados exatos: completa com nomes parecidos
            linhas += _aproximados(db, tabela, expr, titulo, sub, q, lim - len(linhas), {l["id"] for l in linhas})
        if linhas:
            resultado[tabela] = linhas
    return resultado
