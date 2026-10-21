"""ISP-RJ (Instituto de Segurança Pública do Rio de Janeiro): ocorrências por área de batalhão.

Base: https://www.ispdados.rj.gov.br/Arquivos/BaseDPEvolucaoMensalCisp.csv (CSV ';', Latin-1, uma linha por delegacia
(CISP) e mês desde 2003). Cada CISP pertence a uma AISP (Área Integrada de Segurança Pública), e cada AISP é a área de um
batalhão da PM (Decreto estadual 41.930/2009). Somamos por AISP e ano: mortes por intervenção de agente do Estado,
prisões em flagrante (apf), mandados de prisão cumpridos (cmp), policiais militares e civis mortos em serviço.

Atenção: são registros feitos NA ÁREA do batalhão, não necessariamente pelo batalhão (uma morte por intervenção na
área pode ter sido causada pelo BOPE, pela Polícia Civil ou por outra unidade).
"""
import csv
import io

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

URL = "https://www.ispdados.rj.gov.br/Arquivos/BaseDPEvolucaoMensalCisp.csv"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Accept": "*/*"}
CAMPOS = {"hom_por_interv_policial": "mortes_intervencao", "apf": "prisoes_flagrante", "cmp": "mandados_cumpridos",
          "pol_militares_mortos_serv": "pms_mortos_servico", "pol_civis_mortos_serv": "pcs_mortos_servico",
          "letalidade_violenta": "letalidade_violenta", "hom_doloso": "homicidio_doloso",
          "apreensao_drogas": "apreensoes_drogas", "registro_ocorrencias": "registros"}


def _int(v) -> int:
    try:
        return int(float(str(v).replace(",", ".") or 0))
    except ValueError:
        return 0


def agregar(texto: str) -> dict:
    """{aisp: {"anos": {ano: {campo: n}}, "munic": [...], "cisps": [...], "ultimo_mes": "AAAA-MM"}}"""
    out, meses = {}, {}
    for lin in csv.DictReader(io.StringIO(texto), delimiter=";"):
        a = str(lin.get("aisp") or "").strip()
        ano = str(lin.get("ano") or "").strip()
        if not a.isdigit() or not ano.isdigit():
            continue
        d = out.setdefault(a, {"anos": {}, "munic": set(), "cisps": set(), "ultimo_mes": ""})
        t = d["anos"].setdefault(ano, {v: 0 for v in CAMPOS.values()} | {"meses": 0})
        for col, k in CAMPOS.items():
            t[k] += _int(lin.get(col))
        mes = f"{ano}-{int(lin.get('mes') or 0):02d}"
        meses.setdefault(ano, set()).add(mes)
        d["ultimo_mes"] = max(d["ultimo_mes"], mes)
        if lin.get("munic"):
            d["munic"].add(lin["munic"].strip())
        if lin.get("cisp"):
            d["cisps"].add(lin["cisp"].strip())
    for d in out.values():
        for ano, t in d["anos"].items():
            t["meses"] = len(meses[ano])  # o ano corrente vem incompleto
        d["munic"], d["cisps"] = sorted(d["munic"]), sorted(d["cisps"], key=lambda c: int(c) if c.isdigit() else 0)
    return out


def ler(bruto: bytes) -> str:
    return bruto.decode("utf-8-sig") if bruto[:3] == b"\xef\xbb\xbf" else bruto.decode("latin-1")


def baixar() -> bytes:
    r = http._cliente.get(URL, headers=UA, timeout=300, follow_redirects=True)
    r.raise_for_status()
    return r.content


def coletar_isp_aisp(arquivo_local: str | None = None):
    """Ocorrências do ISP-RJ somadas por AISP (área de batalhão da PM) e ano, desde 2003."""
    with registrar_coleta("isp-rj", "aisp", url=URL) as (db, n):
        bruto = open(arquivo_local, "rb").read() if arquivo_local else baixar()
        por = agregar(ler(bruto))
        if not por:
            raise RuntimeError("Base do ISP sem linhas reconhecidas")
        for a, d in por.items():
            upsert(db, Registro, {"fonte": "isp-rj", "tipo": "aisp", "chave": a},
                   {"uf": "RJ", "titulo": f"ISP-RJ AISP {a}", "valor": sum(t["mortes_intervencao"] for t in d["anos"].values()),
                    "dados": {"aisp": int(a), **d, "url": URL if not arquivo_local else None}})
            n += 1
    return n.itens
