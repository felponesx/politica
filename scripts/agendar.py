"""Agendador das coletas do BRASIL+ (deixe rodando no servidor).

  python -m scripts.agendar            # roda para sempre, no horário de Brasília
  python -m scripts.agendar --listar   # mostra a agenda
  python -m scripts.agendar --agora diario   # roda um grupo já (agenda | diario | semanal | mensal | trimestral)

- Cada grupo roda as tarefas em sequência; uma falha não impede as próximas (o erro fica em /coletas).
- Um mesmo grupo nunca roda duas vezes ao mesmo tempo, e só um agendador roda por máquina (trava em arquivo).
- Se a mesma tarefa falhar 3 vezes seguidas, envia alerta (Telegram/webhook do .env) e avisa quando voltar.
"""
import logging
import os
import sys
import tempfile
from datetime import date, timedelta

from app.alertas import enviar
from app.collectors import TAREFAS
from app.config import settings
from app.db import criar_tabelas

log = logging.getLogger("brasilplus.agendador")
FALHAS: dict[str, int] = {}


def _trimestre_anterior(hoje: date):
    t = (hoje.month - 1) // 3  # trimestre atual - 1 (0 = 4º do ano anterior)
    return (hoje.year, t) if t else (hoje.year - 1, 4)


def grupos(hoje: date | None = None) -> dict[str, list[tuple[str, dict]]]:
    hoje = hoje or date.today()
    ano, ant = hoje.year, hoje.year - 1
    recente = {"inicio": hoje - timedelta(days=3), "fim": hoje}
    com_chave = bool(settings.transparencia_api_key)
    ta, tt = _trimestre_anterior(hoje)
    return {
        "diario": [("camara-votacoes", recente), ("senado-votacoes", recente), ("camara-proposicoes", recente),
                   ("pncp-contratos", {"inicio": hoje - timedelta(days=2), "fim": hoje}),
                   ("legislacao-normas", {"ano": ano}), ("camara-despesas", {"ano": ano}),
                   ("camara-proposicoes-detalhe", {"ano": ano}), ("bcb-series", {"anos": 2}),
                   ("camara-tramitacoes", {"limite": 800})],
        "agenda": [("congresso-agenda", {})],
        "semanal": [("saude-mais-medicos", {}), ("cgu-sancoes", {}), ("camara-deputados", {}), ("senado-senadores", {}), ("camara-orgaos", {}),
                    ("senado-materias", {"ano": ano}), ("cnpj-fornecedores", {"limite": 300}),
                    ("lexml-estaduais", {"ano": ano}), ("congresso-atuacao", {}), ("senado-ceaps", {"ano": ano}),
                    ("assembleias", {"inicio": hoje - timedelta(days=8), "fim": hoje})]
                   + ([("transparencia-orgaos", {}), ("transparencia-gastos-todos", {"ano": ano})] if com_chave else []),
        "mensal": [("ibge-indicadores", {}), ("ibge-municipios", {}), ("ibge-indicadores-sociais", {}),
                   ("siconfi-receitas", {"ano": ant}), ("siconfi-divida", {"ano": ant}),
                   ("siconfi-despesas-funcao", {"ano": ant}), ("obrasgov-obras", {}),
                   ("receita-arrecadacao", {"ano_minimo": ano - 3}), ("tesouro-transferencias", {"ano": ano}), ("saude-ubs", {}), ("saude-datasus", {}), ("ensino-ideb", {}),
                   ("tesouro-capag", {}), ("ibge-malhas", {})],
        "trimestral": [("pgfn-divida-ativa", {"ano": ta, "trimestre": tt})],
    }


def rodar_grupo(nome: str):
    for tarefa, params in grupos()[nome]:
        try:
            log.info("[%s] %s %s", nome, tarefa, params)
            TAREFAS[tarefa](**params)
            if FALHAS.get(tarefa, 0) >= 3:
                enviar(f"BRASIL+: a coleta {tarefa} voltou a funcionar.")
            FALHAS[tarefa] = 0
        except Exception as e:
            FALHAS[tarefa] = FALHAS.get(tarefa, 0) + 1
            log.error("[%s] %s falhou (%sª vez seguida): %s", nome, tarefa, FALHAS[tarefa], e)
            if FALHAS[tarefa] == 3:
                enviar(f"BRASIL+: a coleta {tarefa} falhou 3 vezes seguidas. Último erro: {type(e).__name__}: {str(e)[:300]}")


def _travar():
    """Impede dois agendadores na mesma máquina."""
    caminho = os.path.join(tempfile.gettempdir(), "brasilplus-agendador.lock")
    f = open(caminho, "w")
    try:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:  # Windows: sem trava de arquivo
        return f
    except OSError:
        sys.exit("Já existe um agendador rodando nesta máquina.")
    return f


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if argv and argv[0] == "--listar":
        for g, itens in grupos().items():
            print(f"{g}: " + ", ".join(t for t, _ in itens))
        return
    criar_tabelas()  # o agendador é quem aplica as migrações em produção
    if argv and argv[0] == "--agora":
        return rodar_grupo(argv[1])
    trava = _travar()  # noqa: F841 (mantém o arquivo aberto)
    from apscheduler.schedulers.blocking import BlockingScheduler
    s = BlockingScheduler(timezone="America/Sao_Paulo", job_defaults={"coalesce": True, "max_instances": 1,
                                                                      "misfire_grace_time": 3600})
    s.add_job(rodar_grupo, "cron", args=["diario"], hour=2, minute=10, id="diario")
    s.add_job(rodar_grupo, "cron", args=["agenda"], day_of_week="mon-fri", hour="8-21", minute="*/15", id="agenda")
    s.add_job(rodar_grupo, "cron", args=["semanal"], day_of_week="sun", hour=4, minute=0, id="semanal")
    s.add_job(rodar_grupo, "cron", args=["mensal"], day=5, hour=5, minute=0, id="mensal")
    s.add_job(rodar_grupo, "cron", args=["trimestral"], month="2,5,8,11", day=20, hour=6, minute=0, id="trimestral")
    log.info("Agendador iniciado: agenda do Congresso a cada 15 min (seg-sex, 8h-22h), diário 02:10, semanal dom 04:00, mensal dia 5 05:00, trimestral dia 20 (fev/mai/ago/nov).")
    s.start()


if __name__ == "__main__":
    main(sys.argv[1:])
