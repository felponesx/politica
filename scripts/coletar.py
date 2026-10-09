"""CLI de coleta.

Exemplos:
  python -m scripts.coletar camara-deputados
  python -m scripts.coletar camara-votacoes inicio=2026-01-01 fim=2026-09-30
  python -m scripts.coletar siconfi-receitas ano=2025
  python -m scripts.coletar tse-candidatos ano=2024 uf=SP
  python -m scripts.coletar inicial          # carga básica de tudo que não exige chave
  python -m scripts.coletar normalizar       # refaz as tabelas normalizadas a partir do staging
  python -m scripts.coletar ligar            # refaz as ligações entre bases
  python -m scripts.coletar ibge-municipios
  python -m scripts.coletar siconfi-despesas-funcao ano=2025 esferas=U,E,C
  python -m scripts.coletar pgfn-divida-ativa ano=2025 trimestre=2
  python -m scripts.coletar tesouro-capag
  python -m scripts.coletar desastres arquivo_local=reconhecimentos.xlsx
  python -m scripts.coletar indicador-arquivo arquivo=idhm.csv nome=idhm descricao="IDHM" ano=2010
"""
import logging
import sys
from datetime import date, timedelta

from app.collectors import TAREFAS
from app.db import criar_tabelas

DATAS = {"inicio", "fim", "dia"}
INTEIROS = {"limite", "limite_por_uf", "ano", "ano_minimo", "bimestre", "quadrimestre", "tamanho", "tamanho_pagina", "trimestre", "dias", "anos", "dias_discursos"}
DECIMAIS = {"minimo_inscricao", "minimo_devedor"}
LISTAS = {"ufs", "apenas_ids", "tipos", "nomes", "esferas"}


def converter_params(brutos: dict) -> dict:
    out = {}
    for k, v in brutos.items():
        if k in DATAS:
            out[k] = date.fromisoformat(str(v))
        elif k in INTEIROS:
            out[k] = int(v)
        elif k in DECIMAIS:
            out[k] = float(v)
        elif k in LISTAS:
            out[k] = v if isinstance(v, list) else str(v).split(",")
        elif str(v).lower() in ("true", "false"):
            out[k] = str(v).lower() == "true"
        else:
            out[k] = v
    return out


def carga_inicial():
    hoje = date.today()
    inicio = hoje - timedelta(days=90)
    passos = [
        ("camara-deputados", {}), ("senado-senadores", {}), ("camara-orgaos", {}),
        ("camara-votacoes", {"inicio": inicio, "fim": hoje}),
        ("senado-votacoes", {"inicio": inicio, "fim": hoje}),
        ("camara-proposicoes", {"inicio": inicio, "fim": hoje}),
        ("senado-materias", {"ano": hoje.year}),
        ("camara-despesas", {"ano": hoje.year}),
        ("ibge-indicadores", {}),
        ("siconfi-receitas", {"ano": hoje.year - 1}),
        ("siconfi-divida", {"ano": hoje.year - 1}),
        ("pncp-contratos", {"inicio": hoje - timedelta(days=30), "fim": hoje}),
        ("obrasgov-obras", {}),
        ("receita-arrecadacao", {"ano_minimo": hoje.year - 3}),
        ("tesouro-transferencias", {"ano": hoje.year - 1}),
        ("tesouro-transferencias", {"ano": hoje.year}),
        ("legislacao-normas", {"ano": hoje.year}),
        ("camara-proposicoes-detalhe", {"ano": hoje.year}),
        # v0.2
        ("ibge-municipios", {}),
        ("ibge-indicadores-sociais", {}),
        ("siconfi-despesas-funcao", {"ano": hoje.year - 1}),
        ("tesouro-capag", {}),
        ("cnpj-fornecedores", {"limite": 200}),
        ("lexml-estaduais", {"ano": hoje.year}),
        # v0.3
        ("bcb-series", {}),
        ("congresso-agenda", {}),
        ("senado-ceaps", {"ano": hoje.year}),
        ("camara-tramitacoes", {"limite": 500}),
        ("congresso-atuacao", {}),
        ("assembleias", {}),
        ("ibge-malhas", {}),
    ]
    # Arquivos grandes do TSE (rode por estado): tse-bens ano=2022 uf=SP · tse-contas ano=2022 uf=SP
    # Exigem chave ou arquivo grande — rode à parte:
    #   transparencia-orgaos / transparencia-gastos-todos ano=2025   (chave no .env)
    #   pgfn-divida-ativa ano=2025 trimestre=2                         (≈ alguns GB)
    #   desastres arquivo_local=planilha_s2id.xlsx
    for nome, kw in passos:
        try:
            TAREFAS[nome](**kw)
        except Exception as e:  # segue para a próxima fonte; o erro fica em /coletas
            logging.error("Falhou %s: %s", nome, e)


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    criar_tabelas()
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        print("Tarefas:", ", ".join(sorted(TAREFAS)))
        return
    if argv[0] == "inicial":
        return carga_inicial()
    if argv[0] == "ligar":
        from app.ligacoes import ligar_tudo
        return print(ligar_tudo())
    if argv[0] == "normalizar":
        from app.normalizar import normalizar
        return print(normalizar())
    params = converter_params(dict(a.split("=", 1) for a in argv[1:]))
    print(f"{argv[0]}: {TAREFAS[argv[0]](**params)} itens")


if __name__ == "__main__":
    main(sys.argv[1:])
