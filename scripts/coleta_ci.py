"""Coleta no GitHub Actions (.github/workflows/coletar-dados.yml).

  python -m scripts.coleta_ci coletar   # roda as tarefas, cada uma num processo com limite de tempo
  python -m scripts.coleta_ci resumo    # tabela das coletas (vai para o resumo do Actions)
  python -m scripts.coleta_ci midia-atrasada   # sai com 0 se as fotos e logos precisam ser refeitos (> MIDIA_DIAS dias)

Sem a variável TAREFAS roda a carga inicial (scripts/coletar.py). Com ela, roda só as tarefas pedidas,
separadas por ponto e vírgula: TAREFAS="tse-resultados ano=2022 uf=SP; tse-resultados ano=2018 uf=SP".
Na carga completa, tarefas que mudam pouco não rodam de novo enquanto a última coleta valer (VALIDADE abaixo);
quem pede tarefas à mão sempre as recebe. Uma tarefa que trava não derruba as outras, e a coleta para antes do limite do Actions para sobrar tempo
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
LIMITES = {"pncp-contratos": 60, "tse-resultados": 110, "tse-candidatos": 40, "tse-contas": 90, "cnpj-fornecedores": 25,
           "receita-recuperacao-judicial": 170, "siconfi-tributos": 150, "saude-ubs": 40, "saude-mais-medicos": 20, "saude-datasus": 40, "ensino-ideb": 90, "cgu-sancoes": 40, "tcu-inabilitados": 15, "transparencia-social": 60, "transparencia-viagens": 40, "inpe-desmatamento": 90, "ibge-trabalho": 10, "tse-fundos": 15, "aneel-tarifas": 20,
           # base inteira do CNPJ (10 arquivos de estabelecimentos e 10 de empresas) + PGFN: a coleta para sozinha em 200 min
           "receita-empresas-porte": 215, "obrasgov-obras": 130, "siconfi-despesas-funcao": 170}
# eleições: não fazem parte da carga inicial (arquivos grandes), mas o site precisa delas
ELEICOES = [("tse-candidatos", {"ano": 2022}), ("tse-candidatos", {"ano": 2024, "apenas_eleitos": "true"}),
            ("tse-resultados", {"ano": 2024}), ("tse-candidatos", {"ano": 2026}), ("tse-resultados", {"ano": 2026}),
            ("tse-candidatos", {"ano": 2018}), ("tse-resultados", {"ano": 2018}),
            # gastos de campanha (prestação de contas) de 2002 a 2026 (2004 não traz o código do candidato); só das candidaturas já coletadas; zips de 14 MB a 1,4 GB
            *[("tse-contas", {"ano": a}) for a in (2022, 2018, 2026, 2024, 2020, 2016, 2014, 2012, 2010, 2008, 2006, 2002)],
            ("tse-candidatos", {"ano": 2020, "apenas_eleitos": "true"}), ("tse-resultados", {"ano": 2020})]
# segurança pública: Sisdepen (semestral), Anuário (anual) e Sinesp (mensal; ano passado completo e o atual)
# CAPAG dos municípios de anos anteriores (arquivos do Tesouro, um por ano) para a tabela e as linhas por ano da Saúde fiscal
CAPAG_ANOS = {
    2018: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/379e92f3-d8a9-4aa6-a23c-ca82a8f5b026/download/capag-municipios---2018.xlsx",
    2019: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/444b8cb5-6fea-4907-82d9-018aae1d68b5/download/capag-2019---municipios.xlsx",
    2020: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/f2149990-1ca4-475d-95c1-512f78079905/download/capag-municipios.xlsx",
    2021: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/10387f66-f44d-4096-811c-58e68503100a/download/capag-municipios---novembro-2021.xlsx",
    2022: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/86636c19-b38a-4b9e-8fff-30fc4208dd04/download/capag-municipios-2022.xlsx",
    2023: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/31ed778a-9115-419c-b18e-c9131a978aef/download/capag-municipios-2023.xlsx",
    2024: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/30c5fc20-634d-4558-9d45-01645b501deb/download/20241015capag-municipios.xlsx",
    2025: "https://www.tesourotransparente.gov.br/ckan/dataset/9ff93162-409e-48b5-91d9-cf645a47fdfc/resource/046f7fcf-a742-4787-9768-dbb10747d55d/download/capag-municipios-posicao-2025-nov-09---processamento-2025-nov-10.xlsx",
}
# sem chave: orçamento por órgão (Portal da Transparência, arquivo anual) e notícias de política
EXTRAS = [("transparencia-emendas", {}),
          *[("tesouro-capag", {"url": u, "ano": a}) for a, u in CAPAG_ANOS.items()],
          *[("transparencia-cartao", {"ano": a}) for a in range(2015, date.today().year + 1)],
          *[("transparencia-orcamento", {"ano": a}) for a in range(2014, date.today().year + 1)],
          ("noticias-politica", {}), ("bcb-scr-estados", {}), ("saude-ubs", {}), ("saude-mais-medicos", {}), ("saude-datasus", {}), ("ensino-ideb", {}), ("cgu-sancoes", {}), ("tcu-inabilitados", {}), ("transparencia-social", {}), ("transparencia-viagens", {}), ("inpe-desmatamento", {}), ("ibge-trabalho", {}), ("tse-fundos", {}), ("aneel-tarifas", {}), ("ibge-empresas-economia", {}), ("ibge-saneamento", {}),
          # anos anteriores para os gráficos em linha dos estados (retorno por R$ 1 e dívida do governo estadual)
          ("receita-arrecadacao", {"ano_minimo": date.today().year - 6}),
          *[("tesouro-transferencias", {"ano": a}) for a in range(date.today().year - 6, date.today().year - 1)],
          *[("siconfi-divida", {"ano": a}) for a in range(date.today().year - 6, date.today().year - 1)],
          # situação de cada proposição (arquivo anual da Câmara): anos recentes; o histórico desde 1985 vai no HISTORICO
          ("camara-proposicoes-situacao", {"desde": date.today().year - 3}),
          # situação e autoria das matérias do Senado (lista /processo): ano corrente inteiro e, dos 3 anteriores, o que ainda tramita
          ("senado-situacao", {"desde": date.today().year - 3}),
          # bancos e crédito (IF.data do Banco Central; os dados de um ano fechado só mudam quando o BC republica)
          ("bcb-financeiro", {}),
          # gastos por função (SICONFI RREO, desde 2015): anos fechados e o ano atual até o último bimestre publicado
          *[("siconfi-despesas-funcao", {"ano": a}) for a in range(2015, date.today().year)],
          ("siconfi-despesas-funcao", {"ano": date.today().year, "bimestre": max(1, (date.today().month - 2) // 2)}),
          # impostômetro: impostos de cada estado e de cada prefeitura no último ano fechado (RREO Anexo 03)
          ("siconfi-tributos", {"ano": date.today().year - 1, "esferas": "E"}),
          ("siconfi-tributos", {"ano": date.today().year - 1, "esferas": "M"})]
# histórico desde 1985 (volta das eleições diretas) dos tipos de proposição de maior peso; os PLs ordinários são volume demais
HISTORICO = [("camara-proposicoes", {"inicio": date(a, 1, 1), "fim": min(date(a + 4, 12, 31), date.today()),
                                       "tipos": ["PEC", "PLP", "MPV", "PDL", "PDC", "PLN", "REP"]})  # REP: representações por quebra de decoro (aba Processos do parlamentar)
             for a in range(1985, date.today().year + 1, 5)] + [
    # leis ordinárias, complementares e emendas desde 1988 (aba "Leis em vigor"): uma consulta curta por ano; anos fechados só uma vez por ano
    ("legislacao-normas", {"ano": a, "tipos": ["LEI", "LCP", "EMC"]}) for a in range(1988, date.today().year)] + (
    # anos antigos mudam pouco: a situação desde 1985 é atualizada só aos domingos (um arquivo grande por ano)
    [("camara-proposicoes-situacao", {"desde": 1985})] if date.today().weekday() == 6 else [])
SEGURANCA = [("seguranca-prisional", {"todos": "true"}), ("seguranca-anuario", {"todas": "true"}), ("seguranca-efetivo", {}), ("isp-rj-batalhoes", {}),
             *[("seguranca-sinesp", {"ano": a}) for a in range(2015, date.today().year + 1)]]


# tarefas da carga completa que mudam pouco: (fonte, tarefa) gravados em `coletas`, parâmetros que devem coincidir e dias de validade
VALIDADE = {
    "saude-ubs": ("saude", "ubs", (), lambda p: 25),                    # mudam devagar: uma vez por mês basta
    "saude-mais-medicos": ("saude", "mais_medicos", (), lambda p: 7),
    "saude-datasus": ("datasus", "saude", (), lambda p: 20),
    "ensino-ideb": ("inep", "ideb", (), lambda p: 60),
    "cgu-sancoes": ("cgu", "sancoes", (), lambda p: 7),
    "tcu-inabilitados": ("tcu", "inabilitados", (), lambda p: 7),
    "transparencia-social": ("transparencia", "social", (), lambda p: 25),   # um mês novo por mês
    "transparencia-viagens": ("transparencia", "viagens", (), lambda p: 25),
    "inpe-desmatamento": ("inpe", "desmatamento", (), lambda p: 30),
    "ibge-trabalho": ("ibge", "trabalho", (), lambda p: 30),
    "tse-fundos": ("tse", "fundos", (), lambda p: 90),
    "aneel-tarifas": ("aneel", "tarifas", (), lambda p: 20),                      # o CEIS/CNEP mudam todo dia útil: uma vez por semana basta
    "siconfi-tributos": ("siconfi", "tributos_entes", ("ano", "esferas"), lambda p: 30 if p.get("esferas") == "M" else None),
    # anos fechados do RREO não mudam mais; o último ano fechado é revisto todo mês
    "siconfi-despesas-funcao": ("siconfi", "despesas_funcao", ("ano",),
                                lambda p: (365 if int(p.get("ano", 0)) < date.today().year - 1 else 30 if int(p.get("ano", 0)) == date.today().year - 1 else None)),
}
VALIDADE["bcb-financeiro"] = ("bcb", "financeiro", ("ano",), lambda p: 30)
VALIDADE["legislacao-normas"] = ("senado", "legislacao", ("ano",), lambda p: 365 if int(p.get("ano", 0)) < date.today().year else None)
MIDIA_DIAS = int(os.environ.get("MIDIA_DIAS", "7"))


def ja_coletada(cmd: list[str]) -> str | None:
    """Texto "coletada há N dias" se a tarefa já rodou com os mesmos parâmetros dentro da validade; senão None."""
    regra = VALIDADE.get(cmd[0])
    if not regra:
        return None
    fonte, tarefa, chaves, dias_de = regra
    params = dict(a.split("=", 1) for a in cmd[1:] if "=" in a)
    dias = dias_de(params)
    if not dias:
        return None
    try:
        from datetime import datetime

        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models import Coleta
        with SessionLocal() as db:
            q = select(Coleta).where(Coleta.fonte == fonte, Coleta.tarefa == tarefa, Coleta.status.in_(("ok", "parcial")),
                                     Coleta.fim >= datetime.now() - timedelta(days=dias)).order_by(Coleta.fim.desc())
            for c in db.scalars(q):
                if all(str((c.parametros or {}).get(k)) == params.get(k) for k in chaves):
                    return f"coletada há {(datetime.now() - c.fim).days} dia(s), vale por {dias}"
    except Exception as e:  # sem banco ou sem a tabela: roda normalmente
        print(f"(não deu para conferir a última coleta de {cmd[0]}: {type(e).__name__})", flush=True)
    return None


def midia_atrasada(pasta: str = "site/midia"):
    """Sai com 0 quando as fotos e logos precisam ser refeitos (índice ausente ou com mais de MIDIA_DIAS dias), 1 se estão em dia."""
    import json
    try:
        gerado = date.fromisoformat(json.load(open(os.path.join(pasta, "indice.json"), encoding="utf-8"))["gerado_em"])
    except (OSError, ValueError, KeyError):
        sys.exit(0)
    sys.exit(0 if (date.today() - gerado).days >= MIDIA_DIAS else 1)


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
    manual = bool(os.environ.get("TAREFAS", "").strip())
    for cmd in comandos():
        if not manual and (motivo := ja_coletada(cmd)):
            print(f"{' '.join(cmd)}: pulada ({motivo})", flush=True)
            continue
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
    {"coletar": coletar, "resumo": resumo, "midia-atrasada": midia_atrasada}[sys.argv[1] if len(sys.argv) > 1 else "coletar"]()
