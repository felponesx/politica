"""Publicações próprias, fotos, links de vídeo, banco (só leitura) e área do administrador."""
import base64

import pytest
from fastapi.testclient import TestClient

from app import publicacoes as pub
from app.config import settings
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Conta, Midia, Publicacao, Sessao, VotoLei

JSON = {"content-type": "application/json"}
CPF_OK = "529.982.247-25"
CPF_OK2 = "111.444.777-35"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff" + b"\x00" * 64


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(settings, "cpf_pepper", "x" * 40)
    monkeypatch.setattr(settings, "admin_emails", "adm@exemplo.com")
    criar_tabelas()
    c = TestClient(app)
    yield c
    c.cookies.clear()


@pytest.fixture(autouse=True)
def _limpa():
    def limpar():
        db = SessionLocal()
        try:
            db.query(VotoLei).delete()
            db.query(Sessao).delete()
            db.query(Publicacao).delete()
            db.query(Midia).delete()
            db.query(Conta).delete()
            db.commit()
        finally:
            db.close()
    limpar()
    yield
    limpar()


def _conta(cli, email, nome, cpf):
    r = cli.post("/contas", json={"email": email, "senha": "senha-forte-1", "nome": nome, "cpf": cpf, "aceito_termos": True}, headers=JSON)
    if r.status_code == 409:  # já existe: entra
        cli.post("/contas/entrar", json={"email": email, "senha": "senha-forte-1"}, headers=JSON)


def _login_admin(cli):
    _conta(cli, "adm@exemplo.com", "Felipe Admin", CPF_OK)


def _login_comum(cli):
    _conta(cli, "pessoa@exemplo.com", "Pessoa Comum", CPF_OK2)


def _publicacao(**k):
    base = {"titulo": "Dados próprios de teste", "corpo": "Primeiro parágrafo.\n\nSegundo parágrafo.", "categoria": "dados", "publicada": False}
    base.update(k)
    return base


def test_video_so_do_youtube_ou_vimeo():
    assert pub.link_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    assert pub.link_video("https://youtu.be/dQw4w9WgXcQ") == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
    assert pub.link_video("https://vimeo.com/123456789") == "https://player.vimeo.com/video/123456789"
    for ruim in ("http://youtu.be/dQw4w9WgXcQ", "https://evil.com/x", "https://youtube.com/watch?v=<script>", "javascript:alert(1)"):
        with pytest.raises(pub.ErroPublicacao):
            pub.link_video(ruim)


def test_foto_confere_o_arquivo_pelos_bytes():
    assert pub.decodifica_foto(base64.b64encode(PNG).decode())[1] == "image/png"
    assert pub.decodifica_foto("data:image/jpeg;base64," + base64.b64encode(JPG).decode())[1] == "image/jpeg"
    with pytest.raises(pub.ErroPublicacao):
        pub.decodifica_foto(base64.b64encode(b"<html>nao sou foto</html>").decode())
    with pytest.raises(pub.ErroPublicacao):
        pub.decodifica_foto(base64.b64encode(PNG + b"0" * (3 * 1024 * 1024)).decode())


def test_so_admin_escreve_e_visitante_nao_ve_rascunho(cli):
    _login_comum(cli)
    assert cli.post("/admin/publicacoes", json=_publicacao(), headers=JSON).status_code == 403
    cli.cookies.clear()
    _login_admin(cli)
    r = cli.post("/admin/publicacoes", json=_publicacao(), headers=JSON)
    assert r.status_code == 200 and r.json()["publicada"] is False
    slug = r.json()["slug"]
    cli.cookies.clear()
    assert cli.get(f"/publicacoes/{slug}").status_code == 404  # rascunho não aparece no site


def test_publicar_aparece_no_site_e_slug_fica_fixo(cli):
    _login_admin(cli)
    slug = cli.post("/admin/publicacoes", json=_publicacao(publicada=True), headers=JSON).json()["slug"]
    cli.cookies.clear()
    lista = cli.get("/publicacoes").json()
    assert lista["total"] == 1 and lista["itens"][0]["slug"] == slug
    d = cli.get(f"/publicacoes/{slug}").json()
    assert d["corpo"].startswith("Primeiro") and d["video"] is None
    _login_admin(cli)
    pid = cli.get("/admin/publicacoes").json()["itens"][0]["id"]
    cli.post(f"/admin/publicacoes/{pid}", json=_publicacao(titulo="Outro título bem diferente", publicada=True), headers=JSON)
    assert cli.get("/publicacoes").json()["itens"][0]["slug"] == slug  # o link não muda ao editar o título


def test_foto_da_capa_so_aparece_publicada(cli):
    _login_admin(cli)
    foto = cli.post("/admin/midia", json={"nome": "capa", "dados_base64": base64.b64encode(PNG).decode()}, headers=JSON).json()
    pid = cli.post("/admin/publicacoes", json=_publicacao(capa_midia_id=foto["id"]), headers=JSON).json()["id"]
    cli.cookies.clear()
    assert cli.get(f"/midia/{foto['id']}").status_code == 404  # ainda é rascunho
    _login_admin(cli)
    cli.post(f"/admin/publicacoes/{pid}", json=_publicacao(capa_midia_id=foto["id"], publicada=True), headers=JSON)
    cli.cookies.clear()
    r = cli.get(f"/midia/{foto['id']}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_video_salvo_como_incorporacao(cli):
    _login_admin(cli)
    slug = cli.post("/admin/publicacoes", json=_publicacao(video="https://youtu.be/dQw4w9WgXcQ", publicada=True), headers=JSON).json()["slug"]
    cli.cookies.clear()
    assert cli.get(f"/publicacoes/{slug}").json()["video"] == "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"


def test_banco_so_para_admin_e_esconde_segredos(cli):
    _login_comum(cli)
    assert cli.get("/admin/banco").status_code == 403
    cli.cookies.clear()
    _login_admin(cli)
    r = cli.get("/admin/banco/contas")
    assert r.status_code == 200
    assert "senha_hash" not in r.json()["colunas"] and "cpf_codigo" not in r.json()["colunas"] and "google_sub" not in r.json()["colunas"]
    assert cli.get("/admin/banco/sessoes").status_code == 404  # tabela fora da lista
    assert cli.get("/admin/banco/publicacoes").status_code == 200
