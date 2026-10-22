"""Coleta no GitHub Actions (.github/workflows/coletar-dados.yml).

  python -m scripts.coleta_ci coletar   # roda as tarefas, cada uma num processo com limite de tempo
  python -m scripts.coleta_ci resumo    # tabela das coletas (vai para o resumo do Actions)

Sem a variável TAREFAS roda a carga inicial (scripts/coletar.py). Com ela, roda só as tarefas pedidas,
separadas por ponto e vírgula: TAREFAS="tse-resultados ano=2022 uf=SP; tse-resultados ano=2018 uf=SP".
Uma tarefa que trava não derruba as outras, e a coleta para antes do limite do Actions para sobrar tempo
de gerar a cópia dos dados.
"""
import os
import subprocess
import sys
import time
from datetime import date, timedelta

LIMITE_TAREFA = int(os.environ.get("LIMITE_TAREFA_MIN", "45")) * 60
ORCAMENTO = int(os.environ.get("ORCAMENTO_MIN", "300")) * 60


def _arg(v):
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return ",".join(map(str, v))
    return str(v)


# limite de tempo por tarefa (minutos); as demais usam LIMITE_TAREFA_MIN
LIMITES = {"pncp-contratos": 60, "tse-resultados": 110, "tse-candidatos": 40, "cnpj-fornecedores": 25,
           "receita-recuperacao-judicial": 170, "siconfi-tributos": 150,
           # base inteira do CNPJ (10 arquivos de estabelecimentos e 10 de empresas) + PGFN: a coleta para sozinha em 200 min
           "receita-empresas-porte": 215, "obrasgov-obras": 130, "siconfi-despesas-funcao": 170}
# eleições: não fazem parte da carga inicial (arquivos grandes), mas o site precisa delas
ELEICOES = [("tse-candidatos", {"ano": 2022}), ("tse-candidatos", {"ano": 2024, "apenas_eleitos": "true"}),
            ("tse-resultados", {"ano": 2024}), ("tse-candidatos", {"ano": 2026}), ("tse-resultados", {"ano": 2026}),
            ("tse-candidatos", {"ano": 2018}), ("tse-resultados", {"ano": 2018}),
            ("tse-candidatos", {"ano": 2020, "apenas_eleitos": "true"}), ("tse-resultados", {"ano": 2020})]
# segurança pública: Sisdepen (semestral), Anuário (anual) e Sinesp (mensal; ano passado completo e o atual)
# sem chave: orçamento por órgão (Portal da Transparência, arquivo anual) e notícias de política
EXTRAS = [*[("transparencia-orcamento", {"ano": a}) for a in range(2014, date.today().year + 1)],
          ("noticias-politica", {}), ("bcb-scr-estados", {}), ("ibge-empresas-economia", {}), ("ibge-saneamento", {}),
          # anos anteriores para os gráficos em linha dos estados (retorno por R$ 1 e dívida do governo estadual)
          ("receita-arrecadacao", {"ano_minimo": date.today().year - 6}),
          *[("tesouro-transferencias", {"ano": a}) for a in range(date.today().year - 6, date.today().year - 1)],
          *[("siconfi-divida", {"ano": a}) for a in range(date.today().year - 6, date.today().year - 1)],
          # situação de cada proposição (arquivo anual da Câmara): anos recentes; o histórico desde 1985 vai no HISTORICO
          ("camara-proposicoes-situacao", {"desde": date.today().year - 3}),
          # gastos por função (SICONFI RREO, desde 2015): anos fechados e o ano atual até o último bimestre publicado
          *[("siconfi-despesas-funcao", {"ano": a}) for a in range(2015, date.today().year)],
          ("siconfi-despesas-funcao", {"ano": date.today().year, "bimestre": max(1, (date.today().month - 2) // 2)}),
          # impostômetro: impostos de cada estado e de cada prefeitura no último ano fechado (RREO Anexo 03)
          ("siconfi-tributos", {"ano": date.today().year - 1, "esferas": "E"}),
          ("siconfi-tributos", {"ano": date.today().year - 1, "esferas": "M"})]
# histórico desde 1985 (volta das eleições diretas) dos tipos de proposição de maior peso; os PLs ordinários são volume demais
HISTORICO = [("camara-proposicoes", {"inicio": date(a, 1, 1), "fim": min(date(a + 4, 12, 31), date.today()),
                                       "tipos": ["PEC", "PLP", "MPV", "PDL", "PDC", "PLN"]})
             for a in range(1985, date.today().year + 1, 5)] + (
    # anos antigos mudam pouco: a situação desde 1985 é atualizada só aos domingos (um arquivo grande por ano)
    [("camara-proposicoes-situacao", {"desde": 1985})] if date.today().weekday() == 6 else [])
SEGURANCA = [("seguranca-prisional", {"todos": "true"}), ("seguranca-anuario", {"todas": "true"}), ("seguranca-efetivo", {}), ("isp-rj-batalhoes", {}),
             *[("seguranca-sinesp", {"ano": a}) for a in range(2015, date.today().year + 1)]]


def comandos():
    pedidas = os.environ.get("TAREFAS", "").strip()
    if pedidas:
        # "midia" só liga o passo de fotos e logos do robô; não é uma coleta
        return [linha.split() for linha in pedidas.split(";") if linha.strip() and linha.strip() != "midia"]
    from scripts.coletar import passos_iniciais
    hoje = date.today()
    passos = []
    for nome, kw in passos_iniciais():
        if nome == "pncp-contratos":  # ~9.600 contratos por dia: no robô, só a última semana
            kw = {**kw, "inicio": hoje - timedelta(days=int(os.environ.get("PNCP_DIAS", "7")))}
        if nome == "cnpj-fornecedores":
            kw = {**kw, "limite": int(os.environ.get("CNPJ_LIMITE", "150"))}
        passos.append((nome, kw))
    # os CNPJs dependem da cota e dos contratos; o resultado de 2022 (arquivo de ~580 MB) fica por último
    cnpj = [p for p in passos if p[0] == "cnpj-fornecedores"]
    # a base do CNPJ (recuperação judicial) baixa vários GB devagar: fica no fim, com o tempo que sobrar
    passos = ([p for p in passos if p[0] != "cnpj-fornecedores"] + ELEICOES + SEGURANCA + EXTRAS + HISTORICO + cnpj + [("tse-resultados", {"ano": 2022})]
              + [("receita-recuperacao-judicial", {"minutos": 150})])
    return [[nome, *(f"{k}={_arg(v)}" for k, v in kw.items())] for nome, kw in passos]


def coletar():
    t0 = time.monotonic()
    for cmd in comandos():
        resto = ORCAMENTO - (time.monotonic() - t0)
        if resto < 120:
            print(f"::warning::Sem tempo para {' '.join(cmd)}; ficou para a próxima coleta.", flush=True)
            continue
        ini = time.monotonic()
        print(f"::group::{' '.join(cmd)}", flush=True)
        try:
            limite = LIMITES.get(cmd[0], LIMITE_TAREFA // 60) * 60
            r = subprocess.run([sys.executable, "-m", "scripts.coletar", *cmd], timeout=min(limite, resto))
            situacao = "ok" if r.returncode == 0 else f"saiu com código {r.returncode}"
        except subprocess.TimeoutExpired:
            situacao = "interrompida por tempo"
        print("::endgroup::", flush=True)
        print(f"{' '.join(cmd)}: {situacao} em {(time.monotonic() - ini) / 60:.1f} min", flush=True)


def resumo():
    from sqlalchemy import select

    from app.db import SessionLocal, criar_tabelas
    from app.models import Coleta
    criar_tabelas()
    with SessionLocal() as db:
        coletas = db.scalars(select(Coleta).order_by(Coleta.id)).all()
    print("| Tarefa | Parâmetros | Situação | Itens | Minutos | Erro |")
    print("|---|---|---|---:|---:|---|")
    for c in coletas:
        dur = (c.fim - c.inicio).total_seconds() / 60 if c.fim and c.inicio else 0
        erro = (c.erro or "").replace("|", "/").replace("\n", " ")[:300]
        print(f"| {c.fonte}-{c.tarefa} | {c.parametros or ''} | {c.status} | {c.itens or 0} | {dur:.1f} | {erro} |")


if __name__ == "__main__":
    {"coletar": coletar, "resumo": resumo}[sys.argv[1] if len(sys.argv) > 1 else "coletar"]()
