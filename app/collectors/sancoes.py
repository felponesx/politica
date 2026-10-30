"""Empresas punidas: CEIS (inidôneas e suspensas), CNEP (multas da Lei Anticorrupção) e acordos de leniência da CGU.

Arquivos diários do Portal da Transparência, sem chave: https://portaldatransparencia.gov.br/download-de-dados/{ceis|cnep|acordos-leniencia}/AAAAMMDD
(zip com CSV ';' em latin-1; o de hoje costuma sair no fim do dia, então se tenta os últimos dias). Só entram pessoas jurídicas (CNPJ): pessoas físicas ficam de fora.
Um registro por CNPJ (`sancao_empresa`) e um resumo (`sancoes_resumo`, chave BR)."""
import csv
import io
import re
import zipfile
from datetime import date, timedelta

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

URL = "https://portaldatransparencia.gov.br/download-de-dados/{base}/{dia:%Y%m%d}"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)", "Accept": "*/*"}
MINIMO = {"ceis": 10_000, "cnep": 800, "acordos-leniencia": 50}   # linhas esperadas (guarda contra arquivo cortado)
SANCOES_POR_EMPRESA = 12
TOP = 25


def so_digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def para_iso(v) -> str | None:
    m = re.fullmatch(r"\s*(\d{2})/(\d{2})/(\d{4})\s*", str(v or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def numero(v) -> float:
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if str(v or "").strip() else 0.0
    except ValueError:
        return 0.0


def _col(cab, *padroes):
    norm = [re.sub(r"\s+", " ", sem_acento(c).lower()).strip() for c in cab]
    for p in padroes:
        for i, h in enumerate(norm):
            if re.search(p, h):
                return i
    return None


def baixar(base: str, hoje: date | None = None) -> tuple[date, dict[str, str]]:
    """({data}, {nome do csv: texto}) do arquivo mais novo publicado nos últimos 12 dias."""
    hoje = hoje or date.today()
    for d in range(0, 12):
        dia = hoje - timedelta(days=d)
        r = http._cliente.get(URL.format(base=base, dia=dia), headers=UA, timeout=300)
        if r.status_code == 200 and r.content[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(r.content))
            return dia, {n: z.read(n).decode("latin-1") for n in z.namelist() if n.lower().endswith(".csv")}
    raise RuntimeError(f"Portal da Transparência: sem arquivo de {base} nos últimos 12 dias")


def ler_linhas(texto: str, minimo: int, nome: str) -> tuple[list, list]:
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = next(leitor)
    linhas = [l for l in leitor if l]
    if len(linhas) < minimo:
        raise RuntimeError(f"{nome}: só {len(linhas)} linhas (esperado ≥ {minimo:,}); nada foi gravado")
    return cab, linhas


def _indices(cab, cadastro: str) -> dict:
    i = {"cnpj": _col(cab, r"^cpf ou cnpj"), "tipo": _col(cab, r"^tipo de pessoa"), "nome": _col(cab, r"^nome do sancionado"),
         "razao": _col(cab, r"^razao social"), "categoria": _col(cab, r"^categoria da sancao"), "inicio": _col(cab, r"^data inicio sancao"),
         "fim": _col(cab, r"^data final sancao"), "orgao": _col(cab, r"^orgao sancionador"), "uf": _col(cab, r"^uf orgao"), "esfera": _col(cab, r"^esfera orgao"),
         "abrangencia": _col(cab, r"^abrag"), "codigo": _col(cab, r"^codigo da sancao"), "multa": _col(cab, r"^valor da multa") if cadastro == "CNEP" else None}
    faltam = [k for k, v in i.items() if v is None and k != "multa"] + (["multa"] if cadastro == "CNEP" and i["multa"] is None else [])
    if faltam:
        raise ValueError(f"Arquivo {cadastro} mudou: faltam {faltam} em {cab[:6]}")
    return i


def agregar(cadastros: dict[str, tuple[list, list]], hoje: date | None = None) -> dict[str, dict]:
    """{cnpj: {nome, cadastros, sancoes[], vigente, multa_total, n}} só de pessoas jurídicas; as sanções mais novas primeiro."""
    hoje_iso = (hoje or date.today()).isoformat()
    out: dict[str, dict] = {}
    for cad, (cab, linhas) in cadastros.items():
        i = _indices(cab, cad)
        for l in linhas:
            if len(l) <= max(v for v in i.values() if v is not None):
                continue
            cnpj = so_digitos(l[i["cnpj"]])
            if len(cnpj) != 14 or l[i["tipo"]].strip().upper() != "J":
                continue
            inicio, fim = para_iso(l[i["inicio"]]), para_iso(l[i["fim"]])
            vigente = bool(inicio and inicio <= hoje_iso and (not fim or fim >= hoje_iso))
            e = out.setdefault(cnpj, {"cnpj": cnpj, "nome": "", "cadastros": [], "sancoes": [], "vigente": False, "multa_total": 0.0, "n": 0})
            e["nome"] = e["nome"] or (l[i["razao"]].strip() or l[i["nome"]].strip())
            if cad not in e["cadastros"]:
                e["cadastros"].append(cad)
            multa = numero(l[i["multa"]]) if i["multa"] is not None else 0.0
            e["sancoes"].append({"cadastro": cad, "categoria": l[i["categoria"]].strip(), "inicio": inicio, "fim": fim, "vigente": vigente,
                                 "orgao": l[i["orgao"]].strip(), "uf": l[i["uf"]].strip() or None, "esfera": l[i["esfera"]].strip().capitalize(),
                                 "abrangencia": l[i["abrangencia"]].strip(), "multa": multa or None})
            e["vigente"] = e["vigente"] or vigente
            e["multa_total"] = round(e["multa_total"] + multa, 2)
            e["n"] += 1
    for e in out.values():
        e["sancoes"].sort(key=lambda s: s["inicio"] or "", reverse=True)
        e["sancoes"] = e["sancoes"][:SANCOES_POR_EMPRESA]
    return out


def ler_acordos(textos: dict[str, str]) -> list[dict]:
    nome_acordos = next((n for n in textos if "acordos" in n.lower()), None)
    if not nome_acordos:
        raise RuntimeError("acordos de leniência: arquivo de acordos não encontrado")
    cab, linhas = ler_linhas(textos[nome_acordos], MINIMO["acordos-leniencia"], "acordos de leniência")
    i = {"id": _col(cab, r"^id do acordo"), "cnpj": _col(cab, r"^cnpj"), "razao": _col(cab, r"^razao social"), "inicio": _col(cab, r"^data de inicio"),
         "fim": _col(cab, r"^data de fim"), "situacao": _col(cab, r"^situacao"), "orgao": _col(cab, r"^orgao")}
    if any(v is None for v in i.values()):
        raise ValueError(f"Arquivo de acordos mudou: {cab}")
    out = []
    for l in linhas:
        if len(l) <= max(i.values()):
            continue
        out.append({"id": l[i["id"]].strip(), "cnpj": so_digitos(l[i["cnpj"]]) or None, "nome": l[i["razao"]].strip(), "inicio": para_iso(l[i["inicio"]]),
                    "fim": para_iso(l[i["fim"]]), "situacao": l[i["situacao"]].strip(), "orgao": l[i["orgao"]].strip()})
    return sorted(out, key=lambda a: a["inicio"] or "", reverse=True)


def resumir(empresas: dict[str, dict], acordos: list[dict], data_base: dict) -> dict:
    cats: dict[str, int] = {}
    ufs: dict[str, int] = {}
    n_sancoes = 0
    for e in empresas.values():
        for s in e["sancoes"]:
            n_sancoes += 1
            if s["cadastro"] == "CEIS":
                cats[s["categoria"]] = cats.get(s["categoria"], 0) + 1
            if s["uf"]:
                ufs[s["uf"]] = ufs.get(s["uf"], 0) + 1
    multas = sorted((e for e in empresas.values() if e["multa_total"]), key=lambda e: -e["multa_total"])
    return {"data_base": data_base, "empresas": len(empresas), "vigentes": sum(1 for e in empresas.values() if e["vigente"]),
            "por_cadastro": {c: sum(1 for e in empresas.values() if c in e["cadastros"]) for c in ("CEIS", "CNEP")},
            "ceis_por_categoria": sorted(cats.items(), key=lambda kv: -kv[1])[:10], "por_uf": sorted(ufs.items(), key=lambda kv: -kv[1]),
            "multa_total_cnep": round(sum(e["multa_total"] for e in empresas.values()), 2),
            "maiores_multas": [{"cnpj": e["cnpj"], "nome": e["nome"], "multa_total": e["multa_total"], "n": e["n"]} for e in multas[:TOP]],
            "acordos_leniencia": acordos, "n_sancoes_guardadas": n_sancoes}


def coletar_sancoes():
    """CEIS, CNEP e acordos de leniência (CGU) por empresa. Só grava se os três arquivos vierem completos."""
    with registrar_coleta("cgu", "sancoes") as (db, n):
        dados, datas = {}, {}
        for base, cad in (("ceis", "CEIS"), ("cnep", "CNEP")):
            dia, textos = baixar(base)
            datas[cad] = dia.isoformat()
            dados[cad] = ler_linhas(next(iter(textos.values())), MINIMO[base], cad)
        dia, textos = baixar("acordos-leniencia")
        datas["Acordos"] = dia.isoformat()
        acordos = ler_acordos(textos)
        empresas = agregar(dados)
        for cnpj, e in empresas.items():
            upsert(db, Registro, {"fonte": "cgu", "tipo": "sancao_empresa", "chave": cnpj}, {"titulo": e["nome"], "valor": e["multa_total"] or None, "dados": e})
            n += 1
            if n.itens % 2000 == 0:
                db.commit()
        upsert(db, Registro, {"fonte": "cgu", "tipo": "sancoes_resumo", "chave": "BR"}, {"titulo": "Empresas punidas", "dados": resumir(empresas, acordos, datas)})
        n += 1
    return n.itens
