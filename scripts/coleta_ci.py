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
from datetime import date

LIMITE_TAREFA = int(os.environ.get("LIMITE_TAREFA_MIN", "45")) * 60
ORCAMENTO = int(os.environ.get("ORCAMENTO_MIN", "270")) * 60


def _arg(v):
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return ",".join(map(str, v))
    return str(v)


def comandos():
    pedidas = os.environ.get("TAREFAS", "").strip()
    if pedidas:
        return [linha.split() for linha in pedidas.split(";") if linha.strip()]
    from scripts.coletar import passos_iniciais
    passos = passos_iniciais()
    # as mais demoradas vão para o fim, para o resto não esperar por elas (a cota antes dos CNPJs, que dependem dela)
    lentas = [p for nome in ("camara-despesas", "cnpj-fornecedores") for p in passos if p[0] == nome]
    passos = [p for p in passos if p not in lentas] + lentas
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
            r = subprocess.run([sys.executable, "-m", "scripts.coletar", *cmd], timeout=min(LIMITE_TAREFA, resto))
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
