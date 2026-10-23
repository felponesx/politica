"""Configuração comum dos testes."""
import os

# todos os testes usam o mesmo cliente ("testclient"): sem isso o limite por IP (120/min) derruba os últimos testes
os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")
os.environ.setdefault("CACHE_SEGUNDOS", "0")  # os testes mexem nos dados entre uma chamada e outra

# os testes de /contadores não podem depender do arquivo que o robô grava em site/dados (a leitura muda a cada 15 minutos)
os.environ.setdefault("CONTADORES_EXTERNOS", os.devnull + ".nao-existe")


import pytest  # noqa: E402

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")


@pytest.fixture(autouse=True)
def _contadores_limpos():
    """Cada teste começa com os contadores de limite, o cache e o registro de uso da IA vazios."""
    from sqlalchemy import text

    from app.db import criar_tabelas, engine
    criar_tabelas()
    with engine.begin() as c:
        for t in ("uso_limites", "uso_ia", "cache_ia"):
            c.execute(text(f"DELETE FROM {t}"))
    yield
