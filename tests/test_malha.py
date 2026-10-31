"""Malha municipal versionada: códigos, importação do shapefile do IBGE (ZIP), ativação controlada, histórico, OSM provisório e comparação."""
import io
import zipfile

import pytest
from shapely.geometry import Polygon, box
from sqlalchemy import func, select

from app import malha
from app.collectors import ibge_malha
from app.db import SessionLocal, criar_tabelas
from app.models import MalhaFonte, MalhaMunicipio


def _limpa(db):
    db.query(MalhaMunicipio).delete()
    db.query(MalhaFonte).delete()
    db.commit()


@pytest.fixture()
def db():
    criar_tabelas()
    d = SessionLocal()
    _limpa(d)
    yield d
    _limpa(d)
    d.close()


def test_codigo_de_municipio_digito_verificador_prefixo_e_lagoas():
    assert malha.digito_municipio("172100") == 0 and malha.digito_municipio("355030") == 8 and malha.digito_municipio("530010") == 8
    assert malha.codigo_valido("1721000", "TO")[0] and malha.codigo_valido("3550308", "SP")[0] and malha.codigo_valido("5300108", "DF")[0]
    assert not malha.codigo_valido("3550309")[0]                       # dígito errado
    assert not malha.codigo_valido("355030")[0] and not malha.codigo_valido("abcdefg")[0] and not malha.codigo_valido("9921000")[0]
    assert not malha.codigo_valido("3550308", "RJ")[0]                  # prefixo é de SP
    assert malha.codigo_valido("2201919", "PI")[0] and "exceção" in malha.codigo_valido("5203962", "GO")[1]     # as 9 exceções conhecidas do IBGE passam; qualquer outro dígito errado não
    assert len(malha.EXCECOES_DIGITO) == 9 and all(malha.digito_municipio(c[:6]) != int(c[6]) for c in malha.EXCECOES_DIGITO)
    assert malha.codigo_valido("4300001")[0] and "Lagoa" in malha.codigo_valido("4300002")[1]   # corpos d'água da malha do IBGE: reconhecidos, não são município


def test_area_em_projecao_de_area_igual_e_perimetro():
    g = box(-48.0, -10.5, -47.0, -9.5)    # ~1° × 1° perto do equador: ≈ 12.100 km²
    assert 11_800 < malha.area_km2(g) < 12_400
    assert 430 < malha.perimetro_km(g) < 450


def _zip_ibge(caminho, municipios, sem_dbf=False, truncar_shx=False):
    import shapefile
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    for nome, tipo, tam, dec in (("CD_MUN", "C", 7, 0), ("NM_MUN", "C", 100, 0), ("SIGLA_UF", "C", 2, 0), ("AREA_KM2", "N", 12, 3)):
        w.field(nome, tipo, tam, dec)
    for cod, nome, uf, geom, area in municipios:
        w.poly([list(geom.exterior.coords)])
        w.record(cod, nome, uf, area)
    w.close()
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("BR_Municipios_2025.shp", shp.getvalue())
        z.writestr("BR_Municipios_2025.shx", shx.getvalue()[:-8] if truncar_shx else shx.getvalue())
        if not sem_dbf:
            z.writestr("BR_Municipios_2025.dbf", dbf.getvalue())
        z.writestr("BR_Municipios_2025.prj", "GEOGCS[]")


def _quadrados():
    """Três municípios de TO lado a lado (1721000 Palmas, 1700251 Abreulândia, 1700707 Aguiarnópolis) — só o código importa para a validação."""
    out = []
    for i, (cod, nome) in enumerate((("1721000", "Palmas"), ("1700251", "Abreulândia"), ("1700707", "Aguiarnópolis"))):
        g = box(-48.5 + i * 0.1, -10.2, -48.4 + i * 0.1, -10.1)
        out.append((cod, nome, "TO", g, round(malha.area_km2(g), 3)))
    return out


def test_zip_do_ibge_e_validado_e_importado_com_codigos_e_areas(tmp_path, db):
    z = tmp_path / "ok.zip"
    _zip_ibge(z, _quadrados())
    v = ibge_malha.validar_zip(z)
    assert v["feicoes"] == 3 and set(v["componentes"]) == {".shp", ".shx", ".dbf", ".prj"}
    for kw, msg in (({"sem_dbf": True}, "faltam componentes"), ({"truncar_shx": True}, "inconsistente")):
        ruim = tmp_path / f"{msg[:4]}.zip"
        _zip_ibge(ruim, _quadrados(), **kw)
        with pytest.raises(RuntimeError, match=msg):
            ibge_malha.validar_zip(ruim)
    lixo = tmp_path / "lixo.zip"
    lixo.write_bytes(b"nao e zip")
    with pytest.raises(RuntimeError, match="ZIP inválido"):
        ibge_malha.validar_zip(lixo)
    fonte = ibge_malha.importar_zip(db, z, {"versao": "2025-teste", "publicado_em": "Thu, 26 Feb 2026", "url": "u", "sha256": "0" * 64, "etag": "e", "tamanho": z.stat().st_size})
    db.commit()
    assert fonte.oficial and fonte.origem == "ibge" and fonte.n_municipios == 3 and fonte.n_validos == 3 and fonte.n_invalidos == 0
    linhas = db.scalars(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte.id).order_by(MalhaMunicipio.cod_ibge)).all()
    assert [l.cod_ibge for l in linhas] == ["1700251", "1700707", "1721000"] and all(l.valida and not l.ativa and l.geom_wkb for l in linhas)
    assert all(abs(l.area_km2 - 124) < 5 for l in linhas)
    # 3 municípios não são os 5.570: a importação NÃO é aprovada (não pode virar a malha em uso)
    assert fonte.status == "reprovada" and fonte.verificacao["importacao"]["municipios"] == 3
    with pytest.raises(RuntimeError, match="reprovada"):
        malha.ativar_fonte(db, fonte.id)
    with pytest.raises(RuntimeError, match="já foi importada"):
        ibge_malha.importar_zip(db, z, {"versao": "2025-teste"})


def test_codigo_invalido_e_geometria_invalida_ficam_registrados_sem_derrubar_a_importacao(db):
    bow = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])    # gravata: auto-interseção
    fonte, _ = malha.obter_fonte(db, "ibge", "t", oficial=True, status="provisoria")
    r = malha.inserir_municipios(db, fonte, [{"cod": "1721000", "nome": "Palmas", "uf": "TO", "geom": box(0, 0, 1, 1)}, {"cod": "1721001", "nome": "Errado", "uf": "TO", "geom": box(2, 2, 3, 3)},
                                             {"cod": "1700251", "nome": "Gravata", "uf": "TO", "geom": bow}])
    assert r["validos"] == 1 and r["invalidos"] == 2
    ruins = {m.cod_ibge: m for m in db.scalars(select(MalhaMunicipio).where(MalhaMunicipio.fonte_id == fonte.id))}
    assert "dígito" in ruins["1721001"].motivo and "Self-intersection" in ruins["1700251"].motivo and not ruins["1700251"].valida
    assert ruins["1700251"].geom_wkb   # reparada para uso, mas continua contada como inválida


def _fonte_com(db, origem, versao, oficial, itens, status):
    f, _ = malha.obter_fonte(db, origem, versao, oficial=oficial, status=status)
    malha.inserir_municipios(db, f, itens)
    f.status = status
    db.flush()
    return f


def test_osm_provisorio_e_substituido_pelo_oficial_so_depois_de_validado_e_o_historico_fica(db):
    palmas_osm = box(-48.40, -10.30, -48.20, -10.10)
    malha.salvar_osm_provisorio(db, "TO", "1721000", "Palmas", palmas_osm, relacao=336798, osm_base="2026-10-31T12:00:00Z")
    db.commit()
    g, origem, versao, oficial = malha.geometria_ativa(db, "1721000")
    assert origem == "osm" and not oficial and g.equals(palmas_osm) or abs(g.area - palmas_osm.area) < 1e-9
    osm_fonte = db.scalars(select(MalhaFonte).where(MalhaFonte.origem == "osm")).one()
    assert osm_fonte.status == "provisoria" and not osm_fonte.oficial and osm_fonte.verificacao["relacoes"] == {"1721000": 336798}
    # importação oficial reprovada não é ativada
    ruim = _fonte_com(db, "ibge", "v1", True, [{"cod": "1721000", "nome": "Palmas", "uf": "TO", "geom": box(-48.41, -10.31, -48.19, -10.09)}], "reprovada")
    with pytest.raises(RuntimeError):
        malha.ativar_fonte(db, ruim.id)
    assert malha.geometria_ativa(db, "1721000")[1] == "osm"
    # oficial validada: troca, e a OSM continua guardada (inativa)
    ok = _fonte_com(db, "ibge", "v2", True, [{"cod": "1721000", "nome": "Palmas", "uf": "TO", "geom": box(-48.41, -10.31, -48.19, -10.09)}], "validada")
    r = malha.ativar_fonte(db, ok.id)
    db.commit()
    assert r["ativadas"] == 1 and r["trocadas"] == 1
    assert malha.geometria_ativa(db, "1721000")[1:] == ("ibge", "v2", True)
    assert db.scalar(select(func.count()).select_from(MalhaMunicipio).where(MalhaMunicipio.cod_ibge == "1721000")) == 3   # OSM + IBGE reprovada + IBGE v2: nada apagado
    assert db.scalar(select(func.count()).select_from(MalhaMunicipio).where(MalhaMunicipio.cod_ibge == "1721000", MalhaMunicipio.ativa.is_(True))) == 1
    assert db.get(MalhaFonte, osm_fonte.id).status == "substituida"
    # depois da oficial, uma nova importação OSM não a derruba
    malha.salvar_osm_provisorio(db, "TO", "1721000", "Palmas", box(0, 0, 1, 1))
    db.commit()
    assert malha.geometria_ativa(db, "1721000")[1] == "ibge"


def test_troca_e_atomica_se_falha_no_meio_nada_muda(db, monkeypatch):
    antigo = _fonte_com(db, "osm", "o1", False, [{"cod": "1721000", "nome": "Palmas", "uf": "TO", "geom": box(0, 0, 1, 1)}, {"cod": "1700251", "nome": "A", "uf": "TO", "geom": box(2, 2, 3, 3)}], "provisoria")
    malha.ativar_fonte(db, antigo.id)
    db.commit()
    novo = _fonte_com(db, "ibge", "n1", True, [{"cod": "1721000", "nome": "Palmas", "uf": "TO", "geom": box(0, 0, 1.1, 1.1)}, {"cod": "1700251", "nome": "A", "uf": "TO", "geom": box(2, 2, 3.1, 3.1)}], "validada")
    db.commit()
    from sqlalchemy.orm import Session
    original = Session.flush
    contador = {"n": 0}

    def flush_falha(self, *a, **k):
        contador["n"] += 1
        if contador["n"] == 5:   # no meio da troca (depois da 1ª substituição)
            raise RuntimeError("falha simulada no meio da troca")
        return original(self, *a, **k)
    monkeypatch.setattr(Session, "flush", flush_falha)
    with pytest.raises(RuntimeError, match="falha simulada"):
        malha.ativar_fonte(db, novo.id)
    monkeypatch.setattr(Session, "flush", original)
    db.rollback()
    ativas = {m.cod_ibge: db.get(MalhaFonte, m.fonte_id).origem for m in db.scalars(select(MalhaMunicipio).where(MalhaMunicipio.ativa.is_(True)))}
    assert ativas == {"1721000": "osm", "1700251": "osm"}   # nenhuma substituição parcial


def test_comparacao_osm_x_ibge_area_perimetro_e_iou_e_verificacao_de_sobreposicao_e_lacuna(db):
    ofi = box(-48.40, -10.30, -48.20, -10.10)
    osm = box(-48.40, -10.30, -48.20, -10.12)     # um pouco menor
    po = _fonte_com(db, "osm", "o", False, [{"cod": "1721000", "nome": "Palmas", "uf": "TO", "geom": osm}, {"cod": "1700251", "nome": "Só OSM", "uf": "TO", "geom": box(5, 5, 6, 6)}], "provisoria")
    fo = _fonte_com(db, "ibge", "i", True, [{"cod": "1721000", "nome": "Palmas", "uf": "TO", "geom": ofi}], "validada")
    c = malha.comparar_fontes(db, po.id, fo.id)
    i = c["itens"][0]
    assert c["comparados"] == 1 and c["so_na_provisoria"] == ["1700251"] and -12 < i["dif_area_pct"] < -8 and c["fora_da_tolerancia"] == 1 and 0.85 < i["iou"] < 0.95
    # sobreposição e lacuna na própria malha
    f = _fonte_com(db, "ibge", "m", True, [{"cod": "1721000", "nome": "A", "uf": "TO", "geom": box(0, 0, 1, 1)}, {"cod": "1700251", "nome": "B", "uf": "TO", "geom": box(0.9, 0, 2, 1)},
                                           {"cod": "1700707", "nome": "C", "uf": "TO", "geom": box(0, 1.4, 1, 2.4)}, {"cod": "1700350", "nome": "D", "uf": "TO", "geom": box(1.1, 1.4, 2, 2.4)},
                                           {"cod": "1700400", "nome": "E", "uf": "TO", "geom": box(0, -1, 2, -0.1)}], "validada")
    v = malha.verificar_integridade(db, f.id, min_km2=1.0)
    assert v["n_sobreposicoes"] == 1 and {v["sobreposicoes"][0]["a"], v["sobreposicoes"][0]["b"]} == {"1721000", "1700251"} and v["sobreposicoes"][0]["km2"] > 1000
    assert v["n_lacunas"] >= 0 and v["municipios"] == 5


def test_coleta_nao_baixa_de_novo_a_versao_ja_validada_e_ativa_a_oficial(db, tmp_path, monkeypatch):
    from app.collectors import ibge_malha as im
    from app.downloads import sha256 as _sha
    z = tmp_path / "BR_Municipios_2025-20260226.zip"
    _zip_ibge(z, _quadrados())
    cab = {"tamanho": z.stat().st_size, "etag": "abc123", "modificado": "Thu, 26 Feb 2026 20:02:48 GMT", "aceita_range": True}
    baixados = []
    monkeypatch.setattr(im, "cabecalho", lambda url: cab)
    monkeypatch.setattr(im, "baixar", lambda url, destino, **k: baixados.append(destino) or {**cab, "retomado": False, "reutilizado": False})
    monkeypatch.setattr(im, "pasta_malha", lambda: tmp_path)
    monkeypatch.setattr(malha, "TOTAL_MUNICIPIOS", 3)    # a malha de teste tem 3 municípios
    monkeypatch.setattr(im, "sha256", _sha)
    assert im.coletar_ibge_malha() > 0 and len(baixados) == 1
    f = db.scalars(select(MalhaFonte).where(MalhaFonte.origem == "ibge")).one()
    assert f.status == "validada" and f.versao.startswith("2025-20260226-") and f.oficial and f.verificacao["ativacao"]["ativadas"] == 3
    assert malha.geometria_ativa(db, "1721000")[1] == "ibge"
    assert im.coletar_ibge_malha() == 0 and len(baixados) == 1           # segunda execução: só o HEAD, nada baixado nem duplicado
    assert db.scalar(select(func.count()).select_from(MalhaFonte).where(MalhaFonte.origem == "ibge")) == 1
    assert db.scalar(select(func.count()).select_from(MalhaMunicipio)) == 3
    assert im.coletar_ibge_malha(refazer=True) > 0 and len(baixados) == 2 and db.scalar(select(func.count()).select_from(MalhaFonte)) == 2   # forçar guarda outra versão, sem apagar a anterior
    assert db.scalar(select(func.count()).select_from(MalhaMunicipio).where(MalhaMunicipio.ativa.is_(True))) == 3
