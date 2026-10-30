"""Doadores de campanha com CNPJ (TSE, prestação de contas), por candidatura: empresa, partido, candidato, eleição, valor, data e origem do recurso.

Usa os mesmos zips e leiautes de `tse_financas` (2002–2026). Só entra doador com CNPJ de 14 dígitos: CPF de pessoa física NÃO é guardado nem lido
adiante. Doações de empresas foram proibidas em 2015: de 2002 a 2014 'empresa' é doação eleitoral histórica; de 2018 em diante os CNPJ são partidos,
comitês e fundos (`tipo_doador = partido_ou_comite`). Aparecer como doador não indica irregularidade."""
import logging
import re
import zipfile
from datetime import date, datetime

from app.collectors.base import registrar_coleta
from app.collectors.tse import sq_unico
from app.collectors.tse_financas import (R_ORIGEM, R_VALOR, SQ, UE, _arquivos, _baixar, _linhas, _pega, _rotulo, url_contas)
from app.models import DoacaoEmpresa
from app.utils import para_float

log = logging.getLogger("brasilplus.doadores")
DOC = ("nr_cpf_cnpj_doador", "cpf_cnpj_do_doador", "numero_cpf_cgc_doador", "cd_cpf_cgc")
NOME = ("nm_doador_rfb", "nome_do_doador_receita_federal", "nm_doador", "nome_do_doador", "nome_doador", "no_doador")
DATA = ("dt_receita", "data_da_receita", "data_receita")
PARTIDO = ("sg_partido", "sigla_partido", "sg_part")
CARGO = ("ds_cargo", "cargo", "descricao_cargo")
CAND = ("nm_candidato", "nome_candidato", "no_cand")
ORIGEM = R_ORIGEM
MINIMO = 500   # linhas de doador CNPJ esperadas por ano (guarda contra arquivo cortado ou leiaute mudado)


def so_cnpj(v) -> str | None:
    d = "".join(c for c in str(v or "") if c.isdigit())
    return d if len(d) == 14 else None


def para_dia(v, ano: int | None = None) -> date | None:
    """Data dd/mm/aaaa. Com `ano`, descarta datas fora de [ano-1, ano+4] (o arquivo tem erros de digitação como 0006 e 2206)."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    if not m:
        return None
    try:
        d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return d if ano is None or ano - 1 <= d.year <= ano + 4 else None


def tipo_doador(origem: str) -> str:
    """empresa (pessoa jurídica), partido_ou_comite, ou cnpj_sem_tipo quando o arquivo da época não diz a origem (2002 traz só a forma do pagamento)."""
    o = origem.lower()
    if ("jur" in o and "dica" in o) or "empresa" in o:
        return "empresa"
    if any(x in o for x in ("partido", "comit", "candidato", "dire", "diret", "fundo", "financiamento")):
        return "partido_ou_comite"
    return "cnpj_sem_tipo"


def agregar(linhas, ano: int) -> tuple[dict, int]:
    """({(cnpj, sq, origem): {...}}, linhas_com_doador_cnpj)"""
    out: dict[tuple, dict] = {}
    n = 0
    for l in linhas:
        cnpj = so_cnpj(_pega(l, *DOC))
        if not cnpj:
            continue
        sq = sq_unico(_pega(l, *SQ), _pega(l, *UE), ano)
        if not sq:
            continue
        v = para_float(_pega(l, *R_VALOR)) or 0
        origem = (_rotulo(_pega(l, *ORIGEM)) or "Origem não informada")[:120]
        n += 1
        e = out.setdefault((cnpj, sq, origem), {"doador": _pega(l, *NOME)[:200] or None, "candidato": _pega(l, *CAND)[:200] or None, "cargo": _pega(l, *CARGO)[:60] or None,
                                                "uf": (_pega(l, "sg_uf", "uf") or "")[:2] or None, "partido": _pega(l, *PARTIDO)[:30] or None,
                                                "valor": 0.0, "n": 0, "ini": None, "fim": None})
        e["valor"] += v
        e["n"] += 1
        d = para_dia(_pega(l, *DATA), ano)
        if d:
            e["ini"] = d if e["ini"] is None or d < e["ini"] else e["ini"]
            e["fim"] = d if e["fim"] is None or d > e["fim"] else e["fim"]
    return out, n


def coletar_tse_doadores(ano: int, uf: str | None = None, arquivo_local: str | None = None):
    """Doadores com CNPJ de uma eleição (todas as candidaturas do arquivo). Refazer o ano atualiza as linhas pela chave (ano, CNPJ, candidato, origem)."""
    with registrar_coleta("tse", "doadores_cnpj", ano=ano, uf=uf or "todas") as (db, n):
        if int(ano) == 2004:
            raise ValueError("2004: o arquivo do TSE não tem o código do candidato; não dá para ligar.")
        caminho = _baixar(url_contas(int(ano)), f"contas_{ano}.zip", arquivo_local)
        agreg: dict[tuple, dict] = {}
        lidas = 0
        with zipfile.ZipFile(caminho) as z:
            f_rec, _ = _arquivos(z.namelist(), int(ano), uf)
            if not f_rec:
                raise RuntimeError(f"{ano}: nenhum arquivo de receitas de candidato no zip do TSE (o leiaute pode ter mudado)")
            for nome in f_rec:
                parcial, k = agregar(_linhas(z, nome), int(ano))
                lidas += k
                agreg.update(parcial)
        if lidas < MINIMO and not uf:
            raise RuntimeError(f"doadores {ano}: só {lidas} linhas com CNPJ (esperado ≥ {MINIMO}); nada foi gravado")
        existentes = {(c, s, o): i for i, c, s, o in db.query(DoacaoEmpresa.id, DoacaoEmpresa.cnpj, DoacaoEmpresa.sq_candidato, DoacaoEmpresa.origem).filter_by(ano=int(ano))}
        agora = datetime.now()
        novas, mudadas = [], []
        for (cnpj, sq, origem), e in agreg.items():
            linha = {"ano": int(ano), "cnpj": cnpj, "doador": e["doador"], "sq_candidato": sq, "candidato": e["candidato"], "cargo": e["cargo"], "uf": e["uf"],
                     "partido": e["partido"], "origem": origem, "tipo_doador": tipo_doador(origem), "valor": round(e["valor"], 2), "n_doacoes": e["n"],
                     "primeira_data": e["ini"], "ultima_data": e["fim"], "coletado_em": agora}
            if (cnpj, sq, origem) in existentes:
                mudadas.append({"id": existentes[(cnpj, sq, origem)], **linha})
            else:
                novas.append(linha)
        for i in range(0, len(novas), 5000):
            db.bulk_insert_mappings(DoacaoEmpresa, novas[i:i + 5000])
        for i in range(0, len(mudadas), 5000):
            db.bulk_update_mappings(DoacaoEmpresa, mudadas[i:i + 5000])
        db.commit()
        n += len(agreg)
        log.info("doadores %s: %s linhas lidas, %s novas, %s atualizadas", ano, lidas, len(novas), len(mudadas))
    return n.itens
