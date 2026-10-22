"""Fotos: prefeitos eleitos pelo zip remoto do TSE (Range) e retratos oficiais da Câmara para os envolvidos nos escândalos."""
import io
import struct
import zipfile
from types import SimpleNamespace

import pytest

from app.db import SessionLocal, criar_tabelas
from app.models import Candidato, Registro
from scripts import fotos_escandalos as fe
from scripts import midia_site as ms


def _zip_com(nome: str, conteudo: bytes, deflate: bool):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED) as z:
        z.writestr("leiame.pdf", b"x" * 50)
        z.writestr(nome, conteudo)
    bruto = buf.getvalue()
    info = zipfile.ZipFile(io.BytesIO(bruto)).getinfo(nome)
    return bruto, info


def _jpeg(cor=(200, 30, 30)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (300, 400), cor).save(out, "JPEG")
    return out.getvalue()


@pytest.mark.parametrize("deflate", [False, True])
def test_foto_do_zip_le_so_os_bytes_da_entrada(monkeypatch, deflate):
    foto = _jpeg()
    bruto, info = _zip_com("FAC10001954238_div.jpeg", foto, deflate)
    pedidos = []

    def get(url, headers=None, timeout=None):
        ini, fim = map(int, headers["Range"].split("=")[1].split("-"))
        pedidos.append((ini, fim))
        return SimpleNamespace(status_code=206, content=bruto[ini:fim + 1])
    monkeypatch.setattr(ms.cli, "get", get)
    got = ms._foto_do_zip("http://x/zip", len(info.filename), info.compress_size, info.compress_type, info.header_offset)
    assert got == foto
    assert len(pedidos) == 1 and pedidos[0][0] == info.header_offset  # um pedido só, a partir do cabeçalho da entrada


def test_foto_do_zip_recusa_servidor_que_ignora_o_range(monkeypatch):
    monkeypatch.setattr(ms.cli, "get", lambda *a, **k: SimpleNamespace(status_code=200, content=b"PK\x03\x04" + b"0" * 100))
    assert ms._foto_do_zip("http://x/zip", 10, 5, 0, 0) is None


def test_fotos_prefeitos_so_dos_eleitos(monkeypatch):
    criar_tabelas()
    foto = _jpeg()
    bruto, info = _zip_com("FAC10001954238_div.jpeg", foto, False)
    with SessionLocal() as db:
        db.query(Candidato).filter(Candidato.ano == 2099).delete()
        db.query(Registro).filter(Registro.tipo == "candidato_foto_teste").delete()
        for sq, res in (("10001954238", "ELEITO"), ("10001954239", "NÃO ELEITO")):
            reg = Registro(fonte="tse", tipo="candidato_foto_teste", chave=sq, dados={})
            db.add(reg)
            db.flush()
            db.add(Candidato(registro_id=reg.id, ano=2099, sq_candidato=sq, nome="X", nome_urna="X", uf="AC", cargo="PREFEITO", resultado=res))
        db.commit()
        entradas = [("leiame.pdf", 50, 0, 0), (info.filename, info.compress_size, info.compress_type, info.header_offset),
                    ("FAC10001954239_div.jpeg", 10, 0, 999)]
        monkeypatch.setattr("app.collectors.bcb_scr.entradas_zip", lambda url: (len(bruto), entradas))
        monkeypatch.setattr(ms, "_foto_do_zip", lambda url, nl, comp, metodo, off: foto if off == info.header_offset else b"lixo")
        out = ms.fotos_prefeitos(db, ano=2099)
        db.query(Candidato).filter(Candidato.ano == 2099).delete()
        db.query(Registro).filter(Registro.tipo == "candidato_foto_teste").delete()
        db.commit()
    assert list(out) == ["tse:10001954238"] and out["tse:10001954238"].startswith("data:image/jpeg;base64,")


# respostas reais da API da Câmara (22/10/2026, resumidas): uma linha por legislatura
def _linha(i, nome, partido, uf, leg):
    return {"id": i, "nome": nome, "siglaPartido": partido, "siglaUf": uf, "idLegislatura": leg, "urlFoto": f"https://www.camara.leg.br/internet/deputado/bandep/{i}.jpg"}


JANENE = [_linha(73776, "JOSÉ JANENE", "PP***", "PR", 50), _linha(73776, "JOSÉ JANENE", "PPB", "PR", 51), _linha(73776, "JOSÉ JANENE", "PP**", "PR", 52)]


def test_escolher_deputado_nome_partido_e_uf():
    pessoa = {"nome": "José Janene", "cargo_na_epoca": "Deputado federal e líder do PP", "partido_na_epoca": "PP"}
    assert fe.escolher_deputado(pessoa, JANENE)["id"] == 73776
    # partido de outra linhagem: não é a mesma pessoa
    assert fe.escolher_deputado({**pessoa, "partido_na_epoca": "PT"}, JANENE) is None
    # estado do cargo precisa bater com o de algum mandato
    assert fe.escolher_deputado({**pessoa, "cargo_na_epoca": "Deputado federal (SP)"}, JANENE) is None
    assert fe.escolher_deputado({**pessoa, "cargo_na_epoca": "Deputado federal (PR)"}, JANENE)["id"] == 73776


def test_escolher_deputado_homonimo_e_cargo():
    dois = [_linha(1, "PAULO ROCHA", "PT", "PA", 50), _linha(2, "PAULO ROCHA", "PT", "MG", 54)]
    pessoa = {"nome": "Paulo Rocha", "cargo_na_epoca": "Deputado federal", "partido_na_epoca": "PT"}
    assert fe.escolher_deputado(pessoa, dois) is None  # dois deputados com o mesmo nome e partido: sem foto
    assert fe.escolher_deputado({**pessoa, "cargo_na_epoca": "Deputado federal (PA)"}, dois)["id"] == 1  # o estado desempata
    assert fe.escolher_deputado({**pessoa, "cargo_na_epoca": "Empresário"}, dois) is None
    assert fe.escolher_deputado({**pessoa, "cargo_na_epoca": "Deputado estadual (PA)"}, dois) is None
    # nome parecido não basta: tem que ser igual
    assert fe.escolher_deputado({**pessoa, "nome": "Paulo"}, dois) is None


def test_apelido_entre_parenteses_e_partido_que_mudou_de_sigla():
    lin = [_linha(9, "PROFESSOR LUIZINHO", "PT", "SP", 53)]
    pessoa = {"nome": "Luiz Carlos da Silva (Professor Luizinho)", "cargo_na_epoca": "Deputado federal (SP)", "partido_na_epoca": "PT"}
    assert fe.escolher_deputado(pessoa, lin)["id"] == 9
    fiuza = [_linha(74557, "RICARDO FIUZA", "PFL", "PE", 51)]
    assert fe.escolher_deputado({"nome": "Ricardo Fiuza", "cargo_na_epoca": "Deputado federal (PE)", "partido_na_epoca": "DEM"}, fiuza)["id"] == 74557
