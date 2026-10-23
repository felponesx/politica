"""Patrimônio declarado e prestação de contas de campanha — dados abertos do TSE.
- Bens: cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_{ano}.zip
- Contas: cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip
  (receitas_candidatos_{ano}_{UF}.csv e despesas_contratadas_candidatos_{ano}_{UF}.csv)
Os arquivos são grandes: use `uf=SP` para importar um estado por vez.
"""
import csv
import io
import os
import re
import tempfile
import zipfile


from app import http
from app.collectors.base import registrar_coleta
from app.collectors.tse import sq_unico
from app.models import CandidatoFinancas
from app.utils import para_float, sem_acento, upsert

URL_BENS = "https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_{ano}.zip"


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


def url_contas(ano: int) -> str:
    """O nome do zip mudou ao longo dos anos (conferido com o servidor do TSE em 23/10/2026)."""
    base = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/"
    if ano >= 2018:
        return f"{base}prestacao_de_contas_eleitorais_candidatos_{ano}.zip"
    if ano in (2012, 2014):
        return f"{base}prestacao_final_{ano}.zip"
    return f"{base}prestacao_contas_{ano}.zip"


def _norm(h) -> str:
    return re.sub(r"[^a-z0-9]+", "_", sem_acento(str(h or "")).lower()).strip("_")


def _rotulo(t: str) -> str:
    """Padroniza o texto de origem/tipo: em 2006 e 2008 vem tudo em maiúsculas."""
    t = " ".join(str(t or "").split())
    return t.capitalize() if t.isupper() and len(t) > 3 else t


def _pega(l, *chaves):
    for k in chaves:
        v = (l.get(k) or "").strip()
        if v and not v.startswith("#NULO"):
            return v
    return ""


# nomes de coluna por época (já normalizados por _norm): 2018 em diante · 2010-2016 · 2002-2008
SQ = ("sq_candidato", "sequencial_candidato")
UE = ("sg_ue", "unidade_eleitoral_candidato", "sg_uf")
R_VALOR = ("vr_receita", "valor_receita")
R_ORIGEM = ("ds_origem_receita", "tipo_receita", "ds_titulo", "rtrim_ltrim_dr_ds_titulo", "ds_fonte_receita", "fonte_recurso")
D_VALOR = ("vr_despesa_contratada", "vr_despesa", "valor_despesa")
D_TIPO = ("ds_origem_despesa", "tipo_despesa", "ds_titulo", "rtrim_ltrim_dr_ds_titulo")
F_DOC = ("nr_cpf_cnpj_fornecedor", "cpf_cnpj_do_fornecedor", "numero_cpf_cgc_fornecedor", "cd_cpf_cnpj_fornecedor", "cd_cpf_cgc")
F_NOME = ("nm_fornecedor_rfb", "nome_do_fornecedor_receita_federal", "nm_fornecedor", "nome_fornecedor", "nome_do_fornecedor", "no_for")


def _arquivos(nomes, ano, uf=None):
    """(receitas, despesas): só os arquivos de CANDIDATO (não comitê nem partido), sem o duplicado "doador originário"
    e sem o consolidado "brasil" (em 2008 ele é o único arquivo dos candidatos)."""
    rec, desp = [], []
    for n in nomes:
        b = n.lower().replace("\x88", "e").replace("ê", "e")
        if n.endswith("/") or not b.endswith((".csv", ".txt")) or "leio" in b or "leia" in b:
            continue
        if any(x in b for x in ("comit", "partido", "diretorio", "originario", "orgao_partidario")) or "candidat" not in b:
            continue
        if "brasil" in b and ano != 2008:
            continue
        if uf:  # só os arquivos separados por estado têm UF no nome (2002, 2006 e 2008 são nacionais: o filtro vira do candidato)
            m = re.search(r"_([a-z]{2})\.(?:csv|txt)$", b) or re.search(r"/([a-z]{2})/[^/]*$", b)
            if m and m.group(1) != uf.lower():
                continue
        if "receita" in b:
            rec.append(n)
        elif "despesa" in b:
            desp.append(n)
    return rec, desp


def _linhas(z, nome):
    with z.open(nome) as bruto:
        leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
        cab = None
        for linha in leitor:
            if cab is None:
                cab = [_norm(h) for h in linha]
                continue
            if len(linha) >= 3:
                yield dict(zip(cab, linha))


def coletar_contas(ano: int, uf: str | None = None, arquivo_local: str | None = None, todas: bool = False):
    """Receitas por origem e despesas por tipo e por fornecedor de cada candidatura, de 2002 a 2026 (os leiautes mudam: ver `_arquivos`
    e as tuplas de colunas acima). Conferido com os arquivos reais do TSE (2022/SP, 2014, 2010, 2006, 2002, 2008).
    Cuidados que os arquivos reais exigem: o zip de 2018+ traz também `receitas_candidatos_doador_originario_*` (mesmo dinheiro visto
    pela origem: somar contaria em dobro) e linhas vazias de despesa ("#NULO", valor 0). Se já há candidaturas do ano na tabela de
    candidatos, só elas são guardadas (`todas=true` guarda tudo) (os zips de 2020 e 2024 têm ~450 mil candidaturas). 2004 não traz o código do candidato: não dá para ligar."""
    from sqlalchemy import select

    from app.models import Candidato
    with registrar_coleta("tse", "contas_campanha", ano=ano, uf=uf or "todas", todas=todas) as (db, n):
        if ano == 2004:
            raise ValueError("2004: o arquivo do TSE não tem o código do candidato (só nome e número); não dá para ligar às candidaturas.")
        so_estes = set() if todas else set(db.scalars(select(Candidato.sq_candidato).where(Candidato.ano == ano)))
        if not todas and not so_estes:
            n.avisos.append(f"{ano}: nenhuma candidatura na tabela de candidatos; rode tse-candidatos ano={ano} antes (ou use todas=true)")
            return 0
        caminho = _baixar(url_contas(ano), f"contas_{ano}.zip", arquivo_local)
        rec, desp = {}, {}
        with zipfile.ZipFile(caminho) as z:
            f_rec, f_desp = _arquivos(z.namelist(), ano, uf)
            if not f_rec and not f_desp:
                raise RuntimeError(f"{ano}: nenhum arquivo de candidato no zip do TSE (o leiaute pode ter mudado)")
            for nome in f_rec:
                for l in _linhas(z, nome):
                    sq = sq_unico(_pega(l, *SQ), _pega(l, *UE), ano)
                    if not sq or (so_estes and sq not in so_estes):
                        continue
                    v = para_float(_pega(l, *R_VALOR)) or 0
                    r = rec.setdefault(sq, {"uf": _pega(l, "sg_uf", "uf")[:2] or None, "total": 0.0, "fontes": {}})
                    r["total"] += v
                    _soma(r["fontes"], _rotulo(_pega(l, *R_ORIGEM)) or "Origem não informada", v)
            for nome in f_desp:
                for l in _linhas(z, nome):
                    sq = sq_unico(_pega(l, *SQ), _pega(l, *UE), ano)
                    if not sq or (so_estes and sq not in so_estes):
                        continue
                    v = para_float(_pega(l, *D_VALOR)) or 0
                    tipo = _rotulo(_pega(l, *D_TIPO))
                    if v == 0 and not tipo:
                        continue  # linha vazia do arquivo (candidato sem despesa)
                    d = desp.setdefault(sq, {"uf": _pega(l, "sg_uf", "uf")[:2] or None, "total": 0.0, "tipos": {}, "forn": {}})
                    d["total"] += v
                    _soma(d["tipos"], tipo or "Outras", v)
                    cnpj = _doc_cnpj(_pega(l, *F_DOC))
                    nome_f = _pega(l, *F_NOME)
                    chave = cnpj or "pf"
                    f = d["forn"].setdefault(chave, {"cnpj": cnpj, "nome": (nome_f or None) if cnpj else "Pessoas físicas (várias)", "valor": 0.0})
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
