"""Malha municipal OFICIAL do IBGE pelo servidor de arquivos (geoftp), sem depender da API `servicodados` (que ficou inalcançável a partir do robô e do ambiente de desenvolvimento em 31/10/2026).

Fonte: https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/Brasil/BR_Municipios_2025.zip (≈ 226 MB, Shapefile, SIRGAS 2000).
A versão é a do próprio arquivo (ano + Last-Modified + ETag, lidos num HEAD de poucos bytes): se já foi importada, NADA é baixado. Quando há versão nova: download em streaming com retomada,
ZIP validado, shapefile conferido (.shx = .dbf), polígonos lidos um a um, código de 7 dígitos e dígito verificador conferidos, geometrias validadas, área calculada contra o atributo `AREA_KM2` do IBGE.
A importação entra em `malha_fonte`/`malha_municipio` numa transação; só vira a geometria em uso (`ativar_fonte`) se passar na validação, e a provisória do OSM fica guardada como histórico."""
import logging
import re
import zipfile
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from app.collectors.base import registrar_coleta
from app.db import SessionLocal  # noqa: F401
from app.downloads import baixar, cabecalho, sha256
from app.models import MalhaFonte, MalhaMunicipio, Registro
from app.utils import upsert
from sqlalchemy import select

log = logging.getLogger("brasilplus.ibge_malha")
ANO = 2025
URL = f"https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_{ANO}/Brasil/BR_Municipios_{ANO}.zip"
COMPONENTES = (".shp", ".shx", ".dbf", ".prj")
CAMPOS = ("CD_MUN", "NM_MUN", "SIGLA_UF", "AREA_KM2")


def pasta_malha() -> Path:
    import os
    import tempfile
    p = Path(os.environ.get("MALHA_DIR") or Path(tempfile.gettempdir()) / "brasilplus_malha")
    p.mkdir(parents=True, exist_ok=True)
    return p


def versao_do_arquivo(cab: dict) -> str:
    """`2025-AAAAMMDD-<etag>`: o ano da malha, a data de modificação publicada pelo IBGE e o ETag (muda se o arquivo mudar)."""
    try:
        data = parsedate_to_datetime(cab["modificado"]).strftime("%Y%m%d")
    except (TypeError, ValueError):
        data = "semdata"
    return f"{ANO}-{data}-{(cab.get('etag') or 'sem-etag')[:20]}"


def validar_zip(caminho: Path) -> dict:
    """ZIP íntegro (CRC de todos os membros), os quatro componentes do shapefile e a contagem de feições do .shx igual à de registros do .dbf."""
    try:
        z = zipfile.ZipFile(caminho)
    except zipfile.BadZipFile as e:
        raise RuntimeError(f"ZIP inválido: {e}") from e
    with z:
        ruim = z.testzip()
        if ruim:
            raise RuntimeError(f"ZIP corrompido: membro {ruim}")
        nomes = {Path(i.filename).suffix.lower(): i for i in z.infolist() if not i.is_dir()}
        faltam = [c for c in COMPONENTES if c not in nomes]
        if faltam:
            raise RuntimeError("faltam componentes do shapefile: " + ", ".join(faltam))
        import shapefile
        r = shapefile.Reader(dbf=z.open(nomes[".dbf"]))
        campos = [c[0] for c in r.fields[1:]]
        sem = [c for c in CAMPOS if c not in campos]
        if sem:
            raise RuntimeError("faltam colunas no .dbf: " + ", ".join(sem))
        n_dbf, n_shx = len(r), (nomes[".shx"].file_size - 100) // 8
        if n_dbf != n_shx:
            raise RuntimeError(f"shapefile inconsistente: {n_shx:,} feições no .shx e {n_dbf:,} registros no .dbf")
        return {"feicoes": n_dbf, "componentes": {c: nomes[c].file_size for c in COMPONENTES}, "base": nomes[".shp"].filename.rsplit(".", 1)[0]}


def ler_poligonos(caminho_zip: Path):
    """Gera dicts {cod, nome, uf, area_atrib, geom} um a um (o .shp tem ≈ 320 MB; extraído para disco para o acesso aleatório do .shx ser rápido). Remove os arquivos extraídos ao fim."""
    import shapefile
    from shapely.geometry import shape
    destino = caminho_zip.parent / "extraido"
    destino.mkdir(exist_ok=True)
    with zipfile.ZipFile(caminho_zip) as z:
        membros = [i for i in z.infolist() if Path(i.filename).suffix.lower() in COMPONENTES]
        for i in membros:
            z.extract(i, destino)
    base = next(destino.glob("*.shp")).with_suffix("")
    try:
        with shapefile.Reader(str(base), encoding="utf-8") as r:
            campos = [c[0] for c in r.fields[1:]]
            for sr in r.iterShapeRecords():
                d = dict(zip(campos, sr.record))
                yield {"cod": str(d["CD_MUN"]).strip(), "nome": str(d["NM_MUN"]).strip(), "uf": str(d["SIGLA_UF"] or "").strip() or None, "area_atrib": float(d["AREA_KM2"] or 0) or None,
                       "geom": shape(sr.shape.__geo_interface__) if sr.shape.shapeType else None}
    finally:
        for f in destino.glob("*"):
            f.unlink(missing_ok=True)
        destino.rmdir()


def importar_zip(db, caminho: Path, info: dict) -> MalhaFonte:
    """Importa o ZIP já validado para o banco (uma transação: se algo falhar, nada fica gravado). `info`: versao, publicado_em, url, etag, tamanho."""
    from app import malha
    fonte, nova = malha.obter_fonte(db, "ibge", info["versao"], oficial=True, escopo="municipios", rotulo=f"IBGE — Malha Municipal {ANO} (oficial)", publicado_em=info.get("publicado_em"), url=info.get("url"),
                                    sha256=info.get("sha256"), etag=info.get("etag"), tamanho=info.get("tamanho"), arquivo_local=str(caminho), status="provisoria")
    if not nova:
        raise RuntimeError(f"a versão {info['versao']} já foi importada (fonte {fonte.id}); use refazer=true para reimportar")
    itens = list(ler_poligonos(caminho))
    resumo = malha.inserir_municipios(db, fonte, itens)
    malha.avaliar_ibge(db, fonte, resumo)
    return fonte


def coletar_ibge_malha(refazer: bool = False, ativar: bool = True):
    """Atualiza a malha municipal oficial só quando há versão nova (um HEAD decide; sem versão nova não baixa nada). Valida, importa em transação e, se aprovada, ativa substituindo
    a provisória do OSM (que continua guardada). Depois compara OSM × IBGE e verifica sobreposições e lacunas."""
    refazer, ativar = (str(v).lower() in ("true", "1", "sim") for v in (refazer, ativar))
    from app import malha
    with registrar_coleta("ibge", "malha_municipal", refazer=refazer) as (db, n):
        cab = cabecalho(URL)
        versao = versao_do_arquivo(cab)
        anteriores = db.scalars(select(MalhaFonte).where(MalhaFonte.origem == "ibge", MalhaFonte.versao.like(versao + "%"))).all()
        boa = next((f for f in anteriores if f.status in ("validada", "substituida")), None)
        if boa is not None and not refazer:   # a mesma versão já foi importada e aprovada: um HEAD bastou, nada é baixado
            log.info("malha %s já importada e validada (fonte %s, %s): nada baixado", versao, boa.id, boa.status)
            return n.itens
        existente = anteriores[0] if anteriores else None   # só reprovadas: tenta de novo (a reprovada continua guardada como histórico)
        destino = pasta_malha() / f"BR_Municipios_{ANO}-{versao[5:13]}.zip"
        transf = baixar(URL, destino)
        valido = validar_zip(destino)
        digest = sha256(destino)
        info = {"versao": versao if existente is None else f"{versao}-r{datetime.now():%H%M%S}", "publicado_em": cab.get("modificado"), "url": URL, "sha256": digest, "etag": cab.get("etag"), "tamanho": transf["tamanho"]}
        fonte = importar_zip(db, destino, info)
        fonte.verificacao = {**(fonte.verificacao or {}), "zip": valido, "download": {"retomado": transf["retomado"], "reutilizado": transf["reutilizado"]}}
        db.commit()   # a importação (fonte + geometrias) fica gravada inteira ou nada
        if fonte.status != "validada":
            n.avisos.append(f"importação reprovada na validação: {(fonte.verificacao or {}).get('importacao', {}).get('problemas', [])[:3]}")
            n += 1
            return n.itens
        if ativar:
            troca = malha.ativar_fonte(db, fonte.id)
            db.commit()
            fonte.verificacao = {**fonte.verificacao, "ativacao": troca}
        verificacao = malha.verificar_integridade(db, fonte.id)
        fonte.verificacao = {**fonte.verificacao, "integridade": {k: v for k, v in verificacao.items() if k not in ("municipios",)}}
        osm = db.scalars(select(MalhaFonte).where(MalhaFonte.origem == "osm").order_by(MalhaFonte.id.desc())).first()
        if osm is not None:
            comp = malha.comparar_fontes(db, osm.id, fonte.id)
            upsert(db, Registro, {"fonte": "malha", "tipo": "comparacao_osm_ibge", "chave": fonte.versao}, {"titulo": "Comparação da malha provisória (OSM) com a oficial (IBGE)", "dados": comp})
        db.commit()
        n += fonte.n_municipios
    return n.itens


def comparar_malhas():
    """Recompara a geometria provisória mais recente do OSM com a oficial ativa do IBGE (sem baixar nada)."""
    from app import malha
    with registrar_coleta("malha", "comparacao") as (db, n):
        ibge = db.scalars(select(MalhaFonte).where(MalhaFonte.origem == "ibge", MalhaFonte.status.in_(("validada",))).order_by(MalhaFonte.id.desc())).first()
        osm = db.scalars(select(MalhaFonte).where(MalhaFonte.origem == "osm").order_by(MalhaFonte.id.desc())).first()
        if ibge is None or osm is None:
            raise RuntimeError("falta uma das malhas: " + ("IBGE oficial ainda não importada" if ibge is None else "nenhuma geometria OSM guardada"))
        comp = malha.comparar_fontes(db, osm.id, ibge.id)
        upsert(db, Registro, {"fonte": "malha", "tipo": "comparacao_osm_ibge", "chave": ibge.versao}, {"titulo": "Comparação da malha provisória (OSM) com a oficial (IBGE)", "dados": comp})
        db.commit()
        n += comp["comparados"]
    return n.itens
