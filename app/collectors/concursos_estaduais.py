"""Concursos estaduais: um coletor por estado, a partir do diário oficial de cada um (tarefa concursos-estaduais).

Cada estado roda de forma independente (a falha de um não para os outros) e grava em `registros`:
- tipo `concurso` (fonte `doe_<uf>`): cada ato achado (abertura, processo seletivo, convocação, nomeação, homologação/resultado,
  retificação, prorrogação), com a URL da publicação, a data de publicação e a data da coleta;
- tipo `concurso_uf_status` (fonte `doe`, chave = UF): situação da última tentativa, a última coleta bem-sucedida (preservada quando a
  tentativa seguinte falha), quantos atos e o erro. Estado sem coletor fica `sem_coletor` com o motivo — ausência de coleta não é
  ausência de concurso.

Adaptadores conferidos contra as fontes reais em 12/11/2026:
- SP: API da Imprensa Oficial (`do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications`): título, trecho, data e link.
- MT, ES, GO: plataforma comum dos diários (`/busca/busca/buscar/query/<pág>/di:<ini>/df:<fim>/?q=`), Elasticsearch com o texto de
  cada página; o link leva à página do PDF (`/portal/edicoes/download/<diário>/<página>`). O de ES ("multidiarios") traz também diários
  de municípios capixabas: o ato vai como municipal quando o texto é de prefeitura/câmara municipal.
Os demais estão no REGISTRO com o motivo (site não responde daqui, ou a busca só existe na tela, sem rota que dê para ler).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from app.collectors.base import registrar_coleta
from app.collectors.oportunidades import _limpa, area_concurso, classificar_ato, detalhes_edital
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.concursos_estaduais")
UA = {"User-Agent": "Mozilla/5.0 (compatible; BRASILmais/1.0; dados publicos)"}
TERMOS = ('"concurso público"', '"processo seletivo"')

# (UF, diário, endereço, adaptador ou None, motivo quando None)
SEM_ROTA = "a busca do diário só existe na tela (sem rota de dados aberta); falta escrever o leitor deste estado"
NAO_RESPONDE = "o site do diário não respondeu a partir do ambiente de coleta (pode bloquear acesso de fora do Brasil); testar pelo robô"
REGISTRO = [
    ("AC", "Diário Oficial do Acre", "https://diario.ac.gov.br/", None, SEM_ROTA),
    ("AL", "Diário Oficial de Alagoas", "https://diario.imprensaoficial.al.gov.br/", None, SEM_ROTA),
    ("AM", "Diário Oficial do Amazonas", "https://diario.imprensaoficial.am.gov.br/", None, SEM_ROTA),
    ("AP", "Diário Oficial do Amapá", "https://www.diario.ap.gov.br/", None, NAO_RESPONDE),
    ("BA", "Diário Oficial da Bahia", "https://dool.egba.ba.gov.br/", None, NAO_RESPONDE),
    ("CE", "Diário Oficial do Ceará", "http://imprensaoficial.ce.gov.br/", None, NAO_RESPONDE),
    ("DF", "Diário Oficial do Distrito Federal", "https://dodf.df.gov.br/", None, NAO_RESPONDE),
    ("ES", "Diário Oficial do Espírito Santo", "https://ioes.dio.es.gov.br", "dioe", None),
    ("GO", "Diário Oficial de Goiás", "https://diariooficial.abc.go.gov.br", "dioe", None),
    ("MA", "Diário Oficial do Maranhão", "https://www.diariooficial.ma.gov.br/", None, "o site do diário respondeu com erro 500"),
    ("MG", "Diário Oficial de Minas Gerais", "https://www.jornalminasgerais.mg.gov.br/", None, NAO_RESPONDE),
    ("MS", "Diário Oficial de Mato Grosso do Sul", "https://www.spdo.ms.gov.br/diariodoe", None, NAO_RESPONDE),
    ("MT", "Diário Oficial de Mato Grosso", "https://www.iomat.mt.gov.br", "dioe", None),
    ("PA", "Diário Oficial do Pará", "http://www.ioepa.com.br/", None, SEM_ROTA),
    ("PB", "Diário Oficial da Paraíba", "https://auniao.pb.gov.br/", None, SEM_ROTA),
    ("PE", "Diário Oficial de Pernambuco", "https://diariooficial.cepe.com.br/", None, SEM_ROTA),
    ("PI", "Diário Oficial do Piauí", "https://www.diario.pi.gov.br/", None, SEM_ROTA),
    ("PR", "Diário Oficial do Paraná", "https://www.documentos.dioe.pr.gov.br/", None, NAO_RESPONDE),
    ("RJ", "Diário Oficial do Rio de Janeiro", "https://www.ioerj.com.br/", None, SEM_ROTA),
    ("RN", "Diário Oficial do Rio Grande do Norte", "http://www.diariooficial.rn.gov.br/", None, "o endereço do diário devolveu 404"),
    ("RO", "Diário Oficial de Rondônia", "https://diof.ro.gov.br/", None, SEM_ROTA),
    ("RR", "Diário Oficial de Roraima", "https://www.imprensaoficial.rr.gov.br/", None, SEM_ROTA),
    ("RS", "Diário Oficial do Rio Grande do Sul", "https://www.diariooficial.rs.gov.br/", None, SEM_ROTA),
    ("SC", "Diário Oficial de Santa Catarina", "https://portal.doe.sea.sc.gov.br/", None, SEM_ROTA),
    ("SE", "Diário Oficial de Sergipe", "https://www.segrase.se.gov.br/", None, NAO_RESPONDE),
    ("SP", "Diário Oficial do Estado de São Paulo", "https://doe.sp.gov.br", "sp", None),
    ("TO", "Diário Oficial do Tocantins", "https://diariooficial.to.gov.br/", None, NAO_RESPONDE),
]
REG = {r[0]: r for r in REGISTRO}
SP_API = "https://do-api-web-search.doe.sp.gov.br/v2/advanced-search/publications"
MAX_DETALHES_SP = 400  # textos completos lidos por coleta (só aberturas e processos seletivos)


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _get(cli, url, tentativas=4, **kw):
    """Até 4 tentativas com espera crescente em 429/5xx e falhas de rede; a última resposta (ou exceção) volta para quem chamou."""
    for t in range(tentativas):
        try:
            r = cli.get(url, **kw)
            if r.status_code in (429, 500, 502, 503, 504, 520, 522) and t < tentativas - 1:
                time.sleep(min(30, 3 * 2 ** t))
                continue
            return r
        except httpx.HTTPError:
            if t == tentativas - 1:
                raise
            time.sleep(min(30, 3 * 2 ** t))


def _chave(*partes) -> str:
    return hashlib.sha1("|".join(str(p) for p in partes).encode()).hexdigest()[:24]


_NAO_EDITAL = re.compile(r"^\s*(ORDEM DO DIA|ATA D[AE]|PAUTA|EXTRATO DE CONTRATO|AVISO DE LICITA|DESPACHO)", re.I)
_MUNICIPAL = re.compile(r"prefeitura municipal|munic[ií]pio de [A-ZÁ-Úa-zá-ú]|c[aâ]mara municipal|secretaria municipal", re.I)


def montar_ato(uf: str, titulo: str, texto: str, publicado: str | None, url: str, fonte: str) -> dict:
    """Um ato com os campos padrão; o que não está escrito fica de fora e `incompleto` lista o que faltou."""
    ato = "outro" if _NAO_EDITAL.search(titulo) else classificar_ato(f"{titulo} {texto[:600]}")
    d = {"titulo": titulo[:300], "orgao": _orgao(titulo, texto), "esfera": "municipal" if _MUNICIPAL.search(texto[:800]) else "estadual",
         "uf": uf, "ato": ato, "tipo": "Processo seletivo" if re.search(r"processo seletivo", f"{titulo} {texto[:800]}", re.I) else "Concurso público",
         "area": area_concurso(f"{titulo} {texto[:3000]}"), "publicado": publicado, "coletado_em": _agora(), "resumo": texto[:500],
         "url": url, "fonte": fonte}
    if ato == "abertura":
        d.update(detalhes_edital(texto))
        d["incompleto"] = [c for c in ("vagas", "salario_max", "inscricoes_fim") if c not in d]
    return d


def _orgao(titulo: str, texto: str) -> str | None:
    m = re.search(r"(SECRETARIA DE ESTADO D[AOE] [A-ZÁ-Ú ,]{3,80}|POL[IÍ]CIA (?:CIVIL|MILITAR|PENAL)[A-ZÁ-Ú ]{0,40}|CORPO DE BOMBEIROS[A-ZÁ-Ú ]{0,40}|"
                  r"UNIVERSIDADE [A-ZÁ-Ú ]{3,80}|TRIBUNAL [A-ZÁ-Ú ]{3,80}|DEFENSORIA [A-ZÁ-Ú ]{3,60}|MINIST[EÉ]RIO P[UÚ]BLICO[A-ZÁ-Ú ]{0,60}|"
                  r"PREFEITURA MUNICIPAL DE [A-ZÁ-Ú ]{3,40}|ASSEMBLEIA LEGISLATIVA[A-ZÁ-Ú ]{0,40}|DEPARTAMENTO [A-ZÁ-Ú ]{3,60})", f"{titulo} {texto[:1500]}")
    return re.sub(r"\s+", " ", m.group(1)).strip().title() if m else None


# ---------------------------------------------------------------------------------------------------- adaptadores
def ler_sp(cli, ini: date, fim: date, max_paginas: int = 30) -> list[dict]:
    """Imprensa Oficial de SP: publicações com o termo no período (título + trecho + link)."""
    vistos, out, detalhes = set(), [], 0
    for termo in TERMOS:
        for pag in range(1, max_paginas + 1):
            r = _get(cli, SP_API, params={"Terms[0]": termo.strip('"'), "FromDate": ini.isoformat(), "ToDate": fim.isoformat(),
                                         "PageNumber": pag, "PageSize": 100})
            r.raise_for_status()
            itens = (r.json() or {}).get("items") or []
            for it in itens:
                if it.get("id") in vistos:
                    continue
                vistos.add(it.get("id"))
                ato = montar_ato("SP", _limpa(it.get("title")), _limpa(it.get("excerpt")), (it.get("date") or "")[:10],
                                 f"https://doe.sp.gov.br/{it.get('slug')}", "Diário Oficial do Estado de São Paulo")
                hier = [p.strip() for p in str(it.get("hierarchy") or "").split(">") if p.strip()]
                if hier:
                    ato["orgao"] = hier[2] if len(hier) > 2 else hier[-1]
                    ato["unidade"] = hier[-1]
                candidato = ato["ato"] in ("abertura", "processo_seletivo") or (
                    ato["ato"] == "outro" and re.search(r"edital|abertura|concurso|processo seletivo", ato["titulo"], re.I))
                if candidato and not _NAO_EDITAL.search(ato["titulo"]) and detalhes < MAX_DETALHES_SP:
                    detalhes += 1
                    try:  # texto inteiro do edital: vagas, salário e datas só se estiverem escritos
                        dd = _get(cli, f"{SP_API.rsplit('/advanced-search', 1)[0]}/publications/{it.get('id')}").json()
                        texto = _limpa(dd.get("content"))
                        ato["ato"] = classificar_ato(f"{ato['titulo']} {texto[:1500]}")
                        if ato["ato"] in ("abertura", "processo_seletivo"):
                            ato.update(detalhes_edital(texto))
                        ato["area"] = area_concurso(f"{ato['titulo']} {ato.get('orgao') or ''} {texto[:3000]}")
                        ato["resumo"] = texto[:500] or ato["resumo"]
                        ato["incompleto"] = [c for c in ("vagas", "salario_max", "inscricoes_fim") if c not in ato]
                    except Exception as e:  # noqa: BLE001 - fica o trecho da busca, marcado incompleto
                        ato["aviso"] = f"texto completo não lido ({type(e).__name__})"
                out.append(ato | {"_id": it.get("id")})
            if len(itens) < 100:
                break
    return out


_CABECALHO = re.compile(r"\b(EDITAL|PORTARIA|AVISO|EXTRATO|RESOLU[ÇC][ÃA]O|DECRETO|ATO)\b[^\n.]{0,140}")
_TERMO = re.compile(r"concurso p[uú]blico|processo seletivo", re.I)


def atos_da_pagina(texto: str) -> list[tuple[str, str]]:
    """Corta o texto de uma página do diário em trechos em volta de cada menção a concurso/processo seletivo: (título, trecho)."""
    out, ultimo = [], -10**9
    for m in _TERMO.finditer(texto):
        if m.start() - ultimo < 1200:  # mesma publicação
            continue
        ultimo = m.start()
        ini = max(0, m.start() - 500)
        cab = None
        for c in _CABECALHO.finditer(texto, ini, m.start() + 1):
            cab = c
        if cab:
            ini = cab.start()
        trecho = texto[ini:m.start() + 1800]
        out.append(((cab.group(0) if cab else trecho[:120]).strip(), trecho))
    return out


def ler_dioe(cli, base: str, uf: str, nome: str, ini: date, fim: date, max_paginas: int = 40) -> list[dict]:
    """Plataforma comum (MT, ES, GO): páginas do diário que citam o termo; cada página vira um ou mais atos."""
    out, vistos = [], set()
    for termo in TERMOS:
        for pag in range(0, max_paginas):
            url = f"{base}/busca/busca/buscar/query/{pag}/di:{ini.isoformat()}/df:{fim.isoformat()}/"
            r = _get(cli, url, params={"1": 1, "q": termo})
            r.raise_for_status()
            hits = ((r.json() or {}).get("hits") or {}).get("hits") or []
            for h in hits:
                s = h.get("_source") or {}
                pk = (s.get("diario_id"), s.get("pagina"))
                if pk in vistos:
                    continue
                vistos.add(pk)
                texto = re.sub(r"\s+", " ", s.get("conteudo") or "")
                link = f"{base}/portal/edicoes/download/{s.get('diario_id')}/{s.get('pagina')}"
                for titulo, trecho in atos_da_pagina(texto):
                    out.append(montar_ato(uf, titulo, trecho, s.get("data"), link, nome) | {"_id": f"{pk[0]}-{pk[1]}-{_chave(trecho[:200])}"})
            if len(hits) < 10:
                break
    return out


ADAPTADORES = {"sp": lambda cli, reg, ini, fim: ler_sp(cli, ini, fim),
               "dioe": lambda cli, reg, ini, fim: ler_dioe(cli, reg[2], reg[0], reg[1], ini, fim)}


def _status(db, uf: str) -> dict:
    r = db.query(Registro).filter_by(fonte="doe", tipo="concurso_uf_status", chave=uf).one_or_none()
    return dict(r.dados or {}) if r else {}


def coletar_estado(db, cli, uf: str, dias: int = 15) -> dict:
    """Coleta um estado e grava os atos + a situação. Nunca apaga atos já gravados."""
    reg = REG[uf]
    antes = _status(db, uf)
    st = {"uf": uf, "diario": reg[1], "url": reg[2], "ultima_tentativa": _agora(), "ultima_sucesso": antes.get("ultima_sucesso"),
          "itens_ultima_sucesso": antes.get("itens_ultima_sucesso"), "historico": (antes.get("historico") or [])[-19:]}
    if not reg[3]:
        st.update(status="sem_coletor", motivo=reg[4], itens=0)
    else:
        fim = date.today()
        ini = fim - timedelta(days=int(dias))
        try:
            atos = ADAPTADORES[reg[3]](cli, reg, ini, fim)
            for a in atos:
                pk = a.pop("_id")
                velho = db.query(Registro).filter_by(fonte=f"doe_{uf.lower()}", tipo="concurso", chave=str(pk)).one_or_none()
                if velho and (velho.dados or {}).get("primeira_coleta"):
                    a["primeira_coleta"] = velho.dados["primeira_coleta"]
                a.setdefault("primeira_coleta", a["coletado_em"])
                upsert(db, Registro, {"fonte": f"doe_{uf.lower()}", "tipo": "concurso", "chave": str(pk)},
                       {"titulo": a["titulo"], "uf": uf, "ano": int(a["publicado"][:4]) if a.get("publicado") else None,
                        "valor": a.get("salario_max"), "dados": a})
            st.update(status="ok", itens=len(atos), ultima_sucesso=st["ultima_tentativa"], itens_ultima_sucesso=len(atos),
                      periodo={"de": ini.isoformat(), "ate": fim.isoformat()}, erro=None)
        except Exception as e:  # noqa: BLE001 - um estado não derruba os outros
            st.update(status="indisponivel" if isinstance(e, (httpx.HTTPError,)) or "50" in str(e)[:4] else "erro",
                      erro=f"{type(e).__name__}: {str(e)[:200]}", itens=0)
    st["historico"].append({"quando": st["ultima_tentativa"], "status": st["status"], "itens": st.get("itens", 0), "erro": st.get("erro")})
    upsert(db, Registro, {"fonte": "doe", "tipo": "concurso_uf_status", "chave": uf},
           {"titulo": f"Concursos — {reg[1]}", "uf": uf, "valor": float(st.get("itens") or 0), "dados": st})
    db.commit()
    return st


def coletar_concursos_estaduais(ufs: str | None = None, dias: int = 15):
    if isinstance(ufs, (list, tuple)):
        ufs = ",".join(map(str, ufs))
    lista = [u.strip().strip("[]'\" ").upper() for u in str(ufs).split(",") if u.strip()] if ufs else [r[0] for r in REGISTRO]
    with registrar_coleta("oportunidades", "concursos_estaduais", ufs=",".join(lista), dias=dias) as (db, n), \
            httpx.Client(headers=UA, timeout=60, follow_redirects=True) as cli:
        for uf in lista:
            if uf not in REG:
                n.avisos.append(f"{uf}: UF desconhecida")
                continue
            st = coletar_estado(db, cli, uf, dias)
            n += st.get("itens") or 0
            if st["status"] in ("indisponivel", "erro"):
                n.avisos.append(f"{uf}: {st['erro']}")
    return n.itens
