"""Empresas públicas, de economia mista, privadas e concessões, com faturamento e dívida (tarefa empresas-tipo).

Fontes, todas abertas e oficiais:
- CVM, cadastro das companhias abertas (cad_cia_aberta.csv): situação, setor e bolsa; CONTROLE ACIONÁRIO (estatal/privado/
  estrangeiro) do formulário cadastral anual (FCA) mais novo, que é atualizado (o do cadastro geral fica velho).
- CVM, demonstrações financeiras anuais (DFP, dfp_cia_aberta_<ano>.zip): receita (conta 3.01), lucro (3.11) e empréstimos e
  financiamentos (2.01.04 + 2.02.01) do último exercício; consolidado quando houver, senão individual; versão mais nova.
- Receita Federal, cadastro do CNPJ (pela BrasilAPI; reserva: minhareceita.org): natureza jurídica e atividade (CNAE).
- PGFN (já coletada em receita-empresas-porte): dívida ativa com a União das 300 maiores devedoras e das 300 maiores empresas.

Faturamento por empresa só existe em base aberta para companhias abertas (CVM); as demais aparecem com tipo e dívida.
Grava app/dados/empresas_tipos.json. Só dados de empresas (CNPJ), nada de pessoas.

Uso: python -m app.collectors.empresas_tipo [caminho de uma cópia site/dados, para ler /dividas/empresas sem banco]
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import sys
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from app import empresas_tipo as T

log = logging.getLogger("coletor.empresas_tipo")

CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA"
CNPJ_APIS = ("https://brasilapi.com.br/api/cnpj/v1/{}", "https://minhareceita.org/{}")
DESTINO = Path(__file__).resolve().parent.parent / "dados" / "empresas_tipos.json"
UA = {"User-Agent": "BRASILmais/1.0 (dados publicos)"}


def _num(t):
    try:
        return float(str(t).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _so_digitos(t) -> str:
    return re.sub(r"\D", "", str(t or ""))


def cadastro_cvm(cli: httpx.Client) -> dict:
    """{cnpj14: {...}} das companhias abertas ATIVAS."""
    r = cli.get(f"{CVM}/CAD/DADOS/cad_cia_aberta.csv")
    r.raise_for_status()
    out = {}
    for x in csv.DictReader(io.StringIO(r.content.decode("latin-1")), delimiter=";"):
        if (x.get("SIT") or "").upper() != "ATIVO":
            continue
        c = _so_digitos(x.get("CNPJ_CIA"))
        if len(c) == 14:
            out[c] = {"nome": (x.get("DENOM_COMERC") or x.get("DENOM_SOCIAL") or "").strip(), "razao_social": (x.get("DENOM_SOCIAL") or "").strip(),
                      "setor_cvm": (x.get("SETOR_ATIV") or "").strip(), "controle": T.controle_cvm(x.get("CONTROLE_ACIONARIO")),
                      "bolsa": "BOLSA" in (x.get("TP_MERC") or "").upper(), "uf": (x.get("UF") or "").strip() or None,
                      "municipio": (x.get("MUN") or "").strip().title() or None}
    return out


def controle_fca(cli: httpx.Client) -> dict:
    """{cnpj14: (controle, data)} do formulário cadastral (FCA) mais novo. O campo do cadastro geral fica desatualizado
    (a Sabesp, privatizada em 2024, ainda aparece "estatal" lá; no FCA de 2026 está "Privado")."""
    html = cli.get(f"{CVM}/DOC/FCA/DADOS/").text
    anos = sorted({int(a) for a in re.findall(r"fca_cia_aberta_(\d{4})\.zip", html)})
    out: dict = {}
    for ano in anos[-2:]:  # o ano anterior cobre quem ainda não entregou o do ano corrente
        r = cli.get(f"{CVM}/DOC/FCA/DADOS/fca_cia_aberta_{ano}.zip", timeout=120)
        if r.status_code != 200:
            continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        nome = next((n for n in z.namelist() if "_geral_" in n), None)
        if not nome:
            continue
        for x in csv.DictReader(io.StringIO(z.read(nome).decode("latin-1")), delimiter=";"):
            c = _so_digitos(x.get("CNPJ_Companhia"))
            ctrl = T.controle_cvm(x.get("Especie_Controle_Acionario"))
            chave = (ano, int(x.get("Versao") or 0))
            if len(c) == 14 and ctrl and (c not in out or chave >= out[c][2]):
                out[c] = (ctrl, (x.get("Data_Especie_Controle_Acionario") or x.get("Data_Referencia") or "")[:10], chave)
    return {c: v[:2] for c, v in out.items()}


def ano_dfp(cli: httpx.Client) -> int:
    """Último ano com o arquivo anual "cheio" (o do ano corrente começa quase vazio)."""
    html = cli.get(f"{CVM}/DOC/DFP/DADOS/").text
    anos = []
    for ano, tam in re.findall(r"dfp_cia_aberta_(\d{4})\.zip</a>\s+\S+\s+\S+\s+([\d.]+[KMG]?)", html):
        mult = {"K": 1e3, "M": 1e6, "G": 1e9}.get(tam[-1], 1)
        anos.append((int(ano), float(tam.rstrip("KMG")) * mult))
    cheios = [a for a, t in anos if t > 5e6]
    if not cheios:
        raise RuntimeError("nenhum arquivo anual da DFP com tamanho de ano completo")
    return max(cheios)


def balancos(cli: httpx.Client, ano: int) -> dict:
    """{cnpj14: {faturamento, lucro, divida_balanco, exercicio, conta_receita}} do último exercício (valores em R$)."""
    r = cli.get(f"{CVM}/DOC/DFP/DADOS/dfp_cia_aberta_{ano}.zip", timeout=300)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    contas = {"3.01": "faturamento", "3.11": "lucro", "2.01.04": "emprestimos_cp", "2.02.01": "emprestimos_lp"}
    achado: dict = {}
    for tipo in ("ind", "con"):  # consolidado por último: vale sobre o individual
        for dem in ("DRE", "BPP"):
            nome = f"dfp_cia_aberta_{dem}_{tipo}_{ano}.csv"
            if nome not in z.namelist():
                continue
            for x in csv.DictReader(io.StringIO(z.read(nome).decode("latin-1")), delimiter=";"):
                if x.get("ORDEM_EXERC") != "ÚLTIMO" or x.get("CD_CONTA") not in contas:
                    continue
                if x["CD_CONTA"].startswith("2.0") and "mprést" not in (x.get("DS_CONTA") or ""):
                    continue  # bancos e seguradoras usam essas contas para outra coisa
                c = _so_digitos(x.get("CNPJ_CIA"))
                v = _num(x.get("VL_CONTA"))
                if v is None:
                    continue
                v *= 1000 if (x.get("ESCALA_MOEDA") or "").upper() == "MIL" else 1
                versao = int(x.get("VERSAO") or 0)
                e = achado.setdefault(c, {}).setdefault(tipo, {"_v": -1})
                if versao > e["_v"]:  # reapresentação: a versão mais nova substitui tudo
                    achado[c][tipo] = e = {"_v": versao}
                if versao == e["_v"]:
                    e[contas[x["CD_CONTA"]]] = v
                    e["exercicio"] = (x.get("DT_FIM_EXERC") or "")[:10]
                    if x["CD_CONTA"] == "3.01":
                        e["conta_receita"] = (x.get("DS_CONTA") or "").strip()
    out = {}
    for c, por in achado.items():
        e = por.get("con") or por.get("ind")
        if not e or e.get("faturamento") is None:
            continue
        div = [e.get(k) for k in ("emprestimos_cp", "emprestimos_lp") if e.get(k) is not None]
        out[c] = {"faturamento": e.get("faturamento"), "lucro": e.get("lucro"), "divida_balanco": sum(div) if div else None,
                  "exercicio": e.get("exercicio"), "conta_receita": e.get("conta_receita"), "consolidado": "con" in por}
    return out


def cadastro_cnpj(cli: httpx.Client, cnpj: str, pausa: float = 0.35) -> dict | None:
    for base in CNPJ_APIS:
        for tentativa in range(4):
            try:
                r = cli.get(base.format(cnpj), timeout=30)
            except httpx.HTTPError:
                time.sleep(2 * (tentativa + 1))
                continue
            if r.status_code == 200:
                time.sleep(pausa)
                d = r.json()
                return {"natureza_codigo": d.get("codigo_natureza_juridica"), "natureza": d.get("natureza_juridica"),
                        "cnae": str(d.get("cnae_fiscal") or ""), "atividade": d.get("cnae_fiscal_descricao"),
                        "razao_social": d.get("razao_social"), "uf": d.get("uf"), "municipio": (d.get("municipio") or "").title() or None,
                        "capital_social": d.get("capital_social"), "situacao": d.get("descricao_situacao_cadastral")}
            if r.status_code == 404:
                return None
            time.sleep(float(r.headers.get("Retry-After") or 3 * (tentativa + 1)))
    return None


def maiores_da_receita(copia: str | None) -> list[dict]:
    """300 maiores devedoras + 300 maiores empresas (receita-empresas-porte), do banco ou de uma cópia site/dados."""
    E = None
    if copia:
        from scripts.pacotes_copia import ler_copia
        E = ler_copia(Path(copia)).get("/dividas/empresas")
    else:
        try:
            from app.db import SessionLocal
            from app.routers.v02 import dividas_empresas
            with SessionLocal() as db:
                E = dividas_empresas(db)
        except Exception as e:  # sem o dado da Receita, segue só com a CVM
            log.warning("sem /dividas/empresas: %s", e)
    if not isinstance(E, dict):
        return []
    vistos, out = set(), []
    for e in (E.get("maiores_devedoras") or []) + (E.get("maiores_empresas") or []):
        b = _so_digitos(e.get("cnpj_basico")).zfill(8)
        if b and b not in vistos:
            vistos.add(b)
            out.append(e)
    return out


def coletar(copia: str | None = None, destino: Path = DESTINO) -> dict:
    anterior = {}
    if destino.exists():  # cadastro do CNPJ já consultado não é pedido de novo (só os novos)
        try:
            anterior = {e["cnpj"]: e for e in json.loads(destino.read_text(encoding="utf-8")).get("empresas", [])}
        except (ValueError, KeyError):
            anterior = {}
    with httpx.Client(headers=UA, timeout=120, follow_redirects=True) as cli:
        cvm = cadastro_cvm(cli)
        for c, (ctrl, quando) in controle_fca(cli).items():
            if c in cvm:
                cvm[c]["controle"], cvm[c]["controle_desde"] = ctrl, quando or None
        ano = ano_dfp(cli)
        bal = balancos(cli, ano)
        receita = maiores_da_receita(copia)
        empresas: dict[str, dict] = {}
        for c, x in cvm.items():
            empresas[c] = {"cnpj": c, **x, "fonte_lista": "cvm"}
        for e in receita:
            c = T.cnpj_matriz(e["cnpj_basico"])
            d = empresas.setdefault(c, {"cnpj": c, "nome": e.get("nome"), "fonte_lista": "receita"})
            d.update({"divida_uniao": e.get("divida_uniao"), "porte": e.get("porte"), "capital_social": e.get("capital_social"),
                      "recuperacao_judicial": e.get("recuperacao_judicial"), "falida": e.get("falida")})
            d.setdefault("uf", e.get("uf"))
        n_api = 0
        for c, d in empresas.items():
            cad = None
            ant = anterior.get(c)
            if ant and ant.get("natureza_codigo"):
                cad = {k: ant.get(k) for k in ("natureza_codigo", "natureza", "cnae", "atividade", "razao_social", "situacao")}
            else:
                cad = cadastro_cnpj(cli, c)
                n_api += 1
            if cad:
                for k, v in cad.items():
                    if v not in (None, "") and (k not in d or d[k] in (None, "")):
                        d[k] = v
            if c in bal:
                d.update(bal[c])
    lista = []
    for d in empresas.values():
        d["tipo"] = T.tipo_por_natureza(d.get("natureza_codigo"))
        d["concessao"] = T.concessao(d.get("cnae"))
        d["governo"] = T.do_governo(d)
        lista.append(d)
    lista.sort(key=lambda e: -(e.get("faturamento") or 0))
    cont = {k: sum(1 for e in lista if e["tipo"] == k) for k in T.TIPOS}
    doc = {
        "fonte": "CVM (cadastro e demonstrações financeiras anuais), Receita Federal (cadastro do CNPJ) e PGFN (dívida ativa da União)",
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ano_balanco": ano,
        "contagem": {**cont, "concessao": sum(1 for e in lista if e["concessao"]), "governo": sum(1 for e in lista if e["governo"]),
                     "com_faturamento": sum(1 for e in lista if e.get("faturamento") is not None), "total": len(lista)},
        "tipos": T.TIPOS, "explica": T.EXPLICA,
        "aviso": ("Faturamento e dívida do balanço só existem em base aberta para companhias abertas (CVM). Dívida com a União (PGFN) só para as "
                  "300 maiores devedoras e as 300 maiores empresas. Concessão é indicada pela atividade registrada na Receita, não pelo contrato. "
                  "Aparecer na lista não indica irregularidade."),
        "empresas": lista,
    }
    if len(lista) < 300 or doc["contagem"]["com_faturamento"] < 200:
        raise RuntimeError(f"leitura incompleta ({len(lista)} empresas, {doc['contagem']['com_faturamento']} com faturamento): nada gravado")
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(destino)
    return {"empresas": len(lista), "com_faturamento": doc["contagem"]["com_faturamento"], "consultas_cnpj": n_api, "ano_balanco": ano}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(coletar(sys.argv[1] if len(sys.argv) > 1 else None))
