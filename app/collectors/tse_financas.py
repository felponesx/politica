"""Patrimônio declarado e prestação de contas de campanha — dados abertos do TSE.
- Bens: cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_{ano}.zip
- Contas: cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip
  (receitas_candidatos_{ano}_{UF}.csv e despesas_contratadas_candidatos_{ano}_{UF}.csv)
Os arquivos são grandes: use `uf=SP` para importar um estado por vez.
"""
import csv
import io
import os
import tempfile
import zipfile


from app import http
from app.collectors.base import registrar_coleta
from app.models import CandidatoFinancas
from app.utils import para_float, upsert

URL_BENS = "https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_{ano}.zip"
URL_CONTAS = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip"


def _csvs(caminho, filtro, uf=None):
    with zipfile.ZipFile(caminho) as z:
        for nome in z.namelist():
            baixo = nome.lower()
            if not baixo.endswith(".csv") or "brasil" in baixo or not filtro(baixo):
                continue
            if uf and not baixo.endswith(f"_{uf.lower()}.csv"):
                continue
            with z.open(nome) as bruto:
                yield from csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")


def _baixar(url, nome, arquivo_local):
    return arquivo_local or http.baixar(url, os.path.join(tempfile.gettempdir(), nome))


def _soma(d, k, v):
    d[k] = round(d.get(k, 0) + v, 2)


def coletar_bens(ano: int, uf: str | None = None, arquivo_local: str | None = None):
    with registrar_coleta("tse", "bens", ano=ano, uf=uf or "todas") as (db, n):
        por_cand = {}
        for l in _csvs(_baixar(URL_BENS.format(ano=ano), f"bens_{ano}.zip", arquivo_local), lambda b: "bem_candidato" in b, uf):
            sq, v = l.get("SQ_CANDIDATO"), para_float(l.get("VR_BEM_CANDIDATO")) or 0
            if not sq:
                continue
            c = por_cand.setdefault(sq, {"uf": (l.get("SG_UF") or "")[:2] or None, "total": 0.0, "bens": [], "tipos": {}})
            c["total"] += v
            tipo = (l.get("DS_TIPO_BEM_CANDIDATO") or "Outros").strip()
            _soma(c["tipos"], tipo, v)
            c["bens"].append({"tipo": tipo, "descricao": (l.get("DS_BEM_CANDIDATO") or "")[:200], "valor": v})
        for sq, c in por_cand.items():
            upsert(db, CandidatoFinancas, {"ano": ano, "sq_candidato": sq},
                   {"uf": c["uf"], "patrimonio": round(c["total"], 2), "bens_por_tipo": c["tipos"],
                    "bens": sorted(c["bens"], key=lambda b: -b["valor"])[:30]})
            n += 1
            if n.itens % 2000 == 0:
                db.commit()
    return n.itens


def _doc_cnpj(v):
    d = "".join(c for c in str(v or "") if c.isdigit())
    return d if len(d) == 14 else None  # CPF de pessoa física não é guardado


def coletar_contas(ano: int, uf: str | None = None, arquivo_local: str | None = None):
    """Receitas por origem e despesas contratadas por tipo e por fornecedor de cada candidatura (formato conferido com o arquivo real de 2022).
    Cuidados que o arquivo real exige: o zip traz também `receitas_candidatos_doador_originario_*` (mesmo dinheiro visto pela origem: somar
    os dois contaria em dobro) e linhas vazias de despesa ("#NULO", valor 0)."""
    with registrar_coleta("tse", "contas_campanha", ano=ano, uf=uf or "todas") as (db, n):
        caminho = _baixar(URL_CONTAS.format(ano=ano), f"contas_{ano}.zip", arquivo_local)
        rec, desp = {}, {}
        for l in _csvs(caminho, lambda b: "receitas_candidatos" in b and "doador_originario" not in b, uf):
            sq, v = l.get("SQ_CANDIDATO"), para_float(l.get("VR_RECEITA")) or 0
            if sq:
                r = rec.setdefault(sq, {"uf": (l.get("SG_UF") or "")[:2] or None, "total": 0.0, "fontes": {}})
                r["total"] += v
                origem = (l.get("DS_ORIGEM_RECEITA") or "").strip()
                if not origem or origem.startswith("#NULO"):
                    origem = (l.get("DS_FONTE_RECEITA") or "Outras").strip()
                _soma(r["fontes"], origem, v)
        for l in _csvs(caminho, lambda b: "despesas_contratadas_candidatos" in b, uf):
            sq, v = l.get("SQ_CANDIDATO"), para_float(l.get("VR_DESPESA_CONTRATADA")) or 0
            tipo = (l.get("DS_ORIGEM_DESPESA") or "").strip()
            if not sq or (v == 0 and (not tipo or tipo.startswith("#NULO"))):
                continue  # linha vazia do arquivo (candidato sem despesa)
            d = desp.setdefault(sq, {"uf": (l.get("SG_UF") or "")[:2] or None, "total": 0.0, "tipos": {}, "forn": {}})
            d["total"] += v
            _soma(d["tipos"], tipo if tipo and not tipo.startswith("#NULO") else "Outras", v)
            cnpj = _doc_cnpj(l.get("NR_CPF_CNPJ_FORNECEDOR"))
            nome = (l.get("NM_FORNECEDOR_RFB") or l.get("NM_FORNECEDOR") or "").strip()
            if cnpj:
                f = d["forn"].setdefault(cnpj, {"cnpj": cnpj, "nome": nome if not nome.startswith("#NULO") else None, "valor": 0.0})
                f["valor"] = round(f["valor"] + v, 2)
            else:
                f = d["forn"].setdefault("pf", {"cnpj": None, "nome": "Pessoas físicas (várias)", "valor": 0.0})
                f["valor"] = round(f["valor"] + v, 2)
        for sq in set(rec) | set(desp):
            r, d = rec.get(sq, {}), desp.get(sq, {})
            forn = sorted(d.get("forn", {}).values(), key=lambda f: -f["valor"])[:12]
            upsert(db, CandidatoFinancas, {"ano": ano, "sq_candidato": sq},
                   {"uf": r.get("uf") or d.get("uf"), "receitas": round(r.get("total", 0), 2) if r else None,
                    "receitas_por_fonte": r.get("fontes"), "despesas": round(d.get("total", 0), 2) if d else None,
                    "despesas_por_tipo": d.get("tipos"), "despesas_fornecedores": forn or None})
            n += 1
            if n.itens % 2000 == 0:
                db.commit()
    return n.itens
