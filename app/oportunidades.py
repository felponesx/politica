"""Concursos, cursos gratuitos e eventos pagos com dinheiro público: leitura dos registros gravados por
app/collectors/oportunidades.py (tarefas concursos, cursos-gratuitos, eventos-shows, eventos-patrocinios)."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Coleta, Registro
from app.utils import UFS

AVISO_CONCURSOS = ("Lista montada a partir dos diários oficiais: Diário Oficial da União (órgãos federais, Câmara, Senado, tribunais, "
                   "universidades, conselhos) e, quando o serviço está no ar, os diários das prefeituras (Querido Diário). Concursos de "
                   "governos estaduais (como delegado da Polícia Civil) saem nos diários de cada estado e ainda não entram. Vagas, salário e "
                   "datas aparecem só quando estão escritos no texto do edital; confira sempre o edital oficial pelo link.")
AVISO_CURSOS = ("Só cursos gratuitos: Escola Virtual.Gov (Enap, governo federal; todos gratuitos e com certificado) e Sebrae (só os de "
                "preço zero na loja do Sebrae). Senai, Senac, Sesi e os cursos dos CRAS e das prefeituras não publicam catálogo aberto "
                "que dê para ler automaticamente: veja os links de onde procurar.")
ONDE_PROCURAR = [
    {"nome": "Senai — cursos gratuitos", "url": "https://www.portaldaindustria.com.br/senai/", "obs": "Cada estado tem seu catálogo; muitos cursos técnicos e de qualificação são gratuitos."},
    {"nome": "Senac — Programa Senac de Gratuidade (PSG)", "url": "https://www.senac.br/", "obs": "Vagas gratuitas para quem tem renda familiar de até 2 salários mínimos por pessoa."},
    {"nome": "Sesi", "url": "https://www.portaldaindustria.com.br/sesi/", "obs": "Educação básica e cursos para trabalhadores da indústria e dependentes."},
    {"nome": "CRAS da sua cidade", "url": "https://aplicacoes.mds.gov.br/sagi/cras/", "obs": "Cursos e oficinas gratuitas do serviço de assistência social do município."},
    {"nome": "Pronatec / Novos Caminhos (MEC)", "url": "https://www.gov.br/mec/pt-br/novos-caminhos", "obs": "Cursos técnicos e de qualificação gratuitos em institutos federais e redes estaduais."},
]
AVISO_EVENTOS = ("Contratações de eventos publicadas no Portal Nacional de Contratações Públicas (PNCP) por prefeituras, governos estaduais e "
                 "órgãos federais: cachês de artistas (inexigibilidade, Lei 14.133, art. 74, II) e, quando coletados, palco, som, iluminação, "
                 "segurança, estrutura e produção. A soma só leva o valor HOMOLOGADO de contratações distintas: valor só estimado, teto de ata "
                 "de registro de preços e possíveis republicações do mesmo contrato ficam fora da soma (mostrados à parte). Contrato com vários "
                 "itens (palco + som, por exemplo) não é dividido. Artista, festa e data só quando escritos no objeto. Contratação publicada "
                 "não prova que o evento aconteceu nem indica irregularidade.")
AVISO_PATROCINIO = ("Patrocínio de festa da prefeitura por empresas não é publicado em base aberta. O que existe é a Lei Rouanet: "
                    "projetos culturais (festivais, festas, feiras, shows) e as empresas que patrocinaram, com abatimento no imposto de renda "
                    "(sistema SALIC do Ministério da Cultura). Pessoas físicas aparecem só somadas, sem nome.")


def _dados(db: Session, tipo: str, fontes: tuple[str, ...] | None = None) -> list[dict]:
    q = select(Registro.dados).where(Registro.tipo == tipo)
    if fontes:
        q = q.where(Registro.fonte.in_(fontes))
    return [d for (d,) in db.execute(q) if d]


def _ultima(db: Session, tarefa: str) -> dict | None:
    c = db.execute(select(Coleta).where(Coleta.fonte == "oportunidades", Coleta.tarefa == tarefa, Coleta.status.in_(("ok", "parcial")))
                   .order_by(Coleta.id.desc()).limit(1)).scalar_one_or_none()
    if not c:
        return None
    return {"quando": (c.fim or c.inicio).isoformat() if (c.fim or c.inicio) else None, "status": c.status, "aviso": c.erro}


ABERTURAS = ("abertura", "processo_seletivo")
_CAMPOS_CONC = ("titulo", "orgao", "unidade", "vinculo", "esfera", "uf", "municipio", "tipo", "ato", "area", "publicado", "coletado_em", "url", "fonte",
                "vagas", "salario_max", "inscricoes_inicio", "inscricoes_fim", "cargos", "banca", "escolaridade", "resumo", "incompleto", "trecho_apenas")


def _situacao(x: dict, hoje: str) -> str:
    if x.get("inscricoes_fim") and x["inscricoes_fim"] < hoje:
        return "inscrições encerradas"
    if x.get("inscricoes_inicio") and x["inscricoes_inicio"] <= hoje <= (x.get("inscricoes_fim") or hoje):
        return "inscrições abertas"
    if x.get("inscricoes_inicio") and x["inscricoes_inicio"] > hoje:
        return "inscrições ainda não começaram"
    return "ver edital"


def cobertura_concursos(db: Session) -> dict:
    """Situação de cada fonte: 27 estados (coletor, última coleta boa, erro) e os diários das prefeituras (Querido Diário)."""
    estados = {}
    for r in db.execute(select(Registro.chave, Registro.dados).where(Registro.fonte == "doe", Registro.tipo == "concurso_uf_status")):
        d = r.dados or {}
        estados[r.chave] = {k: d.get(k) for k in ("diario", "url", "status", "motivo", "erro", "ultima_tentativa", "ultima_sucesso", "itens_ultima_sucesso")}
    qd = db.execute(select(Registro.dados).where(Registro.fonte == "querido_diario", Registro.tipo == "concursos_status")).scalar_one_or_none() or {}
    cob = db.execute(select(Registro.dados).where(Registro.fonte == "querido_diario", Registro.tipo == "cobertura")).scalar_one_or_none() or {}
    return {"estados": estados, "estados_com_coletor": sum(1 for e in estados.values() if e.get("status") != "sem_coletor"),
            "municipios": {k: qd.get(k) for k in ("status", "erro", "quando", "ultima_sucesso", "itens_ultima_sucesso")} | {
                "monitorados": cob.get("monitorados"), "sem_cobertura": cob.get("sem_cobertura"), "cobertura_em": cob.get("quando")},
            "aviso": "Estado sem coletor ou fonte fora do ar não quer dizer que não há concurso: quer dizer que ainda não conseguimos ler."}


def concursos(db: Session, dias: int = 120, ato: str | None = None) -> dict | None:
    """Sem `ato`: editais de abertura e processos seletivos. Com `ato` (convocacao, nomeacao, homologacao, retificacao, prorrogacao):
    só aquele tipo. Atos "outro" (menções de passagem) ficam guardados e não aparecem."""
    from app.collectors.oportunidades import ATOS
    hoje = date.today().isoformat()
    corte = (date.today() - timedelta(days=dias)).isoformat()
    itens, contagem = [], defaultdict(int)
    for d in _dados(db, "concurso"):
        if (d.get("publicado") or "") < corte:
            continue
        a = d.get("ato") or "abertura"  # o DOU só grava aberturas
        if a == "outro":
            continue
        contagem[a] += 1
        if (ato and a != ato) or (not ato and a not in ABERTURAS):
            continue
        x = {k: d.get(k) for k in _CAMPOS_CONC}
        x["ato"] = a
        x["ato_nome"] = ATOS.get(a, a)
        x["situacao"] = _situacao(x, hoje)
        if x.get("resumo"):
            x["resumo"] = x["resumo"][:300]
        itens.append({k: v for k, v in x.items() if v not in (None, [], "")})
    if not itens and not contagem:
        return None
    itens.sort(key=lambda x: x.get("publicado") or "", reverse=True)
    areas, esferas = defaultdict(int), defaultdict(int)
    for x in itens:
        areas[x.get("area") or "Outras áreas"] += 1
        esferas[x.get("esfera") or "?"] += 1
    return {"total": len(itens), "itens": itens, "areas": dict(sorted(areas.items(), key=lambda a: -a[1])), "esferas": dict(esferas),
            "atos": {k: {"nome": ATOS.get(k, k), "qtd": v} for k, v in sorted(contagem.items(), key=lambda a: -a[1])},
            "periodo_dias": dias, "coleta": _ultima(db, "concursos"), "cobertura": cobertura_concursos(db), "aviso": AVISO_CONCURSOS}


def cursos(db: Session) -> dict | None:
    itens = []
    for d in _dados(db, "curso"):
        x = {k: d.get(k) for k in ("nome", "ofertante", "quem_faz", "tema", "carga_horaria", "modalidade", "inscricoes_abertas", "certificado", "url", "resumo", "lancado")}
        if x.get("tema") and re.search(r"destaque|novidade|gratuit|mais vendid|lan[cç]amento|promo", x["tema"], re.I):
            x["tema"] = None
        if x.get("resumo"):
            x["resumo"] = x["resumo"][:140].rsplit(" ", 1)[0] + "…" if len(x["resumo"]) > 140 else x["resumo"]
        itens.append({k: v for k, v in x.items() if v not in (None, "")})
    if not itens:
        return None
    # os mais novos primeiro (a Escola Virtual informa o lançamento); sem data, em ordem alfabética
    itens.sort(key=lambda x: (not x.get("inscricoes_abertas", False), "" if x.get("lancado") else "1", "".join(chr(255 - ord(c)) for c in x.get("lancado") or ""), x.get("nome") or ""))
    temas, ofertantes = defaultdict(int), defaultdict(int)
    for x in itens:
        temas[x.get("tema") or "Outros"] += 1
        ofertantes[x.get("ofertante") or "?"] += 1
    return {"total": len(itens), "itens": itens, "temas": dict(sorted(temas.items(), key=lambda a: -a[1])), "ofertantes": dict(ofertantes),
            "onde_procurar": ONDE_PROCURAR, "coleta": _ultima(db, "cursos"), "aviso": AVISO_CURSOS}


_CAMPOS_EVENTO = ("artista", "evento", "data_evento", "municipio", "uf", "esfera", "orgao", "valor", "valor_tipo", "publicado", "url", "objeto",
                  "categoria", "registro_precos", "possivel_duplicata", "modalidade")
CATEGORIAS_NOME = {"cache": "Cachê artístico", "palco": "Palco", "som": "Som", "iluminacao": "Iluminação", "seguranca": "Segurança",
                   "estrutura": "Estrutura (tendas, banheiros, gradis, geradores…)", "producao": "Produção do evento",
                   "varios": "Vários itens no mesmo contrato"}


def _evento(d: dict, objeto: int = 160) -> dict:
    """Formato enxuto: o texto do contrato só quando o artista não foi lido; o órgão só quando a esfera não é conhecida."""
    x = {k: d.get(k) for k in _CAMPOS_EVENTO if k != "publicado"}
    if x.get("artista"):
        x.pop("objeto", None)
    elif x.get("objeto"):
        x["objeto"] = x["objeto"][:objeto]
    if x.get("esfera"):
        x.pop("orgao", None)
    if x.get("categoria") == "cache":
        x.pop("categoria", None)  # o padrão
    if not x.get("registro_precos"):
        x.pop("registro_precos", None)
    if valor_suspeito(d):
        x["valor_a_conferir"] = True
    if x.get("modalidade") == "Inexigibilidade":
        x.pop("modalidade", None)
    return {k: v for k, v in x.items() if v not in (None, "", False)}


def _marcar_duplicatas(todos: list[dict]) -> None:
    """Mesmo órgão, mesmo objeto e mesmo valor em registros diferentes do PNCP (republicação) contam uma vez só: os outros ficam
    `possivel_duplicata` e saem das somas (continuam na lista)."""
    vistos = {}
    for d in sorted(todos, key=lambda d: (d.get("publicado") or "", d.get("numero_controle") or "")):
        k = (d.get("cnpj_orgao") or d.get("orgao"), re.sub(r"\W+", " ", (d.get("objeto") or "").lower()).strip()[:200], round(float(d.get("valor") or 0), 2))
        if k[1] and k in vistos:
            d["possivel_duplicata"] = True
        else:
            vistos[k] = True


LIMITE_SUSPEITO = {"cache": 5e6}  # cachê acima de R$ 5 mi; qualquer outro tipo acima de R$ 50 mi
LIMITE_SUSPEITO_PADRAO = 50e6


def valor_suspeito(d: dict) -> bool:
    """Valor provavelmente digitado errado na fonte (ex.: camarote para 3 mil pessoas com R$ 399.990.000 no PNCP). Não é corrigido:
    aparece com "valor a conferir" e sai da soma."""
    v = float(d.get("valor") or 0)
    return v > LIMITE_SUSPEITO.get(d.get("categoria") or "cache", LIMITE_SUSPEITO_PADRAO)


def conta(d: dict) -> bool:
    """O valor entra na soma só se for contratação de fato: homologado, fora de ata de registro de preços, sem duplicata e sem valor a conferir."""
    return (d.get("valor_tipo") == "homologado" and d.get("registro_precos") is not True and not d.get("possivel_duplicata")
            and bool(d.get("valor")) and not valor_suspeito(d))


def _somas(sel: list[dict]) -> dict:
    cat = defaultdict(lambda: {"qtd": 0, "valor_contratado": 0.0})
    fora = {"estimado_sem_homologacao": 0.0, "registro_precos_teto": 0.0, "possiveis_duplicatas": 0.0, "valor_a_conferir": 0.0}
    for d in sel:
        c = cat[d.get("categoria") or "cache"]
        c["qtd"] += 1
        v = float(d.get("valor") or 0)
        if conta(d):
            c["valor_contratado"] += v
        elif valor_suspeito(d):
            fora["valor_a_conferir"] += v
        elif d.get("possivel_duplicata"):
            fora["possiveis_duplicatas"] += v
        elif d.get("registro_precos") is True:
            fora["registro_precos_teto"] += v
        else:
            fora["estimado_sem_homologacao"] += v
    return {"valor_total": round(sum(c["valor_contratado"] for c in cat.values()), 2),
            "por_categoria": {k: {"nome": CATEGORIAS_NOME.get(k, k), "qtd": v["qtd"], "valor_contratado": round(v["valor_contratado"], 2)} for k, v in cat.items()},
            "fora_da_soma": {k: round(v, 2) for k, v in fora.items()}}


def pendencias_pncp(db: Session) -> dict:
    pend = [d for (d,) in db.execute(select(Registro.dados).where(Registro.fonte == "pncp", Registro.tipo == "pncp_pendencia")) if d]
    abertas = [p for p in pend if not p.get("resolvida")]
    return {"abertas": len(abertas), "resolvidas": len(pend) - len(abertas), "dias_com_falha": sorted({p["dia"] for p in abertas})}


def eventos(db: Session, uf: str | None = None) -> dict | None:
    # sem categoria = o objeto não é contratação de evento (ex.: ECAD); continua guardado, mas não entra
    todos = [d for d in _dados(db, "evento_show", ("pncp",)) if d.get("categoria") or "categorias" not in d]
    if not todos:
        return None
    _marcar_duplicatas(todos)
    datas = sorted(d.get("publicado") for d in todos if d.get("publicado"))
    base = {"periodo": {"de": datas[0], "ate": datas[-1]} if datas else None, "coleta": _ultima(db, "eventos"), "aviso": AVISO_EVENTOS,
            "pendencias": pendencias_pncp(db), "categorias_nome": CATEGORIAS_NOME}
    if uf:
        sel = [d for d in todos if d.get("uf") == uf]
        cid = defaultdict(lambda: {"qtd": 0, "valor": 0.0})
        for d in sel:
            c = cid[d.get("municipio") or "(estado)"]
            c["qtd"] += 1
            c["valor"] += float(d.get("valor") or 0) if conta(d) else 0
        itens = sorted((_evento(d) for d in sel), key=lambda x: -(x.get("valor") or 0))
        return {**base, "uf": uf, "total": len(itens), **_somas(sel), "itens": itens,
                "cidades": sorted(({"municipio": k, **v} for k, v in cid.items()), key=lambda c: -c["valor"])}
    por_uf = {u: {"qtd": 0, "valor": 0.0} for u in UFS}
    por_esfera = defaultdict(lambda: {"qtd": 0, "valor": 0.0})
    cid = defaultdict(lambda: {"qtd": 0, "valor": 0.0})
    for d in todos:
        v = float(d.get("valor") or 0) if conta(d) else 0.0
        if d.get("uf") in por_uf:
            por_uf[d["uf"]]["qtd"] += 1
            por_uf[d["uf"]]["valor"] += v
        por_esfera[d.get("esfera") or "?"]["qtd"] += 1
        por_esfera[d.get("esfera") or "?"]["valor"] += v
        if d.get("municipio"):
            c = cid[(d["municipio"], d.get("uf"))]
            c["qtd"] += 1
            c["valor"] += v
    hoje = date.today().isoformat()
    proximos = sorted((d for d in todos if (d.get("data_evento") or "") >= hoje and (d.get("categoria") or "cache") == "cache"),
                      key=lambda d: d["data_evento"])[:60]
    return {**base, "total": len(todos), **_somas(todos), "com_artista": sum(1 for d in todos if d.get("artista")), "cidades_total": len(cid),
            "por_uf": por_uf, "por_esfera": dict(por_esfera),
            "maiores": [_evento(d) for d in sorted((d for d in todos if conta(d)), key=lambda d: -float(d.get("valor") or 0))[:60]],
            "proximos": [_evento(d) for d in proximos],
            "cidades": [{"municipio": k[0], "uf": k[1], **v} for k, v in sorted(cid.items(), key=lambda a: -a[1]["valor"])[:60]]}


def patrocinios(db: Session, uf: str | None = None) -> dict | None:
    ps = _dados(db, "patrocinio", ("salic",))
    if not ps:
        return None
    if uf:
        ps = [p for p in ps if p.get("uf") == uf or any(str(l).endswith("/" + uf) for l in p.get("locais") or [])]
    emp = defaultdict(lambda: {"valor": 0.0, "projetos": 0})
    for p in ps:
        for s in p.get("patrocinadores") or []:
            if s.get("cnpj"):
                e = emp[s["nome"]]
                e["valor"] += float(s.get("valor") or 0)
                e["projetos"] += 1
    ps.sort(key=lambda p: -float(p.get("captado") or 0))
    return {"uf": uf, "total": len(ps), "captado_total": round(sum(float(p.get("captado") or 0) for p in ps), 2),
            "projetos": [{**{k: v for k, v in p.items() if k not in ("fonte", "tipologia")}, "locais": (p.get("locais") or [])[:8],
                          "patrocinadores": (p.get("patrocinadores") or [])[:8]} for p in ps[:400]],
            "empresas": [{"nome": k, **v} for k, v in sorted(emp.items(), key=lambda a: -a[1]["valor"])[:40]],
            "coleta": _ultima(db, "patrocinios"), "aviso": AVISO_PATROCINIO}
