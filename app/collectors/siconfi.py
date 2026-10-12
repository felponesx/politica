"""Finanças dos estados — API do SICONFI (Tesouro Nacional).
Docs: https://apidatalake.tesouro.gov.br/docs/siconfi/

- Arrecadação/receitas: RREO Anexo 01 (balanço orçamentário) e Anexo 03 (receita corrente líquida)
- Dívida: RGF Anexo 02 (dívida consolidada líquida)
"""
from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import CODIGO_IBGE_POR_UF, UFS, hash_curto, para_float, upsert

BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"


def paginar(endpoint: str, params: dict):
    offset = 0
    while True:
        resp = http.get_json(f"{BASE}/{endpoint}", params={**params, "offset": offset}) or {}
        itens = resp.get("items", [])
        yield from itens
        if not resp.get("hasMore") or not itens:
            break
        offset += len(itens)


def _salvar(db, tipo: str, uf: str, ano: int, item: dict):
    chave = hash_curto(uf, ano, item.get("periodo"), item.get("cod_conta"), item.get("conta"), item.get("coluna"))
    upsert(db, Registro, {"fonte": "siconfi", "tipo": tipo, "chave": chave}, {
        "uf": uf, "ano": ano, "titulo": item.get("conta"), "valor": para_float(item.get("valor")), "dados": item,
    })


def coletar_receitas_estados(ano: int, bimestre: int = 6, ufs: list[str] | None = None):
    """RREO Anexo 01 (receitas/despesas orçamentárias) e Anexo 03 (RCL) de cada estado."""
    with registrar_coleta("siconfi", "receitas_estados", ano=ano, bimestre=bimestre) as (db, n):
        for uf in ufs or UFS:
            for anexo, tipo in (("RREO-Anexo 01", "rreo-anexo01"), ("RREO-Anexo 03", "rreo-anexo03-rcl")):
                for item in paginar("rreo", {
                    "an_exercicio": ano, "nr_periodo": bimestre, "co_tipo_demonstrativo": "RREO",
                    "no_anexo": anexo, "co_esfera": "E", "id_ente": CODIGO_IBGE_POR_UF[uf],
                }):
                    _salvar(db, tipo, uf, ano, item)
                    n += 1
            db.commit()
    return n.itens


def coletar_divida_estados(ano: int, quadrimestre: int = 3, ufs: list[str] | None = None):
    """RGF Anexo 02 — dívida consolidada de cada estado (poder Executivo)."""
    with registrar_coleta("siconfi", "divida_estados", ano=ano, quadrimestre=quadrimestre) as (db, n):
        for uf in ufs or UFS:
            for item in paginar("rgf", {
                "an_exercicio": ano, "in_periodicidade": "Q", "nr_periodo": quadrimestre,
                "co_tipo_demonstrativo": "RGF", "no_anexo": "RGF-Anexo 02", "co_esfera": "E",
                "co_poder": "E", "id_ente": CODIGO_IBGE_POR_UF[uf],
            }):
                _salvar(db, "rgf-anexo02-divida", uf, ano, item)
                n += 1
            db.commit()
    return n.itens


# ---------- despesa por função (RREO Anexo 02) ----------
from app.utils import sem_acento  # noqa: E402

# As 28 funções de governo (Portaria MOG 42/1999). Linhas com outros nomes são subfunções e ficam de fora.
FUNCOES = ["Legislativa", "Judiciária", "Essencial à Justiça", "Administração", "Defesa Nacional",
           "Segurança Pública", "Relações Exteriores", "Assistência Social", "Previdência Social", "Saúde",
           "Trabalho", "Educação", "Cultura", "Direitos da Cidadania", "Urbanismo", "Habitação", "Saneamento",
           "Gestão Ambiental", "Ciência e Tecnologia", "Agricultura", "Organização Agrária", "Indústria",
           "Comércio e Serviços", "Comunicações", "Energia", "Transporte", "Desporto e Lazer", "Encargos Especiais"]
_FUNCOES_NORM = {sem_acento(f): f for f in FUNCOES}

# Código IBGE das 27 capitais (esfera municipal)
CAPITAIS = {"RO": 1100205, "AC": 1200401, "AM": 1302603, "RR": 1400100, "PA": 1501402, "AP": 1600303,
            "TO": 1721000, "MA": 2111300, "PI": 2211001, "CE": 2304400, "RN": 2408102, "PB": 2507507,
            "PE": 2611606, "AL": 2704302, "SE": 2800308, "BA": 2927408, "MG": 3106200, "ES": 3205309,
            "RJ": 3304557, "SP": 3550308, "PR": 4106902, "SC": 4205407, "RS": 4314902, "MS": 5002704,
            "MT": 5103403, "GO": 5208707, "DF": 5300108}


def _nome_funcao(conta: str | None) -> str | None:
    import re
    s = sem_acento(re.sub(r"\(.*?\)|[0-9]+", "", conta or "")).strip(" -.")
    return _FUNCOES_NORM.get(s)


def somar_funcoes(itens) -> dict:
    """{função: {"dotacao", "empenhado", "liquidado"}} a partir das linhas do Anexo 02."""
    out = {}
    for it in itens:
        f = _nome_funcao(it.get("conta"))
        if not f:
            continue
        col = sem_acento(it.get("coluna") or "")
        campo = ("empenhado" if "EMPENHADAS ATE O BIMESTRE" in col else
                 "liquidado" if "LIQUIDADAS ATE O BIMESTRE" in col else
                 "dotacao" if "DOTACAO ATUALIZADA" in col else None)
        v = para_float(it.get("valor"))
        if not campo or v is None:
            continue
        d = out.setdefault(f, {"dotacao": None, "empenhado": None, "liquidado": None})
        # a mesma função pode aparecer de novo no bloco intraorçamentário (valor menor): fica o maior
        d[campo] = v if d[campo] is None else max(d[campo], v)
    return out


def coletar_despesas_funcao(ano: int, bimestre: int = 6, esferas: list[str] | None = None, ufs: list[str] | None = None):
    """Despesa por função da União (U), dos estados (E) e das capitais (C). Ex.: esferas=U,E,C."""
    esferas = [e.upper() for e in (esferas or ["U", "E", "C"])]
    entes = []
    if "M" in esferas:  # todos os municípios (requer ibge-municipios); demora: ~5.570 consultas
        from sqlalchemy import select as _sel

        from app.db import SessionLocal
        from app.models import Municipio
        _db = SessionLocal()
        try:
            capitais = set(CAPITAIS.values())
            for m in _db.scalars(_sel(Municipio).where(Municipio.uf.in_(ufs or UFS))):
                if int(m.codigo_ibge) not in capitais or "C" not in esferas:
                    entes.append(("M", int(m.codigo_ibge), m.uf, f"Prefeitura de {m.nome}"))
        finally:
            _db.close()
    if "U" in esferas:
        entes.append(("U", 1, None, "União"))
    for uf in ufs or UFS:
        if "E" in esferas:
            entes.append(("E", CODIGO_IBGE_POR_UF[uf], uf, f"Governo do estado ({uf})"))
        if "C" in esferas:
            entes.append(("M", CAPITAIS[uf], uf, f"Prefeitura da capital ({uf})"))
    with registrar_coleta("siconfi", "despesas_funcao", ano=ano, bimestre=bimestre, esferas=",".join(esferas)) as (db, n):
        for esfera, id_ente, uf, rotulo in entes:
            itens = list(paginar("rreo", {"an_exercicio": ano, "nr_periodo": bimestre, "co_tipo_demonstrativo": "RREO",
                                          "no_anexo": "RREO-Anexo 02", "co_esfera": esfera, "id_ente": id_ente}))
            ente = (itens[0].get("instituicao") if itens else None) or rotulo
            for funcao, v in somar_funcoes(itens).items():
                upsert(db, Registro, {"fonte": "siconfi", "tipo": "despesa_funcao",
                                      "chave": f"{esfera}-{id_ente}-{ano}-{funcao}"},
                       {"uf": uf, "ano": ano, "titulo": funcao, "valor": v["liquidado"],
                        "dados": {**v, "esfera": ("C" if id_ente in CAPITAIS.values() else "M") if esfera == "M" else esfera,
                                  "id_ente": id_ente,
                                  "ente": ente, "bimestre": bimestre}})
                n += 1
            db.commit()
    return n.itens


# ---------- tributos próprios de estados e municípios (RREO Anexo 03, últimos 12 meses) ----------
# O impostômetro precisa dos impostos estaduais (ICMS, IPVA, ITCD) e municipais (ISS, IPTU, ITBI), que a Receita
# Federal não arrecada. O Anexo 03 (Receita Corrente Líquida) traz cada um com a coluna "TOTAL (ÚLTIMOS 12 MESES)".
TRIBUTOS = {"icms": r"^icms\b", "ipva": r"^ipva\b", "itcd": r"^itc(m)?d\b", "iss": r"^iss(qn)?\b", "iptu": r"^iptu\b",
            "itbi": r"^itbi\b", "irrf": r"^irrf\b"}


def tributos_anexo03(itens: list[dict]) -> dict | None:
    """{"total": impostos, taxas e contribuições de melhoria em 12 meses, "por_tributo": {...}} de um ente."""
    import re as _re
    total, por = None, {}
    for it in itens:
        if not _re.search(r"total.*12\s*meses", sem_acento(str(it.get("coluna") or "")).lower()):
            continue
        conta = sem_acento(str(it.get("conta") or "")).lower().strip()
        cod = str(it.get("cod_conta") or "").lower()
        v = para_float(it.get("valor"))
        if v is None:
            continue
        if total is None and (conta.startswith("impostos, taxas e contribuicoes de melhoria")
                              or "impostostaxasecontribuicoesdemelhoria" in cod):
            total = v
            continue
        for k, rx in TRIBUTOS.items():
            if k not in por and _re.search(rx, conta):
                por[k] = v
    if total is None and por:
        total = sum(por.values())
    return {"total": round(total, 2), "por_tributo": {k: round(v, 2) for k, v in por.items()}} if total else None


def coletar_tributos_entes(ano: int, bimestre: int = 6, esferas: list[str] | None = None, ufs: list[str] | None = None):
    """Impostos próprios em 12 meses de cada estado (E) e de cada município (M; precisa de ibge-municipios)."""
    esferas = [e.upper() for e in (esferas or ["E", "M"])]
    entes = [("E", CODIGO_IBGE_POR_UF[uf], uf) for uf in (ufs or UFS) if "E" in esferas]
    if "M" in esferas:
        from sqlalchemy import select as _sel

        from app.db import SessionLocal
        from app.models import Municipio
        with SessionLocal() as _db:
            entes += [("M", int(m.codigo_ibge), m.uf) for m in _db.scalars(_sel(Municipio).where(Municipio.uf.in_(ufs or UFS)))]
    with registrar_coleta("siconfi", "tributos_entes", ano=ano, bimestre=bimestre, esferas=",".join(esferas)) as (db, n):
        sem = 0
        for k, (esfera, id_ente, uf) in enumerate(entes):
            try:
                itens = list(paginar("rreo", {"an_exercicio": ano, "nr_periodo": bimestre, "co_tipo_demonstrativo": "RREO",
                                              "no_anexo": "RREO-Anexo 03", "co_esfera": esfera, "id_ente": id_ente}))
            except Exception:
                sem += 1
                continue
            t = tributos_anexo03(itens)
            if not t:
                sem += 1
                continue
            upsert(db, Registro, {"fonte": "siconfi", "tipo": "tributos_ente", "chave": f"{esfera}-{id_ente}-{ano}"},
                   {"uf": uf, "ano": ano, "titulo": (itens[0].get("instituicao") if itens else None) or str(id_ente),
                    "valor": t["total"], "dados": {**t, "esfera": esfera, "id_ente": id_ente, "bimestre": bimestre}})
            n += 1
            if k % 200 == 0:
                db.commit()
        if sem:
            n.avisos.append(f"{sem} de {len(entes)} entes sem o Anexo 03 de {ano} (não entregaram ou mudou o formato)")
    return n.itens
