"""Itens da auditoria: exportação segura, rotas administrativas, prontidão, status das fontes, coletas concorrentes, HTTP."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import base  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Coleta, Norma  # noqa: E402
from app.routers.v03 import _celula  # noqa: E402

cliente = TestClient(app)
TOKEN = "t" * 30


def test_csv_nao_executa_formula():
    assert _celula("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert _celula("@cmd") == "'@cmd" and _celula("+1") == "'+1" and _celula("-2+3") == "'-2+3"
    assert _celula(-5.0) == -5.0 and _celula(None) == "" and _celula("texto normal") == "texto normal"


def test_exportar_valida_parametros():
    assert cliente.get("/exportar/normas.csv", params={"limite": 0}).status_code == 422
    assert cliente.get("/exportar/normas.csv", params={"uf": "SPX"}).status_code == 422
    assert cliente.get("/exportar/normas.csv", params={"ano": 99999}).status_code == 422
    assert cliente.get("/exportar/inexistente.csv").status_code == 404


def test_exportar_limita_exportacoes_simultaneas():
    from app.routers import v03
    for _ in range(3):
        assert v03._EXPORTACOES.acquire(blocking=False)
    try:
        r = cliente.get("/exportar/normas.csv")
        assert r.status_code == 503 and "Retry-After" in r.headers
    finally:
        for _ in range(3):
            v03._EXPORTACOES.release()


def test_coleta_exige_token_e_barra_forca_bruta(monkeypatch):
    monkeypatch.setattr(settings, "somente_leitura", False)
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    h = {"x-admin-token": "errado" * 6}
    cods = [cliente.post("/coletas/camara-deputados", headers=h).status_code for _ in range(12)]
    assert cods[:10] == [401] * 10 and cods[10:] == [429, 429]


def test_coleta_so_aceita_arquivo_da_pasta_permitida(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "somente_leitura", False)
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    monkeypatch.setattr(settings, "pasta_arquivos_coleta", str(tmp_path))
    h = {"x-admin-token": TOKEN}
    r = cliente.post("/coletas/tse-resultados", headers=h, json={"ano": "2022", "arquivo_local": "/etc/passwd"})
    assert r.status_code == 422
    r = cliente.post("/coletas/tse-resultados", headers=h, json={"ano": "2022", "arquivo_local": str(tmp_path / ".." / "x")})
    assert r.status_code == 422


def test_coleta_em_modo_leitura_e_token_fraco(monkeypatch):
    monkeypatch.setattr(settings, "somente_leitura", True)
    assert cliente.post("/coletas/camara-deputados", headers={"x-admin-token": TOKEN}).status_code == 403
    monkeypatch.setattr(settings, "somente_leitura", False)
    monkeypatch.setattr(settings, "admin_token", "troque-este-token")
    assert cliente.post("/coletas/camara-deputados", headers={"x-admin-token": TOKEN}).status_code == 403


def test_pronto_e_saude_sem_detalhes():
    assert cliente.get("/saude").json() == {"status": "ok"}
    r = cliente.get("/pronto")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_pronto_indisponivel_nao_vaza_detalhe(monkeypatch):
    from sqlalchemy import text
    with engine.begin() as c:
        cabeca = c.execute(text("select version_num from alembic_version")).scalar()
        c.execute(text("update alembic_version set version_num='0001'"))
    try:
        r = cliente.get("/pronto")
        assert r.status_code == 503 and r.json() == {"status": "indisponivel"}
    finally:
        with engine.begin() as c:
            c.execute(text("update alembic_version set version_num=:v"), {"v": cabeca})


def test_status_das_fontes():
    with SessionLocal() as db:
        db.query(Coleta).filter(Coleta.tarefa.in_(["camara-deputados", "senado-senadores"])).delete()
        db.add(Coleta(fonte="camara", tarefa="camara-deputados", status="ok", itens=513))
        db.add(Coleta(fonte="senado", tarefa="senado-senadores", status="erro", erro="HTTPStatusError: HTTP 503 " + "x" * 400))
        db.commit()
    d = cliente.get("/fontes/status").json()
    por = {f["tarefa"]: f for f in d["fontes"]}
    assert por["camara-deputados"]["situacao"] == "ok" and por["camara-deputados"]["itens_ultima_ok"] == 513
    assert por["senado-senadores"]["situacao"] == "sem_coleta_boa" and len(por["senado-senadores"]["ultimo_erro"]) <= 160
    assert por["bcb-series"]["situacao"] in ("nunca_coletada", "ok", "falhando", "sem_coleta_boa")
    assert sum(d["resumo"].values()) == len(d["fontes"])


def test_coleta_abortada_e_marcada():
    from datetime import datetime, timedelta
    with SessionLocal() as db:
        db.add(Coleta(fonte="x", tarefa="teste-velha", status="rodando", inicio=datetime.now() - timedelta(hours=30)))
        db.commit()
        base._fechar_abortadas(db)
        db.expire_all()
        c = db.query(Coleta).filter_by(tarefa="teste-velha").one()
        assert c.status == "abortada" and c.fim is not None
        db.delete(c)
        db.commit()


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="trava de aviso só existe no Postgres")
def test_mesma_coleta_nao_roda_duas_vezes_ao_mesmo_tempo():
    with base.registrar_coleta("fonte", "tarefa-lock", ano=1):
        with pytest.raises(base.ColetaEmAndamento):
            with base.registrar_coleta("fonte", "tarefa-lock", ano=1):
                pass
        with base.registrar_coleta("fonte", "tarefa-lock", ano=2):  # parâmetros diferentes: pode
            pass
    with base.registrar_coleta("fonte", "tarefa-lock", ano=1):  # solta ao terminar
        pass


def test_http_get_respeita_retry_after_e_varia_espera(monkeypatch):
    esperas = []
    monkeypatch.setattr(http.time, "sleep", lambda s: esperas.append(s))
    monkeypatch.setattr(settings, "http_retries", 3)
    n = {"c": 0}

    def get(url, params=None, headers=None):
        n["c"] += 1
        req = httpx.Request("GET", url)
        if n["c"] < 3:
            return httpx.Response(429, headers={"Retry-After": "7"}, request=req)
        return httpx.Response(200, json={"ok": 1}, request=req)

    monkeypatch.setattr(http._cliente, "get", get)
    assert http.get_json("https://exemplo.gov.br/x?a=1") == {"ok": 1}
    assert len(esperas) == 2 and all(e >= 7 for e in esperas)  # espera pelo menos o que a fonte pediu


def test_http_nao_repete_erro_do_cliente(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("não devia esperar")))
    monkeypatch.setattr(http._cliente, "get", lambda *a, **k: httpx.Response(404, request=httpx.Request("GET", "https://x.gov.br")))
    with pytest.raises(httpx.HTTPStatusError):
        http.get("https://x.gov.br/a")


def test_ssrf_nao_segue_redirecionamento_para_rede_interna(monkeypatch):
    """O gancho de saída roda também em cada redirecionamento: um site público que redireciona para 169.254.169.254 é barrado."""
    def transporte(request):
        if request.url.host == "publico.gov.br":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})
        raise AssertionError("não devia chegar aqui")

    c = httpx.Client(transport=httpx.MockTransport(transporte), event_hooks={"request": [http._barrar_interno]}, follow_redirects=True)
    with pytest.raises(ValueError):
        c.get("http://publico.gov.br/x")
