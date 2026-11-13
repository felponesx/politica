"""Programa único do BRASIL+ (app/executavel.py): primeira execução, configuração, agendador e SQLite em modo WAL."""
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from app import executavel as ex

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def ambiente(monkeypatch):
    """preparar() põe variáveis no ambiente: usa uma cópia, para não vazar para os outros testes."""
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for k in ("DATABASE_URL", "ADMIN_TOKEN", "COLETOR_RAIZ", "COLETOR_DADOS", "BRASILPLUS_SITE"):
        os.environ.pop(k, None)
    return os.environ


def test_primeira_execucao_cria_pastas_config_e_destino(tmp_path, ambiente):
    cfg = ex.preparar(tmp_path / "BRASILMais", 8123)
    base = tmp_path / "BRASILMais"
    for sub in ("dados-brasilplus", "coletor", "coletor-dados", "logs", "coletor/vinculos"):
        assert (base / sub).is_dir(), sub
    assert len(cfg["ADMIN_TOKEN"]) >= 24 and f"ADMIN_TOKEN={cfg['ADMIN_TOKEN']}" in (base / "config.env").read_text(encoding="utf-8")
    destino = tomllib.loads((base / "coletor" / "destinos.toml").read_text(encoding="utf-8"))["destino"][0]
    assert destino["tipo"] == "pasta" and Path(destino["pasta"]) == base / "coletor-dados"
    assert ambiente["DATABASE_URL"].startswith("sqlite:///") and ambiente["DATABASE_URL"].endswith("dados-brasilplus/brasilplus.db")
    assert ambiente["SQLITE_WAL"] == "true" and ambiente["BRASIL_FONTES_URL"].startswith("http://127.0.0.1:8123/")
    assert Path(ambiente["COLETOR_RAIZ"]) == base / "coletor" and Path(ambiente["COLETOR_DADOS"]) == base / "coletor-dados"


def test_segunda_execucao_nao_troca_nada(tmp_path, ambiente):
    base = tmp_path / "BRASILMais"
    primeira = ex.preparar(base)
    (base / "coletor" / "destinos.toml").write_text('# meu\n[[destino]]\nnome = "X"\ntipo = "pasta"\npasta = "/tmp/x"\n', encoding="utf-8")
    ambiente.pop("DATABASE_URL"), ambiente.pop("ADMIN_TOKEN", None)
    segunda = ex.preparar(base)
    assert segunda["ADMIN_TOKEN"] == primeira["ADMIN_TOKEN"]
    assert "# meu" in (base / "coletor" / "destinos.toml").read_text(encoding="utf-8")


def test_config_do_usuario_vence_o_padrao_e_o_ambiente_real_vence_o_config(tmp_path, ambiente):
    base = tmp_path / "BRASILMais"
    base.mkdir()
    (base / "config.env").write_text("# comentário\nADMIN_TOKEN=" + "t" * 30 + "\nDATABASE_URL=sqlite:///meu.db\nCOLETOR_PULL=1\n", encoding="utf-8-sig")
    ambiente["COLETOR_PULL"] = "0"
    ex.preparar(base)
    assert ambiente["DATABASE_URL"] == "sqlite:///meu.db"   # config.env vence o padrão
    assert ambiente["COLETOR_PULL"] == "0"                  # variável do sistema vence o config.env
    assert ex.ler_config(base / "config.env")["ADMIN_TOKEN"] == "t" * 30


def test_pasta_base_pode_ser_escolhida_na_linha_de_comando(tmp_path):
    assert ex.pasta_base(["--base", str(tmp_path / "meus-dados")]) == tmp_path / "meus-dados"


def test_agendador_tem_as_tarefas_e_o_ciclo_do_coletor(monkeypatch):
    monkeypatch.setenv("COLETOR_DADOS", "/tmp/x")
    from apscheduler.schedulers.background import BackgroundScheduler

    from scripts.agendar import agendar_tarefas
    s = agendar_tarefas(BackgroundScheduler(timezone="America/Sao_Paulo"))
    ids = {j.id for j in s.get_jobs()}
    assert {"diario", "semanal", "mensal", "trimestral", "agenda", "ingestao"} <= ids
    montado = ex.montar_agendador()
    assert "ciclo-coletor" in {j.id for j in montado.get_jobs()}


def test_sqlite_em_modo_wal_quando_pedido(tmp_path):
    """O programa roda API e coletas no mesmo processo: leitura e escrita juntas exigem o modo WAL."""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'a.db'}", "SQLITE_WAL": "true"}
    r = subprocess.run([sys.executable, "-c", "from app.db import engine\n"
                        "with engine.connect() as c: print(c.exec_driver_sql('PRAGMA journal_mode').scalar())"],
                       cwd=RAIZ, env=env, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "wal", r.stderr


def test_alembic_ini_so_tem_ascii():
    """O Alembic lê o alembic.ini com a codificação do sistema (cp1252 no Windows, ASCII em alguns Linux): acento ali quebra a partida."""
    (RAIZ / "alembic.ini").read_bytes().decode("ascii")


@pytest.mark.parametrize("fuso", ["UTC", "America/Sao_Paulo", "Asia/Tokyo"])
def test_primeiro_ciclo_e_daqui_a_poucos_segundos_em_qualquer_fuso(fuso):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    quando = ex.proximo_ciclo(ZoneInfo(fuso), 30)
    assert quando.tzinfo is not None
    assert 20 <= (quando - datetime.now(timezone.utc)).total_seconds() <= 40


def _base_com_dados(tmp_path, monkeypatch):
    import sqlite3
    base = tmp_path / "BRASILMais"
    (base / "coletor" / "dados" / "raw" / "bcb" / "ab").mkdir(parents=True)
    banco = base / "dados-brasilplus" / "brasilplus.db"
    banco.parent.mkdir(parents=True)
    c = sqlite3.connect(banco)
    c.execute("create table t (x text)")
    c.execute("insert into t values ('importante')")
    c.commit()
    c.close()
    m = sqlite3.connect(base / "coletor" / "dados" / "manifesto.db")
    m.execute("create table coleta (id integer)")
    m.commit()
    m.close()
    (base / "coletor" / "dados" / "raw" / "bcb" / "ab" / "abc123").write_bytes(b"original captado")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{banco.as_posix()}")
    monkeypatch.delenv("BACKUP_EXTRA", raising=False)
    return base


def test_backup_copia_banco_manifesto_e_originais(tmp_path, monkeypatch):
    import sqlite3
    base = _base_com_dados(tmp_path, monkeypatch)
    feitos = ex.fazer_backup(base)
    assert len(feitos) == 2
    copia = next(f for f in feitos if f.name.startswith("brasilplus-"))
    assert sqlite3.connect(copia).execute("select x from t").fetchone() == ("importante",)
    assert (base / "backups" / "coletor-dados" / "raw" / "bcb" / "ab" / "abc123").read_bytes() == b"original captado"


def test_backup_nunca_apaga_original_que_sumiu_da_origem(tmp_path, monkeypatch):
    base = _base_com_dados(tmp_path, monkeypatch)
    ex.fazer_backup(base)
    (base / "coletor" / "dados" / "raw" / "bcb" / "ab" / "abc123").unlink()
    ex.fazer_backup(base)
    assert (base / "backups" / "coletor-dados" / "raw" / "bcb" / "ab" / "abc123").exists()


def test_backup_guarda_so_os_ultimos_7_dias_do_banco(tmp_path, monkeypatch):
    base = _base_com_dados(tmp_path, monkeypatch)
    (base / "backups").mkdir()
    for d in range(1, 10):
        (base / "backups" / f"brasilplus-202001{d:02d}.db").write_bytes(b"antigo")
    ex.fazer_backup(base)
    sobraram = sorted((base / "backups").glob("brasilplus-*.db"))
    assert len(sobraram) == 7 and any(not a.read_bytes() == b"antigo" for a in sobraram)   # o de hoje está entre eles


def test_backup_extra_copia_em_outra_pasta(tmp_path, monkeypatch):
    base = _base_com_dados(tmp_path, monkeypatch)
    monkeypatch.setenv("BACKUP_EXTRA", str(tmp_path / "disco-externo"))
    ex.fazer_backup(base)
    assert list((tmp_path / "disco-externo").glob("brasilplus-*.db"))


def test_agendador_tem_o_backup_diario():
    assert "backup" in {j.id for j in ex.montar_agendador().get_jobs()}
