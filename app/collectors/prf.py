"""Acidentes nas rodovias federais (PRF, dados abertos), arquivos "agrupados por ocorrência".

A página oficial lista um link do Google Drive por ano e tipo ("Documento CSV de Acidentes 2025 (Agrupados por ocorrência)"). Os links NÃO ficam
escritos no código: o descobridor lê a página, casa o título com o link "Baixar planilha" seguinte e baixa pelo endereço de download direto do Drive.
Guardamos só somas por estado/mês, causa, tipo e rodovia; coordenadas e o resto da ocorrência não. Anos fechados já gravados não são baixados de novo."""
import csv
import html
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
from app.utils import UFS, upsert

log = logging.getLogger("brasilplus.prf")
PAGINA = "https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-da-prf"
DRIVE = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"
TIPO = "Agrupados por ocorrência"
MINIMO = {"fechado": 30_000, "corrente": 3_000}
COLUNAS = ("data_inversa", "uf", "br", "causa_acidente", "tipo_acidente", "mortos", "feridos_leves", "feridos_graves", "pessoas", "veiculos")


def descobrir(texto_html: str, tipo: str = TIPO) -> dict[int, str]:
    """{ano: id do arquivo} lendo a página oficial; pega o primeiro link 'Baixar planilha' depois de cada título."""
    t = html.unescape(texto_html)
    achados: dict[int, str] = {}
    atual = None
    for m in re.finditer(r"Documento CSV de Acidentes (\d{4}) \(([^)]*)\)|<a[^>]*href=\"https://drive\.google\.com/file/d/([^/\"]+)/[^\"]*\"[^>]*>\s*Baixar planilha", t):
        if m.group(1):
            atual = (int(m.group(1)), m.group(2).strip())
        elif atual:
            if atual[1] == tipo:
                achados.setdefault(atual[0], m.group(3))
            atual = None
    return achados


def num(v) -> float:
    v = (v or "").strip()
    try:
        return float(v.replace(",", ".")) if v and v != "NA" else 0.0
    except ValueError:
        return 0.0


def agregar(leitor, cab: list[str]) -> dict:
    faltam = [c for c in COLUNAS if c not in cab]
    if faltam:
        raise ValueError(f"Arquivo da PRF mudou: faltam {faltam}")
    i = {c: cab.index(c) for c in COLUNAS}
    maximo = max(i.values())
    meses: dict[str, dict] = {}
    causas: dict[str, list] = {}
    tipos: dict[str, list] = {}
    rodovias: dict[str, list] = {}
    total = 0
    for l in leitor:
        if len(l) <= maximo:
            continue
        uf = l[i["uf"]].strip()
        data = l[i["data_inversa"]].strip()
        if uf not in UFS or len(data) < 7:
            continue
        mortos, feridos = int(num(l[i["mortos"]])), int(num(l[i["feridos_leves"]]) + num(l[i["feridos_graves"]]))
        total += 1
        chave = f"{uf}|{data[:7]}"
        e = meses.setdefault(chave, [0, 0, 0])
        e[0] += 1
        e[1] += mortos
        e[2] += feridos
        for dic, nome in ((causas, l[i["causa_acidente"]].strip()), (tipos, l[i["tipo_acidente"]].strip()), (rodovias, f"{uf}-BR-{l[i['br']].strip()}")):
            x = dic.setdefault(nome or "Não informado", [0, 0, 0])
            x[0] += 1
            x[1] += mortos
            x[2] += feridos
    return {"acidentes": total, "meses": meses, "causas": causas, "tipos": tipos, "rodovias": rodovias}


def _lista(dic: dict, n: int, chave: str) -> list[dict]:
    return [{chave: k, "acidentes": v[0], "mortos": v[1], "feridos": v[2]} for k, v in sorted(dic.items(), key=lambda x: -x[1][0])[:n]]


def resumir(ag: dict, ano: int) -> dict:
    por_uf: dict[str, dict] = {}
    mensal: dict[str, dict] = {}
    for chave, (a, m, f) in ag["meses"].items():
        uf, ym = chave.split("|")
        u = por_uf.setdefault(uf, {"acidentes": 0, "mortos": 0, "feridos": 0})
        u["acidentes"] += a
        u["mortos"] += m
        u["feridos"] += f
        t = mensal.setdefault(ym, {"acidentes": 0, "mortos": 0, "feridos": 0})
        t["acidentes"] += a
        t["mortos"] += m
        t["feridos"] += f
    tot = {k: sum(u[k] for u in por_uf.values()) for k in ("acidentes", "mortos", "feridos")}
    return {"ano": ano, "total": tot, "por_uf": por_uf, "mensal": dict(sorted(mensal.items())), "ultimo_mes": max(mensal) if mensal else None,
            "causas": _lista(ag["causas"], 15, "causa"), "tipos": _lista(ag["tipos"], 12, "tipo"), "rodovias": _lista(ag["rodovias"], 25, "rodovia")}


def baixar_ano(ano: int, id_arquivo: str) -> Path:
    destino = Path(tempfile.mkdtemp(prefix="prf-")) / f"{ano}.zip"
    http.baixar(DRIVE.format(id=id_arquivo), str(destino))
    if not zipfile.is_zipfile(destino):
        raise RuntimeError(f"PRF {ano}: o Drive não devolveu um zip (limite de cota ou página de aviso)")
    return destino


def coletar_prf_acidentes(anos: int = 5):
    """Descobre os arquivos na página oficial e importa os `anos` mais recentes (o ano corrente é sempre refeito)."""
    with registrar_coleta("prf", "acidentes") as (db, n):
        achados = descobrir(http.get(PAGINA).text)
        if not achados:
            raise RuntimeError("PRF: nenhum link de 'Agrupados por ocorrência' na página oficial (a página mudou?)")
        hoje = date.today().year
        for ano in sorted(achados, reverse=True)[: int(anos)]:
            if ano < hoje and db.query(Registro).filter_by(fonte="prf", tipo="acidentes_ano", chave=str(ano)).first():
                continue
            try:
                arq = baixar_ano(ano, achados[ano])
                with zipfile.ZipFile(arq) as z:
                    nome = next(x for x in z.namelist() if x.lower().endswith(".csv"))
                    leitor = csv.reader(io.TextIOWrapper(z.open(nome), encoding="latin-1", newline=""), delimiter=";")
                    ag = agregar(leitor, [c.strip().lower() for c in next(leitor)])
                arq.unlink(missing_ok=True)
                minimo = MINIMO["corrente" if ano == hoje else "fechado"]
                if ag["acidentes"] < minimo:
                    raise RuntimeError(f"PRF {ano}: só {ag['acidentes']:,} acidentes (esperado ≥ {minimo:,}); nada foi gravado")
                d = resumir(ag, ano)
                upsert(db, Registro, {"fonte": "prf", "tipo": "acidentes_ano", "chave": str(ano)},
                       {"ano": ano, "titulo": f"Acidentes nas rodovias federais {ano}", "valor": float(d["total"]["acidentes"]), "dados": d})
                db.commit()
                n += 1
            except Exception as e:  # noqa: BLE001 - um ano que falha não derruba os outros
                n.avisos.append(f"{ano}: {type(e).__name__}: {str(e)[:150]}")
        if not n.itens and n.avisos:
            raise RuntimeError("; ".join(n.avisos))
    return n.itens
