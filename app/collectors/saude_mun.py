"""Saúde por município: leitos (CNES) e cobertura vacinal (PNI).

Leitos (tarefa saude-leitos-municipios): arquivo anual "Hospitais e Leitos" do Ministério da Saúde
(s3 ckan.saude.gov.br/Leitos_SUS/json/Leitos_json_<ano>.zip, conjunto dadosabertos.saude.gov.br/dataset/hospitais-e-leitos):
uma linha por hospital e competência (mês) com leitos EXISTENTES, leitos SUS e UTI (adulto, pediátrica, neonatal, queimados,
coronariana). Soma por município e mês. "Existente" é o leito cadastrado no CNES, não o leito livre nem o em funcionamento no dia
(ocupação não é publicada em base aberta). A divisão clínico/cirúrgico só existe na API /assistencia-a-saude/cnes-leitos, que em
11/2026 devolve uma linha por chamada (não serve para o país inteiro).

Vacinação (tarefa saude-vacinacao): cobertura vacinal OFICIAL do PNI pelo TabNet (bd_pni/cpnibr.def, webtabx.exe), por município
no último ano da base e série por estado desde 1994. A base aberta do TabNet vai até 2022; de 2023 em diante a cobertura oficial só
sai em painel interativo (infoms.saude.gov.br), que não é dado aberto — fica registrado como indisponível, nada é estimado.
A cobertura pode passar de 100% (doses aplicadas a quem mora em outro lugar, estimativa de população).
"""
from __future__ import annotations

import io
import json
import logging
import re
import urllib.parse
import zipfile
from datetime import date

import httpx

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UF_POR_CODIGO_IBGE, upsert

log = logging.getLogger("brasilplus.saude_mun")

LEITOS_URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/Leitos_SUS/json/Leitos_json_{ano}.zip"
LEITOS_PAGINA = "https://dadosabertos.saude.gov.br/dataset/hospitais-e-leitos"
UTI = ("ADULTO", "PEDIATRICO", "NEONATAL", "QUEIMADO", "CORONARIANA")
MESES_SERIE = 24

PNI_DEF = "bd_pni/cpnibr.def"
PNI_FORM = "http://tabnet.datasus.gov.br/cgi/dhdat.exe?" + PNI_DEF
PNI_TAB = "http://tabnet.datasus.gov.br/cgi/webtabx.exe?" + PNI_DEF
VACINAS = ("BCG", "Hepatite B", "Rotavírus Humano", "Penta", "Pneumocócica", "Poliomielite", "Meningococo C",
           "Febre Amarela", "Tríplice Viral  D1", "Tríplice Viral  D2", "Hepatite A")
_nome = " ".join  # "Tríplice Viral  D1" (dois espaços no TabNet) vira "Tríplice Viral D1"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)"}


def _int(v) -> int:
    try:
        return int(float(str(v or 0).replace(",", ".")))
    except ValueError:
        return 0


# ---------------- leitos ----------------
def somar_leitos(linhas) -> dict:
    """{(cod6, comp): {...}} somando os hospitais. Hospital desabilitado (MOTIVO_DESABILITACAO preenchido) fica de fora."""
    out: dict = {}
    for x in linhas:
        if (x.get("MOTIVO_DESABILITACAO") or "").strip():
            continue
        cod = re.sub(r"\D", "", str(x.get("CO_IBGE") or ""))[:6]
        comp = re.sub(r"\D", "", str(x.get("COMP") or ""))
        if len(cod) != 6 or len(comp) != 6:
            continue
        d = out.setdefault((cod, comp), {"uf": x.get("UF"), "hospitais": 0, "existentes": 0, "sus": 0, "uti_exist": 0, "uti_sus": 0,
                                         **{f"uti_{t.lower()}": 0 for t in UTI}, **{f"uti_{t.lower()}_sus": 0 for t in UTI}})
        d["hospitais"] += 1
        d["existentes"] += _int(x.get("LEITOS_EXISTENTES"))
        d["sus"] += _int(x.get("LEITOS_SUS"))
        d["uti_exist"] += _int(x.get("UTI_TOTAL_EXIST"))
        d["uti_sus"] += _int(x.get("UTI_TOTAL_SUS"))
        for t in UTI:
            d[f"uti_{t.lower()}"] += _int(x.get(f"UTI_{t}_EXIST"))
            d[f"uti_{t.lower()}_sus"] += _int(x.get(f"UTI_{t}_SUS"))
    return out


def ler_leitos_ano(ano: int, cli: httpx.Client) -> list[dict]:
    r = cli.get(LEITOS_URL.format(ano=ano), timeout=300)
    if r.status_code in (403, 404):
        return []
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nome = next(n for n in z.namelist() if n.lower().endswith(".json"))
    return json.loads(z.read(nome).decode("utf-8", errors="replace"))


def coletar_leitos_municipios(anos: list[int] | None = None):
    """Leitos por município: o último mês com todos os detalhes e a série dos últimos 24 meses (existentes, SUS, UTI)."""
    hoje = date.today().year
    if isinstance(anos, str):
        anos = anos.split(",")
    anos = [int(a) for a in (anos or [hoje - 1, hoje])]
    with registrar_coleta("cnes", "leitos_municipios", anos=",".join(map(str, anos))) as (db, n), httpx.Client(headers=UA, follow_redirects=True) as cli:
        por: dict = {}
        for ano in anos:
            linhas = ler_leitos_ano(ano, cli)
            if not linhas:
                n.avisos.append(f"arquivo de leitos de {ano} não publicado")
                continue
            por.update(somar_leitos(linhas))
        if not por:
            raise RuntimeError("nenhum arquivo de leitos foi lido")
        comps = sorted({c for _, c in por})
        ultima = comps[-1]
        no_mes = {cod: d for (cod, c), d in por.items() if c == ultima}
        total = sum(d["existentes"] for d in no_mes.values())
        if len(no_mes) < 2500 or total < 300_000:  # leitura cortada: não troca o dado anterior
            raise RuntimeError(f"leitura incompleta de {ultima}: {len(no_mes)} municípios, {total} leitos")
        serie_meses = comps[-MESES_SERIE:]
        for cod, d in no_mes.items():
            serie = {c: [por[(cod, c)]["existentes"], por[(cod, c)]["sus"], por[(cod, c)]["uti_exist"]] for c in serie_meses if (cod, c) in por}
            upsert(db, Registro, {"fonte": "cnes", "tipo": "leitos_municipio", "chave": cod},
                   {"uf": d["uf"], "titulo": f"leitos {cod}", "valor": d["existentes"],
                    "dados": {**d, "nao_sus": d["existentes"] - d["sus"], "competencia": f"{ultima[:4]}-{ultima[4:]}", "serie": serie}})
            n += 1
        brasil = {k: sum(d[k] for d in no_mes.values()) for k in next(iter(no_mes.values())) if k != "uf"}
        upsert(db, Registro, {"fonte": "cnes", "tipo": "leitos_resumo", "chave": "BR"},
               {"titulo": "leitos Brasil", "valor": brasil["existentes"],
                "dados": {**brasil, "nao_sus": brasil["existentes"] - brasil["sus"], "competencia": f"{ultima[:4]}-{ultima[4:]}",
                          "municipios_com_leitos": len(no_mes), "fonte": LEITOS_PAGINA,
                          "serie": {c: sum(por[k]["existentes"] for k in por if k[1] == c) for c in serie_meses}}})
        db.commit()
    return n.itens


# ---------------- vacinação (TabNet do PNI) ----------------
def _opcoes(html: str, nome: str) -> list[str]:
    m = re.search(r'NAME="' + re.escape(nome) + r'"[^>]*>(.*?)</SELECT>', html, re.S | re.I)
    return re.findall(r'<option value="([^"]*)"', m.group(1)) if m else []


def tabela_google(html: str) -> tuple[list[str], list[list]]:
    """Resultado do webtabx: data.addColumn(...) + data.addRows([...]). Devolve (colunas, linhas) com números já convertidos."""
    cols = re.findall(r"data\.addColumn\('(?:string|number)','([^']*)'\)", html)
    m = re.search(r"data\.addRows\(\[(.*?)\]\);", html, re.S)
    linhas = []
    for bloco in re.findall(r"\[\s*([\"'].*?)\]\s*(?=,|$)", m.group(1) if m else "", re.M):
        rot = re.match(r'\s*"((?:[^"\\]|\\.)*)"', bloco) or re.match(r"\s*'((?:[^'\\]|\\.)*)'", bloco)
        vals = [float(v) if v not in ("null", "") else None for v in re.findall(r"\{v:\s*([-\d.eE]+|null)", bloco)]
        if rot:
            linhas.append([rot.group(1).replace("\\'", "'").replace('\\"', '"').strip(), *vals])
    return cols, linhas


class PNI:
    def __init__(self, cli: httpx.Client):
        self.cli = cli
        self.form = cli.get(PNI_FORM, timeout=180).content.decode("latin-1")
        self.inc = {o.split("|")[0].strip(): o for o in _opcoes(self.form, "Incremento")}
        self.anos = sorted(int(o.split("|")[0]) for o in _opcoes(self.form, "PAno") if o[:4].isdigit())
        self.filtros = re.findall(r'NAME="(S[^"]+)"', self.form)
        self.linhas = {o.split("|")[0]: o for o in _opcoes(self.form, "Linha")}
        self.colunas = {o.split("|")[0]: o for o in _opcoes(self.form, "Coluna")}

    def consultar(self, linha: str, coluna: str | None, vacinas, anos) -> tuple[list[str], list[list]]:
        dados = [("Linha", self.linhas[linha]), ("Coluna", self.colunas[coluna] if coluna else "--Não-Ativa--")]
        dados += [("Incremento", self.inc[v]) for v in vacinas if v in self.inc]
        dados += [("PAno", f"{a}|{a}|4") for a in anos]
        dados += [(s, "TODAS_AS_CATEGORIAS__") for s in self.filtros] + [("formato", "prn"), ("mostre", "Mostra"), ("nomedef", PNI_DEF)]
        r = self.cli.post(PNI_TAB, content=urllib.parse.urlencode(dados, encoding="latin-1"),
                          headers={**UA, "Content-Type": "application/x-www-form-urlencoded"}, timeout=300)
        r.raise_for_status()
        return tabela_google(r.content.decode("latin-1"))


def coletar_vacinacao():
    """Cobertura vacinal oficial: por município no último ano da base aberta e série por estado (todas as vacinas de VACINAS)."""
    with registrar_coleta("datasus", "vacinacao") as (db, n), httpx.Client(headers=UA, follow_redirects=True) as cli:
        pni = PNI(cli)
        if not pni.anos:
            raise RuntimeError("formulário do PNI sem anos")
        ultimo = pni.anos[-1]
        vacinas = [v for v in VACINAS if v in pni.inc]
        cols, linhas = pni.consultar("Município", None, vacinas, [ultimo])
        mun = 0
        for l in linhas:
            m = re.match(r"(\d{6})\s+(.*)", l[0])
            if not m:
                continue
            cob = {_nome(c.split()): round(v, 2) for c, v in zip(cols[1:], l[1:]) if v is not None}  # o TabNet mostra 2 casas
            if not cob:
                continue
            uf = UF_POR_CODIGO_IBGE.get(int(m.group(1)[:2]))
            upsert(db, Registro, {"fonte": "datasus", "tipo": "vacinacao_municipio", "chave": m.group(1)},
                   {"uf": uf, "ano": ultimo, "titulo": m.group(2).strip(), "dados": {"ano": ultimo, "cobertura": cob}})
            mun += 1
            n += 1
        if mun < 5000:
            raise RuntimeError(f"cobertura por município incompleta ({mun} municípios)")
        # série por estado e Brasil: uma consulta por vacina (com coluna = ano, o TabNet aceita uma medida só)
        series: dict = {}
        brasil: dict = {}
        for v in vacinas:
            cols, linhas = pni.consultar("Unidade da Federação", "Ano", [v], pni.anos)
            anos_cols = cols[1:]
            for l in linhas:
                valores = {a: round(x, 2) for a, x in zip(anos_cols, l[1:]) if x is not None and a[:4].isdigit()}
                m = re.match(r"(\d{2})\s", l[0])
                if m and int(m.group(1)) in UF_POR_CODIGO_IBGE:
                    series.setdefault(UF_POR_CODIGO_IBGE[int(m.group(1))], {})[_nome(v.split())] = valores
                elif l[0].strip().lower() == "total":
                    brasil[_nome(v.split())] = valores
        for uf, s in series.items():
            upsert(db, Registro, {"fonte": "datasus", "tipo": "vacinacao_uf", "chave": uf},
                   {"uf": uf, "ano": ultimo, "titulo": f"vacinação {uf}", "dados": {"ano": ultimo, "serie": s}})
            n += 1
        upsert(db, Registro, {"fonte": "datasus", "tipo": "vacinacao_uf", "chave": "BR"},
               {"ano": ultimo, "titulo": "vacinação Brasil", "dados": {"ano": ultimo, "serie": brasil, "anos": pni.anos, "vacinas": [_nome(v.split()) for v in vacinas],
                                                                          "fonte": "TabNet/DATASUS — " + PNI_DEF,
                                                                          "aviso": "A base aberta de cobertura vacinal vai até " + str(ultimo) +
                                                                          "; dali em diante o Ministério publica só em painel interativo, sem arquivo aberto. Nada é estimado."}})
        db.commit()
    return n.itens
