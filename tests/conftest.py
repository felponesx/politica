"""Configuração comum dos testes."""
import os

# todos os testes usam o mesmo cliente ("testclient"): sem isso o limite por IP (120/min) derruba os últimos testes
os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")
os.environ.setdefault("CACHE_SEGUNDOS", "0")  # os testes mexem nos dados entre uma chamada e outra

# os testes de /contadores não podem depender do arquivo que o robô grava em site/dados (a leitura muda a cada 15 minutos)
os.environ.setdefault("CONTADORES_EXTERNOS", os.devnull + ".nao-existe")


import pytest  # noqa: E402

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

# os testes apagam e gravam dados: nunca rodar contra um banco de coleta ou de produção (isso já apagou um banco local em 12/11/2026).
# Banco de teste = nome com "test" (teste.db, teste_123 do testar_postgres.sh). Para forçar: BANCO_DE_TESTE_OK=1.
_nome_banco = os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].lower()
if "test" not in _nome_banco and os.environ.get("BANCO_DE_TESTE_OK") != "1":
    pytest.exit(f"Recusado: DATABASE_URL aponta para '{_nome_banco}', que não parece banco de teste. "
                "Use um banco com 'test' no nome (ou BANCO_DE_TESTE_OK=1).", returncode=4)


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
