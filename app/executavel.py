"""BRASIL+ em um programa só (executável): banco SQLite, API + site + painel, agendador das coletas e o coletor com o Gemini.

Sem Docker e sem PostgreSQL. Tudo que é seu mora numa pasta fixa, separada do programa (uma versão nova do .exe nunca apaga dados):

    ~/BRASILMais/config.env           chaves e opções (ADMIN_TOKEN é criada sozinha)
    ~/BRASILMais/dados-brasilplus/    o banco (SQLite)
    ~/BRASILMais/coletor/             vínculos, destinos.toml, .env do Gemini e os arquivos originais captados
    ~/BRASILMais/coletor-dados/       o que o coletor libera para o BRASIL+ ler
    ~/BRASILMais/site/                a pasta do site (fotos e cópia dos dados)
    ~/BRASILMais/logs/

Para usar um PostgreSQL no lugar do SQLite, ponha DATABASE_URL=... no config.env.
Comandos:  BRASILMais.exe [--sem-navegador] [--base PASTA] | --iniciar-com-windows
"""
import getpass
import json
import logging
import logging.handlers
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

PORTA_PADRAO = 8000
CABECALHO = ("# Configuração do BRASIL+. Linhas NOME=valor. Variáveis do sistema têm prioridade sobre este arquivo.\n"
             "# Exemplos (opcionais): TRANSPARENCIA_API_KEY=...  PERPLEXITY_API_KEY=...  DATABASE_URL=postgresql+psycopg://...\n"
             "# NATIVAS_DESLIGADAS=camara-deputados,senado-senadores   (coletas que o coletor já faz)\n")

log = logging.getLogger("brasilplus.executavel")


def recurso(rel: str) -> Path:
    """Arquivo que vem dentro do programa (ou do repositório, quando rodado pelo código)."""
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return raiz / rel


def pasta_base(argv: list[str] | None = None) -> Path:
    argv = argv or []
    if "--base" in argv and argv.index("--base") + 1 < len(argv):
        return Path(argv[argv.index("--base") + 1]).expanduser()
    if os.environ.get("BRASILPLUS_BASE"):
        return Path(os.environ["BRASILPLUS_BASE"]).expanduser()
    if getattr(sys, "frozen", False):
        return Path.home() / "BRASILMais"   # fixa e separada do programa: reinstalar o .exe não apaga nada
    return Path.cwd()


def ler_config(arquivo: Path) -> dict:
    cfg: dict[str, str] = {}
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                cfg[k.strip()] = v.strip()
    return cfg


def preparar(base: Path, porta: int = PORTA_PADRAO) -> dict:
    """Cria o que falta (pastas, config, vínculos, destino do coletor) SEM sobrescrever nada que já exista, e põe a
    configuração no ambiente (variável do sistema > config.env > padrão). Devolve a configuração lida."""
    base.mkdir(parents=True, exist_ok=True)
    for sub in ("dados-brasilplus", "coletor", "coletor-dados", "logs"):
        (base / sub).mkdir(exist_ok=True)

    arq = base / "config.env"
    cfg = ler_config(arq)
    if len(cfg.get("ADMIN_TOKEN", "")) < 24:
        cfg["ADMIN_TOKEN"] = secrets.token_urlsafe(32)
        texto = arq.read_text(encoding="utf-8-sig") if arq.exists() else CABECALHO
        if texto and not texto.endswith("\n"):
            texto += "\n"
        arq.write_text(texto + f"ADMIN_TOKEN={cfg['ADMIN_TOKEN']}\n", encoding="utf-8")

    vinculos = base / "coletor" / "vinculos"
    if not vinculos.exists():
        origem = recurso("coletor/vinculos")
        if origem.exists():
            shutil.copytree(origem, vinculos)
        else:
            vinculos.mkdir()
    destino = base / "coletor" / "destinos.toml"
    if not destino.exists():
        destino.write_text('[[destino]]\nnome = "PC"\ntipo = "pasta"\npasta = ' + json.dumps(str(base / "coletor-dados")) + "\n",
                           encoding="utf-8")

    site = base / "site"
    padrao = {
        "DATABASE_URL": "sqlite:///" + (base / "dados-brasilplus" / "brasilplus.db").as_posix(),
        "SQLITE_WAL": "true",
        "SOMENTE_LEITURA": "false",
        "COLETOR_DADOS": str(base / "coletor-dados"),
        "COLETOR_PULL": "0",
        "COLETOR_RAIZ": str(base / "coletor"),
        "BRASIL_FONTES_URL": f"http://127.0.0.1:{porta}/fontes-cadastradas?ativa=true",
        "BRASILPLUS_SITE": str(site if site.exists() else recurso("site")),
        "PASTA_ARQUIVOS_COLETA": str(base / "dados-brasilplus"),
    }
    for k, v in {**padrao, **cfg}.items():
        os.environ.setdefault(k, v)
    os.environ.setdefault("BRASILPLUS_BASE", str(base))
    return cfg


def configurar_log(pasta: Path) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    for h in (logging.StreamHandler(), logging.handlers.RotatingFileHandler(pasta / "brasilplus.log", maxBytes=5_000_000,
                                                                          backupCount=3, encoding="utf-8")):
        h.setFormatter(fmt)
        raiz.addHandler(h)


def pedir_gemini(base: Path) -> None:
    """Primeira execução: pergunta a chave do Gemini uma vez (não aparece na tela; fica só nesta pasta)."""
    env, pulou = base / "coletor" / ".env", base / "coletor" / ".gemini-pulado"
    texto = env.read_text(encoding="utf-8-sig") if env.exists() else ""
    if os.environ.get("GEMINI_API_KEY") or "GEMINI_API_KEY=" in texto or pulou.exists():
        return
    if not sys.stdin or not sys.stdin.isatty():
        return
    chave = getpass.getpass("Chave do Gemini, para conferir os dados (não aparece na tela; Enter para pular): ").strip()
    if chave:
        env.write_text(texto + ("" if not texto or texto.endswith("\n") else "\n") + f"GEMINI_API_KEY={chave}\n", encoding="utf-8")
        os.environ["GEMINI_API_KEY"] = chave
    else:
        pulou.write_text("pulado; ponha GEMINI_API_KEY=... em coletor/.env quando quiser\n", encoding="utf-8")
        print("Sem chave do Gemini: o coletor confere só pelas regras locais. Ponha GEMINI_API_KEY=... em coletor\\.env depois.")


def ciclo_coletor() -> None:
    """Capta, confere (regras + Gemini), publica na pasta e entrega ao BRASIL+ sem esperar a próxima ingestão."""
    import coletor
    db = coletor.abrir_db()
    try:
        coletor.coletar(db, [])
        coletor.verificar(db, [])
        coletor.enviar_tudo(db, silencioso=True)
    finally:
        db.close()
    from app.collectors import TAREFAS
    TAREFAS["coletor-ingestao"]()


def _copiar_sqlite(origem: Path, destino: Path) -> None:
    """Cópia consistente pelo próprio SQLite, mesmo com o programa usando o banco."""
    import sqlite3
    a, c = sqlite3.connect(str(origem)), sqlite3.connect(str(destino))
    try:
        a.backup(c)
    finally:
        c.close()
        a.close()


def _guardar_ultimos(pasta: Path, padrao: str, quantos: int = 7) -> None:
    for velho in sorted(pasta.glob(padrao))[:-quantos]:
        velho.unlink()


def fazer_backup(base: Path | None = None) -> list[Path]:
    """Backup diário: banco do BRASIL+ e manifesto do coletor (cópia consistente, últimos 7 dias) e os arquivos originais
    captados (só acrescenta, nunca apaga). Se BACKUP_EXTRA apontar para outra pasta (disco externo, nuvem sincronizada), copia também lá."""
    base = base or Path(os.environ.get("BRASILPLUS_BASE") or Path.cwd())
    destino = base / "backups"
    destino.mkdir(exist_ok=True)
    dia = datetime.now().strftime("%Y%m%d")
    feitos: list[Path] = []

    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        banco = Path(url[len("sqlite:///"):])
        if banco.exists():
            alvo = destino / f"brasilplus-{dia}.db"
            _copiar_sqlite(banco, alvo)
            _guardar_ultimos(destino, "brasilplus-*.db")
            feitos.append(alvo)
    manifesto = base / "coletor" / "dados" / "manifesto.db"
    if manifesto.exists():
        alvo = destino / f"coletor-manifesto-{dia}.db"
        _copiar_sqlite(manifesto, alvo)
        _guardar_ultimos(destino, "coletor-manifesto-*.db")
        feitos.append(alvo)
    for sub in ("raw", "corrigido"):   # arquivos originais: insubstituíveis, só se acrescenta
        origem = base / "coletor" / "dados" / sub
        if origem.exists():
            for arq in origem.rglob("*"):
                if arq.is_file():
                    alvo_arq = destino / "coletor-dados" / sub / arq.relative_to(origem)
                    if not alvo_arq.exists():
                        alvo_arq.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(arq, alvo_arq)

    extra = os.environ.get("BACKUP_EXTRA")
    if extra:
        pasta_extra = Path(extra).expanduser()
        pasta_extra.mkdir(parents=True, exist_ok=True)
        for arq in feitos:
            shutil.copy2(arq, pasta_extra / arq.name)
        _guardar_ultimos(pasta_extra, "brasilplus-*.db")
        _guardar_ultimos(pasta_extra, "coletor-manifesto-*.db")
    log.info("Backup feito em %s", destino)
    return feitos


def proximo_ciclo(fuso, segundos: int = 30) -> datetime:
    """Primeiro ciclo do coletor, daqui a poucos segundos. Precisa ter fuso: sem ele o agendador lê o horário como o do fuso DELE
    (America/Sao_Paulo), e num computador em outro fuso o ciclo ficaria horas no futuro."""
    return datetime.now(fuso) + timedelta(seconds=segundos)


def montar_agendador():
    """Agendador em segundo plano: as tarefas do BRASIL+ e o ciclo do coletor a cada 5 minutos."""
    from apscheduler.schedulers.background import BackgroundScheduler

    from scripts.agendar import agendar_tarefas
    s = BackgroundScheduler(timezone="America/Sao_Paulo", job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    agendar_tarefas(s)
    s.add_job(ciclo_coletor, "interval", minutes=5, id="ciclo-coletor", next_run_time=proximo_ciclo(s.timezone))
    s.add_job(fazer_backup, "cron", hour=3, minute=30, id="backup")
    if os.environ.get("ENTREGA_GIT_PASTA"):   # cópia dos dados para o GitHub a cada 6 h (ver app/entrega.py)
        from app import entrega
        s.add_job(lambda: log.info("entrega: %s", entrega.entregar_se_configurado()), "interval", hours=6, id="entrega",
                  next_run_time=datetime.now(s.timezone) + timedelta(minutes=10))
    return s


def instalar_inicio() -> int:
    """Windows: abre o BRASIL+ sozinho quando você entra no Windows (tarefa agendada)."""
    if sys.platform != "win32":
        print("Isto só vale no Windows.")
        return 1
    exe = sys.executable if getattr(sys, "frozen", False) else str(Path(__file__).resolve())
    r = subprocess.run(["schtasks", "/Create", "/TN", "BRASILMAIS", "/TR", f'"{exe}" --sem-navegador', "/SC", "ONLOGON", "/F"])   # sem shell: o caminho não vira comando
    print("BRASIL+ vai abrir sozinho quando você entrar no Windows." if r.returncode == 0 else "Não consegui criar a tarefa (rode como administrador).")
    return r.returncode


def instancia_unica() -> bool:
    """Windows: só um BRASIL+ por vez (o instalador usa o mesmo nome para fechar o programa ao atualizar). False = já está aberto."""
    if sys.platform != "win32":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "BRASILMaisMutex")
    return ctypes.windll.kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS


def abrir_navegador(porta: int) -> None:
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{porta}/pronto", timeout=3).read()
            break
        except Exception:
            time.sleep(1)
    webbrowser.open(f"http://127.0.0.1:{porta}/painel")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.stdout is None or sys.stderr is None:   # programa sem janela preta: nada de print quebrando
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if "--versao" in argv:
        from app.versao import VERSAO
        print(VERSAO)
        return 0
    if "--iniciar-com-windows" in argv:
        return instalar_inicio()
    if "--rodar" not in argv and not instancia_unica():   # já aberto: só mostra o painel
        webbrowser.open(f"http://127.0.0.1:{int(os.environ.get('PORT') or PORTA_PADRAO)}/painel")
        return 0
    base = pasta_base(argv)
    porta = int(os.environ.get("PORT") or PORTA_PADRAO)
    preparar(base, porta)
    configurar_log(base / "logs")
    pedir_gemini(base)

    if not getattr(sys, "frozen", False):   # pelo código: o módulo do coletor fica em coletor/coletor.py
        sys.path.insert(0, str(recurso("coletor")))

    from app.db import criar_tabelas   # só agora: o ambiente já está pronto
    criar_tabelas()
    if "--rodar" in argv and argv.index("--rodar") + 1 < len(argv):   # roda um grupo agora (diario, semanal, mensal...) e sai
        from scripts.agendar import rodar_grupo
        rodar_grupo(argv[argv.index("--rodar") + 1])
        return 0
    log.info("BRASIL+ iniciando. Pasta: %s | painel: http://127.0.0.1:%s/painel", base, porta)

    agendador = montar_agendador()
    agendador.start()
    if "--sem-navegador" not in argv:
        threading.Thread(target=abrir_navegador, args=(porta,), daemon=True).start()

    import uvicorn

    from app import bandeja, atualizador
    from app.main import app
    from app.versao import VERSAO
    servidor = uvicorn.Server(uvicorn.Config(app, host=os.environ.get("API_BIND", "127.0.0.1"), port=porta, log_config=None))
    pedir_saida = lambda: setattr(servidor, "should_exit", True)   # noqa: E731
    agendador.add_job(lambda: log.info("atualizador: %s", atualizador.verificar(pedir_saida, bandeja.notificar)), "interval",
                      hours=6, id="atualizador", next_run_time=datetime.now(agendador.timezone) + timedelta(minutes=2))
    try:
        if "--sem-bandeja" in argv:
            servidor.run()
        else:   # servidor em segundo plano e o ícone perto do relógio na linha principal; sem ícone, espera o servidor
            fio = threading.Thread(target=servidor.run, name="servidor")
            fio.start()
            if not bandeja.rodar(porta, VERSAO, pedir_saida):
                fio.join()
            else:
                servidor.should_exit = True
                fio.join(timeout=30)
    finally:
        agendador.shutdown(wait=False)
    return 0
