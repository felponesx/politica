"""Limites compartilhados (requisições e IA), IP confiável, corpo HTTP e falha do contador."""
import os
import threading

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import ia_controle, ia_web, limites, seguranca  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402

cliente = TestClient(app)


@pytest.fixture(autouse=True)
def _baldes_vazios():
    for mw in _middlewares():
        mw.baldes.clear()
    yield


class _Req:
    def __init__(self, host, xff=None):
        self.client = type("C", (), {"host": host})()
        self.headers = {"x-forwarded-for": xff} if xff else {}


# ---------- contador atômico ----------
def test_consumir_respeita_o_limite_e_nao_gasta_alem():
    t = 1_000_000
    r = [limites.consumir("k", 3, 60, agora=t) for _ in range(5)]
    assert [x.ok for x in r] == [True, True, True, False, False]
    assert r[2].usado == 3 and r[3].restante == 0
    assert limites.consumir("k", 3, 60, agora=t + 61).ok  # janela nova
    assert not limites.consumir("c", 2, 60, custo=3, agora=t).ok  # custo maior que o limite: nunca passa


def test_consumir_simultaneo_nunca_passa_do_limite():
    """Vários threads (cada um com a sua conexão, como vários workers) disputando o mesmo contador."""
    oks = []

    def tenta():
        for _ in range(10):
            oks.append(limites.consumir("disputa", 25, 3600).ok)

    ts = [threading.Thread(target=tenta) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(oks) == 25 and len(oks) == 80
    with engine.connect() as c:
        assert c.execute(text("select n from uso_limites where chave='disputa'")).scalar() == 25


def test_contador_sobrevive_a_novo_processo():
    """O estado está no banco, não na memória: uma conexão nova (processo novo) enxerga o que já foi gasto."""
    for _ in range(3):
        limites.consumir("persiste", 3, 86400)
    engine.dispose()  # descarta as conexões como num reinício
    assert not limites.consumir("persiste", 3, 86400).ok


# ---------- IP real ----------
def test_ip_cliente_ignora_cabecalho_sem_proxy_confiavel(monkeypatch):
    monkeypatch.setattr(settings, "proxies_confiaveis", "")
    assert seguranca.ip_cliente(_Req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"
    monkeypatch.setattr(settings, "proxies_confiaveis", "172.16.0.0/12")
    assert seguranca.ip_cliente(_Req("203.0.113.9", "1.2.3.4")) == "203.0.113.9"  # conexão não vem do proxy


def test_ip_cliente_com_proxy_confiavel_nao_aceita_falsificacao(monkeypatch):
    monkeypatch.setattr(settings, "proxies_confiaveis", "172.16.0.0/12")
    # o cliente escreveu "9.9.9.9"; o proxy acrescentou o IP verdadeiro (198.51.100.7) à direita
    assert seguranca.ip_cliente(_Req("172.18.0.2", "9.9.9.9, 198.51.100.7")) == "198.51.100.7"
    assert seguranca.ip_cliente(_Req("172.18.0.2", "198.51.100.7, 172.20.0.5")) == "198.51.100.7"  # pula proxy intermediário
    assert seguranca.ip_cliente(_Req("172.18.0.2", "lixo")) == "172.18.0.2"
    assert seguranca.ip_cliente(_Req("172.18.0.2")) == "172.18.0.2"


# ---------- limite de requisições ----------
def test_limite_vale_entre_processos_de_verdade(tmp_path):
    """3 processos Python distintos (como 3 workers) disputam o mesmo contador num banco em arquivo: o total nunca passa do limite."""
    import subprocess
    import sys
    banco = tmp_path / "limites.db"
    codigo = (
        "import sys\nfrom app import limites\n"
        "n = sum(limites.consumir('multi', 30, 3600).ok for _ in range(20))\nprint(n)"
    )
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{banco}"}
    prep = ("from app.db import Base, engine\nimport app.models\n"
            "Base.metadata.create_all(engine)")
    subprocess.run([sys.executable, "-c", prep], check=True, env=env, cwd=os.getcwd())
    ps = [subprocess.Popen([sys.executable, "-c", codigo], env=env, cwd=os.getcwd(), stdout=subprocess.PIPE, text=True) for _ in range(3)]
    total = sum(int(p.communicate(timeout=60)[0].strip()) for p in ps)
    assert total == 30


def test_429_com_cabecalhos(monkeypatch):
    for mw in _middlewares():
        monkeypatch.setattr(mw, "por_minuto", 3)
    cod = [cliente.get("/estados") for _ in range(5)]
    assert [r.status_code == 429 for r in cod] == [False, False, False, True, True]
    assert int(cod[-1].headers["Retry-After"]) >= 1 and cod[-1].headers["X-RateLimit-Remaining"] == "0"
    assert cod[0].headers["X-RateLimit-Limit"] == "3"
    assert cliente.get("/saude").status_code == 200  # saúde fica fora do limite


def _middlewares():
    out, x = [], app.middleware_stack
    while x is not None:
        if isinstance(x, seguranca.Protecao):
            out.append(x)
        x = getattr(x, "app", None)
    return out


def test_rota_pesada_tem_limite_proprio(monkeypatch):
    monkeypatch.setattr(settings, "limite_pesado_por_minuto", 2)
    cod = [cliente.get("/busca", params={"q": "lula"}).status_code for _ in range(4)]
    assert cod[:2] == [200, 200] and cod[2:] == [429, 429]


def test_contador_fora_do_ar_nao_libera_tudo(monkeypatch):
    """Se o banco dos contadores cair, cada processo continua limitando com o balde local (nunca ilimitado)."""
    def quebra(*a, **k):
        raise limites.LimiteIndisponivel("x")

    monkeypatch.setattr(limites, "consumir", quebra)
    for mw in _middlewares():
        monkeypatch.setattr(mw, "por_minuto", 3)
        mw.baldes.clear()
    cod = [cliente.get("/estados").status_code for _ in range(6)]
    assert 429 in cod and cod.count(429) >= 2


# ---------- corpo HTTP ----------
def test_corpo_limitado_sem_content_length():
    def gera():
        for _ in range(40):
            yield b"x" * 10_000  # 400 KB em pedaços (chunked, sem Content-Length)

    r = cliente.post("/ia/web", content=gera())
    assert r.status_code == 413


def test_corpo_com_content_length_mentiroso():
    # promete 10 bytes e manda 300 KB: vale o que chegou
    r = cliente.post("/ia/web", content=b"x" * 300_000, headers={"content-length": "10"})
    assert r.status_code in (400, 413)
    assert cliente.post("/ia/web", content=b"x", headers={"content-length": "abc"}).status_code in (400, 413, 422)


# ---------- IA ----------
class _Resp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"output_text": "Resposta.", "output": [], "model": "m"}


@pytest.fixture
def ia(monkeypatch):
    monkeypatch.setattr(settings, "perplexity_api_key", "chave-de-teste")
    chamadas = []

    def falso(url, **k):
        chamadas.append((url, k))
        return _Resp()

    monkeypatch.setattr(ia_web.httpx, "post", falso)
    return chamadas


def test_ia_limite_por_ip_por_minuto(ia, monkeypatch):
    monkeypatch.setattr(settings, "limite_ia_ip_minuto", 2)
    cod = [cliente.post("/ia/web", json={"pergunta": f"pergunta número {i}"}).status_code for i in range(4)]
    assert cod == [200, 200, 429, 429] and len(ia) == 2


def test_ia_orcamento_diario_global(ia, monkeypatch):
    monkeypatch.setattr(settings, "ia_orcamento_dia_usd", 0.05)  # cabe 2 perguntas de 0,02
    monkeypatch.setattr(settings, "limite_ia_ip_minuto", 100)
    cod = [cliente.post("/ia/web", json={"pergunta": f"outra pergunta {i}"}).status_code for i in range(4)]
    assert cod == [200, 200, 429, 429] and len(ia) == 2


def test_ia_limite_diario_nao_zera_com_reinicio(ia, monkeypatch):
    monkeypatch.setattr(settings, "perplexity_limite_dia", 1)
    monkeypatch.setattr(settings, "limite_ia_ip_minuto", 100)
    assert cliente.post("/ia/web", json={"pergunta": "primeira"}).status_code == 200
    engine.dispose()  # "reinício": nenhuma memória do processo anterior
    assert cliente.post("/ia/web", json={"pergunta": "segunda"}).status_code == 429


def test_ia_cache_compartilhado_nao_cobra_duas_vezes(ia):
    assert cliente.post("/ia/web", json={"pergunta": "Mesma Pergunta"}).status_code == 200
    assert cliente.post("/ia/web", json={"pergunta": "mesma   pergunta"}).status_code == 200
    assert len(ia) == 1
    assert limites.lido("ia:orcamento:dia", 86400) == 20_000  # só uma cobrança


def test_ia_simultanea_respeita_limite_global(ia, monkeypatch):
    monkeypatch.setattr(settings, "limite_ia_ip_minuto", 100)
    monkeypatch.setattr(settings, "limite_ia_ip_dia", 100)
    monkeypatch.setattr(settings, "limite_ia_global_minuto", 6)
    resultados = []

    def vai(i):
        for j in range(5):
            resultados.append(cliente.post("/ia/web", json={"pergunta": f"concorrente {i} {j}"}).status_code)

    ts = [threading.Thread(target=vai, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(ia) <= 6 and resultados.count(200) == len(ia)


def test_ia_falha_do_contador_bloqueia(ia, monkeypatch):
    def quebra(*a, **k):
        raise limites.LimiteIndisponivel("x")

    monkeypatch.setattr(limites, "consumir", quebra)
    r = cliente.post("/ia/web", json={"pergunta": "sem contador"})
    assert r.status_code == 503 and not ia and "Retry-After" in r.headers


def test_ia_manda_teto_de_tokens_e_nao_segue_redirecionamento(ia, monkeypatch):
    monkeypatch.setattr(settings, "ia_max_saida_tokens", 777)
    cliente.post("/ia/web", json={"pergunta": "teto de tokens"})
    url, k = ia[0]
    assert k["json"]["max_output_tokens"] == 777 and k["follow_redirects"] is False


def test_ia_registra_uso_sem_conteudo(ia):
    cliente.post("/ia/web", json={"pergunta": "segredo que não pode ser gravado"})
    with engine.connect() as c:
        linhas = c.execute(text("select * from uso_ia")).all()
        assert len(linhas) == 1 and linhas[0].resultado == "ok" and linhas[0].custo_micro_usd == 20_000
        assert "segredo" not in " ".join(str(v) for v in linhas[0])
    d = cliente.get("/ia/uso").json()
    assert d["disponivel"] and d["dias"][0]["chamadas"] == 1 and "IP" not in str(d) and d["gasto_hoje_usd"] == 0.02


def test_ia_erro_do_provedor_conta_e_vira_502(monkeypatch):
    import httpx
    monkeypatch.setattr(settings, "perplexity_api_key", "k")

    def cai(*a, **k):
        raise httpx.ConnectTimeout("t")

    monkeypatch.setattr(ia_web.httpx, "post", cai)
    assert cliente.post("/ia/web", json={"pergunta": "timeout"}).status_code == 502
    assert ia_controle.limites.lido("ia:orcamento:dia", 86400) == 20_000  # custo contado (evita laço de repetição)
