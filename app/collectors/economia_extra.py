"""Trabalho (IBGE/PNAD Contínua por estado), fundo eleitoral dos partidos (TSE) e tarifa de energia por distribuidora (ANEEL)."""
import csv
import io
import logging
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UF_POR_CODIGO_IBGE, sem_acento, upsert

log = logging.getLogger("brasilplus.economia_extra")
SIDRA = "https://apisidra.ibge.gov.br/values"
# nome: (tabela, variável, rótulo, unidade); a PNAD Contínua trimestral por UF
SERIES_TRABALHO = {"desocupacao": (4099, 4099, "Taxa de desocupação", "%"), "rendimento": (5436, 5929, "Rendimento médio real habitual", "R$")}
FEFC_URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/fefc_fp/fefc_fp_{ano}.zip"
ANEEL_URL = ("https://dadosabertos.aneel.gov.br/dataset/5a583f3e-1646-4f67-bf0f-69db4203e89e/resource/fcf2906c-7c32-4b9b-a637-054e7a5234f4/download/"
             "tarifas-homologadas-distribuidoras-energia-eletrica.csv")


def num(v) -> float | None:
    t = str(v or "").strip().replace(".", "").replace(",", ".") if "," in str(v or "") else str(v or "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def ler_sidra(linhas: list[dict]) -> dict[str, dict]:
    """{UF: {trimestre 'AAAAMM': valor}} da resposta da API de agregados (primeira linha é o cabeçalho)."""
    out: dict[str, dict] = {}
    for l in linhas[1:]:
        uf = UF_POR_CODIGO_IBGE.get(int(l["D1C"])) if str(l.get("D1C", "")).isdigit() else None
        v = num(l.get("V"))
        if uf and v is not None:
            out.setdefault(uf, {})[str(l["D3C"])] = v
    return out


def coletar_trabalho(trimestres: int = 24):
    """Desocupação e renda do trabalho por estado (PNAD Contínua, IBGE/SIDRA)."""
    with registrar_coleta("ibge", "trabalho") as (db, n):
        for chave, (tabela, var, rotulo, unid) in SERIES_TRABALHO.items():
            try:
                r = http.get_json(f"{SIDRA}/t/{tabela}/n3/all/v/{var}/p/last%20{int(trimestres)}")
                serie = ler_sidra(r or [])
                if len(serie) < 27:
                    raise RuntimeError(f"vieram {len(serie)} estados (esperado 27); nada foi gravado")
                for uf, s in serie.items():
                    ult = max(s)
                    upsert(db, Registro, {"fonte": "ibge", "tipo": f"trabalho_{chave}", "chave": uf}, {"uf": uf, "titulo": f"{rotulo} {uf}", "valor": s[ult],
                                                                                                         "dados": {"rotulo": rotulo, "unidade": unid, "ultimo": ult, "serie": s}})
                db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"{rotulo}: {type(e).__name__}: {str(e)[:150]}")
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhuma série lida")
    return n.itens


def _texto(bruto: bytes) -> str:
    try:
        return bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        return bruto.decode("latin-1")


def ler_fefc(texto: str) -> list[dict]:
    """Fundo Especial de Financiamento de Campanha por partido (somando homens e mulheres só uma vez o valor do partido)."""
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    partidos: dict[str, dict] = {}
    for l in leitor:
        p = partidos.setdefault(l["SG_PARTIDO"].strip(), {"partido": l["SG_PARTIDO"].strip(), "valor": 0.0, "candidatos": 0, "mulheres": 0, "valor_mulheres": 0.0})
        p["valor"] = max(p["valor"], num(l["VR_PARTIDO_FEFC"]) or 0.0)
        q = int(num(l["QT_CANDIDATO"]) or 0)
        p["candidatos"] += q
        if l["DS_GENERO"].strip().lower().startswith("fem"):
            p["mulheres"] += q
            p["valor_mulheres"] += num(l["VR_TOTAL_RECEBIDO_FEFC"]) or 0.0
    out = [{**p, "valor": round(p["valor"], 2), "valor_mulheres": round(p["valor_mulheres"], 2)} for p in partidos.values() if p["valor"] > 0]
    return sorted(out, key=lambda x: -x["valor"])


def coletar_fundos(anos=(2018, 2020, 2022, 2024)):
    """Fundo eleitoral (FEFC) por partido em cada eleição (TSE)."""
    with registrar_coleta("tse", "fundos") as (db, n):
        for ano in anos:
            try:
                destino = Path(tempfile.mkdtemp(prefix="fefc-")) / f"{ano}.zip"
                http.baixar(FEFC_URL.format(ano=ano), str(destino))
                z = zipfile.ZipFile(destino)
                nome = next(x for x in z.namelist() if x.lower().startswith("fefc_genero") and x.lower().endswith(".csv"))
                partidos = ler_fefc(_texto(z.read(nome)))
                if len(partidos) < 5:
                    raise RuntimeError(f"só {len(partidos)} partidos")
                upsert(db, Registro, {"fonte": "tse", "tipo": "fefc_ano", "chave": str(ano)},
                       {"ano": ano, "titulo": f"Fundo eleitoral {ano}", "valor": round(sum(p["valor"] for p in partidos), 2), "dados": {"ano": ano, "partidos": partidos}})
                db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001 - ano sem arquivo (404) ou mudado
                n.avisos.append(f"FEFC {ano}: {type(e).__name__}: {str(e)[:120]}")
        if not n.itens:
            raise RuntimeError("; ".join(n.avisos) or "nenhum ano lido")
    return n.itens


def ler_tarifas(linhas, hoje: date | None = None) -> list[dict]:
    """Tarifa residencial convencional (grupo B1) em vigor por distribuidora: TUSD + TE, em R$/kWh."""
    hoje_iso = (hoje or date.today()).isoformat()
    melhor: dict[str, dict] = {}
    for l in linhas:
        if (l.get("DscSubGrupo") or "").strip() != "B1" or sem_acento(l.get("DscClasse", "")) != "RESIDENCIAL" or sem_acento(l.get("DscSubClasse", "")) != "RESIDENCIAL":
            continue
        if sem_acento(l.get("DscModalidadeTarifaria", "")) != "CONVENCIONAL" or sem_acento(l.get("DscBaseTarifaria", "")) != "TARIFA DE APLICACAO":
            continue
        if sem_acento(l.get("DscDetalhe", "")) != "NAO SE APLICA":
            continue
        ini, fim = (l.get("DatInicioVigencia") or "")[:10], (l.get("DatFimVigencia") or "")[:10]
        if not ini or ini > hoje_iso or (fim and fim < hoje_iso):
            continue
        tusd, te = num(l.get("VlrTUSD")) or 0.0, num(l.get("VlrTE")) or 0.0
        total = (tusd + te) / 1000
        if total <= 0:
            continue
        ag = (l.get("SigAgente") or "").strip()
        if ag not in melhor or ini > melhor[ag]["inicio"]:
            melhor[ag] = {"distribuidora": ag, "cnpj": re.sub(r"\D", "", l.get("NumCNPJDistribuidora", "")), "inicio": ini, "fim": fim or None,
                          "tusd": round(tusd / 1000, 4), "te": round(te / 1000, 4), "total": round(total, 4)}
    return sorted(melhor.values(), key=lambda x: -x["total"])


def coletar_tarifas_energia():
    """Tarifa residencial de energia em vigor por distribuidora (ANEEL)."""
    with registrar_coleta("aneel", "tarifas") as (db, n):
        destino = Path(tempfile.mkdtemp(prefix="aneel-")) / "tarifas.csv"
        http.baixar(ANEEL_URL, str(destino))
        with open(destino, "rb") as f:
            inicio = f.read(4096)
        enc = "utf-8-sig"
        try:
            inicio.decode("utf-8")
        except UnicodeDecodeError:
            enc = "latin-1"
        with open(destino, encoding=enc, newline="") as f:
            lista = ler_tarifas(csv.DictReader(f, delimiter=";"))
        if len(lista) < 40:
            raise RuntimeError(f"só {len(lista)} distribuidoras com tarifa residencial em vigor (esperado ≥ 40); nada foi gravado")
        upsert(db, Registro, {"fonte": "aneel", "tipo": "tarifas_residencial", "chave": "BR"},
               {"titulo": "Tarifa residencial de energia", "dados": {"data": date.today().isoformat(), "distribuidoras": lista}})
        n += 1
        destino.unlink(missing_ok=True)
    return n.itens
