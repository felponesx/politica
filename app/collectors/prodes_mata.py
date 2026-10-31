"""PRODES da Mata Atlântica (INPE/TerraBrasilis) pelo shapefile oficial de "Incremento anual na supressão da vegetação nativa (desde 2004)".

Por que existe: o WFS do TerraBrasilis recusa `propertyName` nessa camada ("Can handle 4 attributes only") e, sem ele, devolve a geometria de milhões de polígonos
(502/reset). A página de downloads monta a lista por `GET /business/api/v1/download/all`; o arquivo é versionado no nome (`..._v20260806.zip`), por isso os nomes
chutados antes davam 404. Aqui: descobre o link no catálogo, baixa em streaming com retomada, valida o ZIP e os componentes do shapefile, lê SÓ a tabela de atributos (.dbf,
sem a geometria) em partes, ignora polígonos repetidos pelo `uuid` e soma o desmatamento por estado e ano. Não baixa o GeoPackage de 4,4 GB."""
import hashlib
import logging
import os
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import httpx

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.prodes_mata")
BASE = "https://terrabrasilis.dpi.inpe.br"
CATALOGO = BASE + "/business/api/v1/download/all"
CATEGORIA = "Mata Atlântica - PRODES"
NOME_ARQUIVO = "yearly_deforestation_biome_mata_atlantica"
COMPONENTES = (".shp", ".shx", ".dbf", ".prj")
PRIMEIRO_ANO = 2004
AVISO = ("Incremento anual de supressão da vegetação nativa (PRODES, INPE) — taxa oficial por polígono, soma por estado. "
         "NÃO é o alerta do MapBiomas (metodologia, período e unidade diferentes): nunca somar nem misturar os dois.")


def pasta_destino() -> Path:
    p = Path(os.environ.get("PRODES_DIR") or Path(tempfile.gettempdir()) / "brasilplus_prodes")
    p.mkdir(parents=True, exist_ok=True)
    return p


def catalogo(tentativas: int = 6) -> list[dict]:
    """Catálogo oficial de downloads. O servidor responde 502 de vez em quando: repete com espera crescente."""
    ultimo = None
    for i in range(tentativas):
        try:
            d = http.get(CATALOGO, headers={"Accept": "application/json"}, timeout=60).json()
            if isinstance(d, list) and d:
                return d
            ultimo = "catálogo vazio"
        except Exception as e:  # noqa: BLE001
            ultimo = f"{type(e).__name__}: {str(e)[:80]}"
        time.sleep(min(5 * (i + 1), 40))
    raise RuntimeError(f"catálogo de downloads do TerraBrasilis indisponível ({ultimo})")


def escolher(itens: list[dict]) -> dict:
    """O shapefile do incremento anual da Mata Atlântica (português, ativo, .zip que não seja GeoPackage). Falha se não achar — nada de adivinhar nome."""
    achados = [x for x in itens if x.get("enabled") and x.get("lang") == "pt-br" and NOME_ARQUIVO in (x.get("link") or "")
               and (x.get("link") or "").endswith(".zip") and ".gpkg" not in x["link"]]
    if not achados:
        raise RuntimeError("o catálogo do TerraBrasilis não traz o shapefile do incremento anual da Mata Atlântica")
    x = max(achados, key=lambda i: i.get("created") or "")
    link = x["link"]
    versao = (link.rsplit("_v", 1)[-1].replace(".zip", "") if "_v" in link else "")
    return {"url": BASE + link if link.startswith("/") else link, "publicado_em": x.get("created"), "descricao": x.get("description"), "versao": versao,
            "metadados": (BASE + x["metadata"]) if (x.get("metadata") or "").startswith("/") else x.get("metadata"), "categoria": x.get("category")}


def cabecalho(url: str) -> dict:
    r = http._cliente.head(url, headers={"Accept": "*/*"}, timeout=60)
    r.raise_for_status()
    return {"tamanho": int(r.headers.get("content-length") or 0), "etag": (r.headers.get("etag") or "").strip('"'), "modificado": r.headers.get("last-modified"),
            "aceita_range": "bytes" in (r.headers.get("accept-ranges") or "")}


def baixar(url: str, destino: Path, tentativas: int = 8) -> dict:
    """Download em streaming com retomada: guarda em `<arquivo>.parcial` e continua do byte onde parou (Range) depois de queda. Só renomeia quando o tamanho confere com o do servidor."""
    cab = cabecalho(url)
    final, parcial = destino, destino.with_name(destino.name + ".parcial")
    if final.exists() and final.stat().st_size == cab["tamanho"]:
        return {**cab, "retomado": False, "reutilizado": True}
    retomado = False
    for i in range(tentativas):
        ja = parcial.stat().st_size if parcial.exists() else 0
        if cab["tamanho"] and ja > cab["tamanho"]:
            parcial.unlink()
            ja = 0
        if cab["tamanho"] and ja == cab["tamanho"]:
            break
        headers = {"Accept": "*/*", **({"Range": f"bytes={ja}-"} if ja and cab["aceita_range"] else {})}
        try:
            with http._cliente.stream("GET", url, headers=headers, timeout=httpx.Timeout(60.0, read=120.0)) as r:
                if r.status_code == 200 and ja:   # o servidor ignorou o Range: recomeça do zero
                    ja = 0
                elif r.status_code not in (200, 206):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                retomado = retomado or bool(ja)
                with open(parcial, "ab" if ja else "wb") as f:
                    for pedaco in r.iter_bytes(1 << 20):
                        f.write(pedaco)
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            log.warning("download interrompido (%s); tentativa %s/%s, %s bytes já gravados", type(e).__name__, i + 1, tentativas, parcial.stat().st_size if parcial.exists() else 0)
            time.sleep(min(5 * (i + 1), 60))
            continue
        if not cab["tamanho"] or parcial.stat().st_size == cab["tamanho"]:
            break
    tam = parcial.stat().st_size if parcial.exists() else 0
    if cab["tamanho"] and tam != cab["tamanho"]:
        raise RuntimeError(f"download incompleto: {tam:,} de {cab['tamanho']:,} bytes; o arquivo parcial foi mantido para retomar")
    parcial.replace(final)
    return {**cab, "retomado": retomado, "reutilizado": False}


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def validar_zip(caminho: Path) -> dict:
    """ZIP íntegro (CRC de todos os membros) + os quatro componentes do shapefile + o número de feições do .shx igual ao de registros do .dbf."""
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
        n_dbf = len(shapefile.Reader(dbf=z.open(nomes[".dbf"])))
        n_shx = (nomes[".shx"].file_size - 100) // 8
        if n_dbf != n_shx:
            raise RuntimeError(f"shapefile inconsistente: {n_shx:,} feições no .shx e {n_dbf:,} registros no .dbf")
        return {"feicoes": n_dbf, "componentes": {c: nomes[c].file_size for c in COMPONENTES}, "nome_interno": nomes[".dbf"].filename.rsplit(".", 1)[0]}


def ler_incrementos(caminho: Path) -> tuple[dict, dict]:
    """({UF: {ano: km²}}, estatísticas). Lê só o .dbf, registro a registro (não carrega a geometria nem a tabela inteira na memória).
    Conta apenas `main_class` = DESMATAMENTO (a camada também traz reservatório, nuvem etc.); polígono com o mesmo `uuid` repetido entra uma vez."""
    import shapefile
    soma: dict[str, dict] = {}
    vistos: set[int] = set()
    est = {"lidos": 0, "desmatamento": 0, "outras_classes": 0, "duplicados": 0, "sem_dado": 0, "ano_min": None, "ano_max": None}
    with zipfile.ZipFile(caminho) as z:
        dbf = next(i for i in z.infolist() if i.filename.lower().endswith(".dbf"))
        r = shapefile.Reader(dbf=z.open(dbf))
        campos = [c[0] for c in r.fields[1:]]
        i_uuid, i_uf, i_ano, i_km, i_cls = (campos.index(c) for c in ("uuid", "state", "year", "area_km", "main_class"))
        for rec in r.iterRecords():
            est["lidos"] += 1
            if str(rec[i_cls] or "").strip().upper() != "DESMATAMENTO":
                est["outras_classes"] += 1
                continue
            chave = int.from_bytes(hashlib.blake2b(str(rec[i_uuid]).encode(), digest_size=8).digest(), "big")
            if chave in vistos:
                est["duplicados"] += 1
                continue
            vistos.add(chave)
            uf, ano, km = str(rec[i_uf] or "").strip().upper(), rec[i_ano], rec[i_km]
            if len(uf) != 2 or ano is None or km is None:
                est["sem_dado"] += 1
                continue
            ano = int(ano)
            if ano < PRIMEIRO_ANO:
                continue
            est["desmatamento"] += 1
            est["ano_min"] = ano if est["ano_min"] is None else min(est["ano_min"], ano)
            est["ano_max"] = ano if est["ano_max"] is None else max(est["ano_max"], ano)
            soma.setdefault(uf, {})
            soma[uf][str(ano)] = soma[uf].get(str(ano), 0.0) + float(km)
    return {u: {a: round(v, 2) for a, v in sorted(s.items())} for u, s in sorted(soma.items())}, est


def coletar_prodes_mata_atlantica(refazer: bool = False, arquivo: str = ""):
    """Descobre, baixa, valida e importa o incremento anual da Mata Atlântica. A mesma versão (nome + SHA-256) já importada não é lida de novo (`refazer=true` força).
    Os anos que o arquivo traz substituem os anteriores (o INPE revisa o passado); anos que o arquivo não tem continuam como estavam. `arquivo` = ZIP local (testes)."""
    refazer = str(refazer).lower() in ("true", "1", "sim")
    with registrar_coleta("inpe", "prodes_mata_atlantica", refazer=refazer) as (db, n):
        if arquivo:
            caminho = Path(arquivo)
            info = {"url": str(caminho), "publicado_em": None, "versao": "local", "metadados": None, "descricao": "arquivo local"}
            transf = {"tamanho": caminho.stat().st_size, "retomado": False, "reutilizado": True}
        else:
            info = escolher(catalogo())
            caminho = pasta_destino() / info["url"].rsplit("/", 1)[-1]
            transf = baixar(info["url"], caminho)
        valido = validar_zip(caminho)
        digest = sha256(caminho)
        chave_versao = f"mata_atlantica:{info['versao']}:{digest[:16]}"
        if not refazer and db.query(Registro).filter_by(fonte="inpe", tipo="prodes_download", chave=chave_versao).first():
            log.info("versão %s já importada (SHA-256 %s…); nada a fazer", info["versao"], digest[:12])
            return n.itens
        por_uf, est = ler_incrementos(caminho)
        if est["desmatamento"] == 0 or not por_uf:
            raise RuntimeError("nenhum polígono de desmatamento lido; nada foi gravado")
        if est["lidos"] != valido["feicoes"]:
            raise RuntimeError(f"leu {est['lidos']:,} de {valido['feicoes']:,} registros; nada foi gravado")
        anterior = db.query(Registro).filter_by(fonte="inpe", tipo="prodes_bioma", chave="mata_atlantica").first()
        antigo = (anterior.dados or {}).get("por_uf", {}) if anterior else {}
        anos_novos = {a for s in por_uf.values() for a in s}
        final: dict[str, dict] = {}
        for uf in sorted(set(antigo) | set(por_uf)):
            mantidos = {a: v for a, v in (antigo.get(uf) or {}).items() if a not in anos_novos}
            final[uf] = {a: v for a, v in sorted({**mantidos, **(por_uf.get(uf) or {})}.items())}
        anos = sorted({a for s in final.values() for a in s})
        total = {a: round(sum(s.get(a, 0) for s in final.values()), 2) for a in anos}
        agora = datetime.now().isoformat(timespec="seconds")
        upsert(db, Registro, {"fonte": "inpe", "tipo": "prodes_bioma", "chave": "mata_atlantica"},
               {"titulo": "PRODES Mata Atlântica", "dados": {"bioma": "Mata Atlântica", "camada": "shapefile yearly_deforestation_biome_mata_atlantica", "ultimo_ano": anos[-1], "por_uf": final, "total": total,
                                                          "feicoes": est["desmatamento"], "origem": "arquivo", "versao": info["versao"], "publicado_em": info["publicado_em"], "coletado_em": agora,
                                                          "fonte_url": info["url"], "metadados_url": info["metadados"], "sha256": digest, "aviso": AVISO}})
        upsert(db, Registro, {"fonte": "inpe", "tipo": "prodes_download", "chave": chave_versao},
               {"titulo": f"PRODES Mata Atlântica {info['versao']}", "dados": {"url": info["url"], "versao": info["versao"], "publicado_em": info["publicado_em"], "coletado_em": agora, "sha256": digest,
                                                                              "tamanho": transf["tamanho"], "retomado": transf["retomado"], "etag": transf.get("etag"), "modificado": transf.get("modificado"),
                                                                              "feicoes_no_arquivo": valido["feicoes"], "estatisticas": est, "anos": anos, "descricao": info["descricao"]}})
        db.commit()
        n += 1
    return n.itens
