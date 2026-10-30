"""Ocorrências (marcos de investigações e processos) a partir dos casos curados de `app/dados/escandalos`.

Cada marco do caso (data, fato, fonte) vira uma ocorrência com: título, descrição objetiva, órgãos envolvidos, data, local (quando o marco o diz), fonte original (URL),
situação do caso na data da última verificação e a data dessa verificação. A ETAPA é classificada à parte — investigação, denúncia, condenação, absolvição ou
arquivamento — só quando o texto do marco diz isso com palavras claras; o que não se encaixa fica "outra" (nada é adivinhado). Marco sem URL de fonte é descartado
no carregamento do caso. Nenhuma suspeita vira fato: o aviso de presunção de inocência acompanha toda resposta."""
import re
from datetime import date

from app import escandalos

ETAPAS = {
    "absolvicao": re.compile(r"\babsolv|\binocente|\bsem provas?\b|\bnão há provas|\banulad[ao]s? (?:a )?(?:condena|sentença)|\btranc(?:a|ou|amento)\b", re.I),
    "arquivamento": re.compile(r"\barquiv|\bprescri|\bextin(?:ta|ção) da punibilidade", re.I),
    "condenacao": re.compile(r"\bcondena|\bsentença condenat|\bpena de \d|\bcondenad", re.I),
    "denuncia": re.compile(r"\bdenúncia|\bdenuncia|\bré[us]?\b|\brecebe(?:u)? a denúncia|\bação penal", re.I),
    "investigacao": re.compile(r"\binvestiga|\boperação\b|\binquérito|\bbusca e apreensão|\bpreso|\bprisão|\bindici|\bCPI\b|\bdeflagra", re.I),
}
ORDEM = ("absolvicao", "arquivamento", "condenacao", "denuncia", "investigacao")   # a etapa mais "final" que o texto menciona
ROTULO = {"investigacao": "Investigação", "denuncia": "Denúncia", "condenacao": "Condenação", "absolvicao": "Absolvição", "arquivamento": "Arquivamento", "outra": "Outra"}
LOCAL = re.compile(r"\b(STF|STJ|TSE|TCU|TRF-?\d|TJ-?[A-Z]{2}|PGR|MPF|PF|Câmara|Senado|CPI)\b")


def classificar(fato: str) -> str:
    for e in ORDEM:
        if ETAPAS[e].search(fato or ""):
            return e
    return "outra"


def todas() -> list[dict]:
    out = []
    for slug, c in escandalos.casos().items():
        sit = (c.get("situacao_atual") or {})
        for a in c.get("andamento") or []:
            fato = (a.get("fato") or "").strip()
            out.append({"caso": slug, "caso_nome": c["nome"], "titulo": f'{c["nome"]}: {fato.split(";")[0][:110]}', "descricao": fato, "data": a.get("data"),
                        "etapa": classificar(fato), "orgaos_do_caso": [o["nome"] for o in c.get("orgaos") or []][:6], "instancias_citadas": sorted(set(LOCAL.findall(fato))),
                        "fonte_url": a["fonte"], "situacao_atual_do_caso": sit.get("texto"), "situacao_data": sit.get("data"), "verificado_em": c.get("verificado_em")})
    out.sort(key=lambda x: str(x["data"] or ""), reverse=True)
    return out


def listar(etapa: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    itens = todas()
    contagem = {k: sum(1 for i in itens if i["etapa"] == k) for k in ROTULO}
    if etapa:
        itens = [i for i in itens if i["etapa"] == etapa]
    if q:
        t = q.lower()
        itens = [i for i in itens if t in (i["descricao"] + " " + i["caso_nome"]).lower()]
    return {"total": len(itens), "por_etapa": contagem, "ocorrencias": itens[offset:offset + limit], "rotulos": ROTULO, "aviso": escandalos.AVISO,
            "criterio": "A etapa é classificada pelas palavras do próprio marco (ex.: 'condenado', 'arquiva', 'denúncia', 'operação'); sem palavra clara, a etapa é 'outra'. "
                        "Cada ocorrência vem de um caso curado, com URL da fonte original.", "hoje": date.today().isoformat()}
