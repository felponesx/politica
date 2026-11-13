"""Quadro genérico das fontes que entram sem código novo (cadastro pela tela e adaptador `linhas` do coletor do celular)."""
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import FonteCadastrada, Registro
from app import fontes_cadastro


def _entrada(**kw):
    base = {"nome": "zzt-fonte-nova", "url": "https://exemplo.gov.br/x.json", "formato": "json",
            "campos": {"chave": "id", "titulo": "unidade", "valor": "total", "categoria": "saude"}}
    base.update(kw)
    return base


def test_categoria_do_cadastro_e_validada():
    ok = fontes_cadastro.validar(_entrada())
    assert ok["campos"]["categoria"] == "saude"
    try:
        fontes_cadastro.validar(_entrada(campos={"chave": "id", "categoria": "nao-existe"}))
        assert False, "categoria inventada passou"
    except ValueError as e:
        assert "categoria" in str(e)
    assert "categoria" not in fontes_cadastro.para_coletor(FonteCadastrada(nome="zzt-a", url="https://a.gov.br/x", intervalo_min=60,
                                                                           formato="json", campos=ok["campos"]))["mapa"]


def test_fonte_cadastrada_aparece_no_quadro_e_no_painel():
    criar_tabelas()
    with SessionLocal() as db:
        db.query(FonteCadastrada).filter(FonteCadastrada.nome.like("zzt-%")).delete()
        db.query(Registro).filter(Registro.fonte == "zzt-fonte-nova").delete()
        agora = datetime.now(timezone.utc)
        db.add(FonteCadastrada(**fontes_cadastro.validar(_entrada()), ativa=True, criada_em=agora, atualizada_em=agora))
        db.add(FonteCadastrada(**fontes_cadastro.validar(_entrada(nome="zzt-sem-secao", campos={"chave": "id"})), ativa=True, criada_em=agora, atualizada_em=agora))
        db.add(Registro(fonte="zzt-fonte-nova", tipo="zzt_fonte_nova", chave="1", titulo="Hospital A", valor=10.0, uf="SP", dados={}))
        db.commit()
    c = TestClient(app)
    q = c.get("/fontes-novas").json()
    f = next(x for x in q["fontes"] if x["nome"] == "zzt-fonte-nova")
    assert f["categoria"] == "saude" and f["categoria_nome"] == "Saúde" and f["registros"] == 1 and f["amostra"][0]["titulo"] == "Hospital A"
    assert "zzt-sem-secao" in q["sem_secao"] and "zzt-fonte-nova" not in q["sem_secao"]
    st = c.get("/fontes/status").json()
    p = next(x for x in st["fontes"] if x["tarefa"] == "zzt-fonte-nova")
    assert p["categoria"] == "saude" and p["estado"] == "ok" and p["origem"] == "cadastro"
    assert "zzt-sem-secao" in st["sem_secao"]
    with SessionLocal() as db:
        db.query(FonteCadastrada).filter(FonteCadastrada.nome.like("zzt-%")).delete()
        db.query(Registro).filter(Registro.fonte == "zzt-fonte-nova").delete()
        db.commit()


def test_fonte_do_celular_com_adaptador_linhas_aparece(tmp_path, monkeypatch):
    criar_tabelas()
    pasta = tmp_path / "dados" / "zzt-celular"
    pasta.mkdir(parents=True)
    (pasta / "meta.json").write_text(json.dumps({"fonte": "zzt-celular", "adaptador": "linhas", "categoria": "gastos", "url": "https://x.gov.br/a"}), encoding="utf-8")
    outra = tmp_path / "dados" / "bcb"
    outra.mkdir()
    (outra / "meta.json").write_text(json.dumps({"fonte": "bcb"}), encoding="utf-8")   # sem adaptador `linhas`: não entra no quadro
    monkeypatch.setenv("COLETOR_DADOS", str(tmp_path))
    nomes = {f["nome"]: f for f in TestClient(app).get("/fontes-novas").json()["fontes"]}
    assert nomes["zzt-celular"]["origem"] == "celular" and nomes["zzt-celular"]["categoria"] == "gastos" and "bcb" not in nomes
