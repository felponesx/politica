"""Busca unificada em português.

Postgres: full-text search com dicionário 'portuguese' (stemming: "educação" acha "educacional")
+ unaccent (sem acento acha com acento) e trigramas para nomes de pessoas.
SQLite (dev/testes): LIKE simples.
Os índices correspondentes são criados na migração 0002.
"""
from sqlalchemy import text

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
        linhas = db.execute(text(sql), {"q": q, "qlike": _sem_curinga(q), "lim": max(1, min(int(limite), 50))}).mappings().all()
        if linhas:
            resultado[tabela] = [dict(l) for l in linhas]
    return resultado
