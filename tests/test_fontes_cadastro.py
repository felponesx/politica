"""Cadastro de fontes pela tela: regras de entrada (sem banco) e as rotas com token (com banco de teste)."""
import pytest
from fastapi.testclient import TestClient

from app import fontes_cadastro as fc
from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import FonteCadastrada

TOKEN = "tok-de-teste-com-mais-de-24-caracteres-xyz"
BASE = {"nome": "exemplo-lista", "url": "https://dados.exemplo.gov.br/lista.json", "formato": "json",
        "intervalo_min": 360, "campos": {"chave": "id", "valor": "valor", "titulo": "descricao", "data": "data"}}


# ---------- regras (sem banco) ----------

def test_entrada_valida_passa_e_recebe_tipo_padrao():
    limpa = fc.validar(BASE)
    assert limpa["campos"]["tipo"] == "exemplo_lista"
    assert limpa["url"].startswith("https://") and limpa["intervalo_min"] == 360


@pytest.mark.parametrize("url", ["http://dados.gov.br/x.json", "https://localhost/x.json", "https://192.168.0.10/x.json",
                                 "https://10.1.2.3/x.json", "https://169.254.169.254/latest/meta-data", "https://servidor.local/x.json"])
def test_endereco_interno_ou_sem_https_e_recusado(url):
    with pytest.raises(ValueError):
        fc.validar({**BASE, "url": url})


def test_nome_e_formato_e_intervalo_com_regra():
    with pytest.raises(ValueError, match="nome"):
        fc.validar({**BASE, "nome": "Com Espaço"})
    with pytest.raises(ValueError, match="formato"):
        fc.validar({**BASE, "formato": "exe"})
    with pytest.raises(ValueError, match="intervalo"):
        fc.validar({**BASE, "intervalo_min": 1})


def test_mapa_sem_chave_ou_com_campo_desconhecido_e_recusado():
    with pytest.raises(ValueError, match="chave"):
        fc.validar({**BASE, "campos": {"valor": "v"}})
    with pytest.raises(ValueError, match="desconhecidos"):
        fc.validar({**BASE, "campos": {"chave": "id", "senha": "x"}})


def test_campo_de_pessoa_so_com_permissao_explicita():
    pessoa = {**BASE, "campos": {"chave": "id", "titulo": "nome_completo"}}
    with pytest.raises(ValueError, match="pessoa"):
        fc.validar(pessoa)
    assert fc.validar({**pessoa, "permitir_pessoas": True})["permitir_pessoas"] is True


# ---------- rotas (com token) ----------

@pytest.fixture
def cliente(monkeypatch):
    criar_tabelas()
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    monkeypatch.setattr(settings, "somente_leitura", False)
    with SessionLocal() as db:
        db.query(FonteCadastrada).filter(FonteCadastrada.nome.like("exemplo-%")).delete(synchronize_session=False)
        db.commit()
    yield TestClient(app)
    with SessionLocal() as db:
        db.query(FonteCadastrada).filter(FonteCadastrada.nome.like("exemplo-%")).delete(synchronize_session=False)
        db.commit()


def test_cadastrar_exige_token(cliente):
    assert cliente.post("/fontes-cadastradas", json=BASE).status_code == 422   # sem o cabeçalho
    r = cliente.post("/fontes-cadastradas", json=BASE, headers={"X-Admin-Token": "errado-errado-errado-errado-1"})
    assert r.status_code == 401


def test_cadastrar_listar_repetido_e_pausar(cliente):
    h = {"X-Admin-Token": TOKEN}
    r = cliente.post("/fontes-cadastradas", json=BASE, headers=h)
    assert r.status_code == 201, r.text
    fonte_id = r.json()["id"]
    assert cliente.post("/fontes-cadastradas", json=BASE, headers=h).status_code == 409
    lista = cliente.get("/fontes-cadastradas").json()
    assert any(f["nome"] == "exemplo-lista" and f["ativa"] for f in lista)
    r = cliente.post(f"/fontes-cadastradas/{fonte_id}", json={"ativa": False, "intervalo_min": 60}, headers=h)
    assert r.status_code == 200 and r.json()["ativa"] is False and r.json()["intervalo_min"] == 60
    assert all(f["nome"] != "exemplo-lista" for f in cliente.get("/fontes-cadastradas?ativa=true").json())


def test_cadastro_recusa_endereco_interno_pela_api(cliente):
    r = cliente.post("/fontes-cadastradas", json={**BASE, "url": "https://127.0.0.1/x.json"}, headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 422 and "interno" in r.json()["detail"]
