"""Votos de cada ministro do STJ, pelo texto oficial do acórdão (tarefa stj-votos).

Fonte: Portal de Dados Abertos do STJ (dadosabertos.web.stj.jus.br), conjuntos "Espelhos de Acórdãos" de cada órgão julgador
(Corte Especial, 3 Seções e 6 Turmas): um JSON por mês com os acórdãos que a Secretaria de Jurisprudência tratou. O campo
`decisao` é a certidão do julgamento: "por unanimidade/por maioria, ... nos termos do voto do Relator. Os Srs. Ministros A, B e C
votaram com o Sr. Ministro Relator. Votou vencido o Sr. Ministro D. Ausente, justificadamente, o Sr. Ministro E."

Regras:
- Só entra a posição ESCRITA na certidão: acompanhou o relator/condutor, vencido (ou vencido em parte), ausente, impedido ou
  suspeito, não participou, relator, relator do acórdão. Quem não aparece fica sem registro — nunca vira voto a favor ou contra.
- O resultado do colegiado (unanimidade/maioria e o que se decidiu) é guardado à parte da posição de cada ministro.
- O espelho não cobre todos os acórdãos do tribunal: só os que a Secretaria de Jurisprudência escolhe tratar (novidade de tese,
  representatividade do relator ou do órgão). Contagens são "nos acórdãos publicados como espelho", não "em todos os julgamentos".
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

import httpx

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.stj")

CKAN = "https://dadosabertos.web.stj.jus.br/api/3/action/package_show?id={}"
PAGINA = "https://dadosabertos.web.stj.jus.br/dataset/{}"
ORGAOS = {
    "espelhos-de-acordaos-corte-especial": "Corte Especial",
    "espelhos-de-acordaos-primeira-secao": "Primeira Seção", "espelhos-de-acordaos-segunda-secao": "Segunda Seção",
    "espelhos-de-acordaos-terceira-secao": "Terceira Seção",
    "espelhos-de-acordaos-primeira-turma": "Primeira Turma", "espelhos-de-acordaos-segunda-turma": "Segunda Turma",
    "espelhos-de-acordaos-terceira-turma": "Terceira Turma", "espelhos-de-acordaos-quarta-turma": "Quarta Turma",
    "espelhos-de-acordaos-quinta-turma": "Quinta Turma", "espelhos-de-acordaos-sexta-turma": "Sexta Turma",
}
POSICOES = {
    "relator": "Relator", "relator_acordao": "Redigiu o acórdão (voto vencedor)", "acompanhou": "Votou com o relator ou com o voto vencedor",
    "vencido": "Vencido", "vencido_parte": "Vencido em parte", "ausente": "Ausente", "impedido": "Impedido ou suspeito",
    "nao_participou": "Não participou",
    "participou_unanime": "Participou de decisão unânime", "participou": "Participou (a certidão não descreve o voto)",
}
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)"}

_TRAT = r"(?:o|a|os|as)\s+(?:Exm[oa]s?\.\s+)?(?:Srs?|Sras?)\.\s+(?:Ministr[oa]s?|Desembargador(?:es|as?)?(?:\s+Convocad[oa]s?)?(?:\s+do\s+\w+)?)"
_PARE = r"(?!(?:Presidiu|Ausente|Ausentes|Votaram|Votou|Vencid[oa]s?|Os|As|O|A|Não|Nao|Participaram|Impedid[oa]|Sustenta\w*|Afirmou|Declarou|Convocad[oa]s?)\b)"
_NOME = re.compile(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zà-ÿ'A-ZÁÉÍÓÚÂÊÔÃÕÇ]*(?:\s+(?:(?:de|da|do|dos|das)\s+)?" + _PARE + r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zà-ÿ'A-ZÁÉÍÓÚÂÊÔÃÕÇ]*){0,5}")
_FIM = r"(?<!\bSr)(?<!\bSra)(?<!\bSrs)(?<!\bSras)(?=\.\s|\.$|;)"


def chave_nome(nome: str) -> str:
    t = unicodedata.normalize("NFD", re.sub(r"\(.*?\)", "", nome or ""))
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).strip().upper()


def _lista(txt: str) -> list[str]:
    txt = re.split(r",?\s+(?:que|quanto|por|nos termos|com ressalva)\b", re.sub(r"\s*\((?:[^)]*)\)", "", txt))[0]  # "(Presidente)", "(Desembargador convocado ...)"
    partes = re.split(r",\s*|\s+e\s+", txt.strip().rstrip("."))
    out = []
    for p in partes:
        p = re.sub(r"^(?:(?:o|a|os|as)\s+)?(?:(?:Srs?|Sras?)\.\s+)?(?:Ministr[oa]s?\s+)?", "", p.strip())
        m = _NOME.match(p)  # só o nome: palavras com maiúscula (e de/da/do/dos/das no meio), no máximo 6
        if m and len(m.group(0)) > 3 and not re.search(r"\b(?:Relator|Relatora|Presidente|Ministr[oa]s?|Convocad[oa]s?)\b", m.group(0), re.I):
            out.append(m.group(0))
    return out


def ler_decisao(texto: str, relator: str | None) -> dict:
    """Resultado do colegiado e posição de cada ministro citada na certidão. Nada é inferido de quem não aparece."""
    t = re.sub(r"\.(?=[A-ZÁÉÍÓÚ])", ". ", re.sub(r"\s+", " ", texto or "").strip())
    res = "unanimidade" if re.search(r"por unanimidade", t, re.I) else "maioria" if re.search(r"por maioria", t, re.I) else None
    m = re.search(r"por (?:unanimidade|maioria),\s*(.+?)(?:,\s*nos termos d|\.\s)", t, re.I)
    dispositivo = m.group(1).strip() if m else None
    pos: dict[str, str] = {}
    grafias: dict[str, str] = {}

    def marca(nomes, p):
        for n in nomes:
            k = chave_nome(n)
            if k and not n.isupper():
                grafias.setdefault(k, n)
            if k and k not in pos:
                pos[k] = p

    condutor = None
    m = re.search(r"nos termos do voto d[oa] (?:Sr\.|Sra\.)\s+Ministr[oa]\s+(.+?),\s+que lavrar", t)
    if m:
        condutor = m.group(1)
        marca([condutor], "relator_acordao")
    # vencidos primeiro (um relator vencido continua "vencido", não "relator")
    parte = r"(?:\s+(?:em\s+parte|parcialmente))?"
    for m in re.finditer(r"(?:Votaram vencid[oa]s|Vencid[oa]s)" + parte + r",?\s+" + _TRAT + r"\s+(.+?)" + _FIM, t):
        marca(_lista(m.group(1)), "vencido_parte" if re.search("parte|parcial", m.group(0)) else "vencido")
    for m in re.finditer(r"(?:Votou vencid[oa]|Vencid[oa])" + parte + r",?\s+" + _TRAT + r"\s+(.+?)" + _FIM, t):
        marca(_lista(m.group(1)), "vencido_parte" if re.search("parte|parcial", m.group(0)) else "vencido")
    if relator:
        marca([relator], "relator")
    for m in re.finditer(r"(?:Os|As|O|A)\s+(?:Srs?|Sras?)\.\s+Ministr[oa]s?\s+(.+?)\s+vot(?:aram|ou)\s+com\s+(?:o|a)\s+(?:Sr|Sra)\.\s+Ministr[oa]" + r"[^.]*?" + _FIM, t):
        marca(_lista(m.group(1)), "acompanhou")
    for m in re.finditer(r"Vot(?:aram|ou)\s+com\s+(?:o|a)\s+(?:Sr|Sra)\.\s+Ministr[oa]\s+[^,]+?\s+" + _TRAT + r"\s+(.+?)" + _FIM, t):
        marca(_lista(m.group(1)), "acompanhou")
    for m in re.finditer(r"Ausentes?,?\s+(?:justificadamente,?\s+)?(?:nest[ae]\s+julgamento,?\s+)?" + _TRAT + r"\s+(.+?)" + _FIM, t):
        marca(_lista(m.group(1)), "ausente")
    for m in re.finditer(r"N[ãa]o\s+particip(?:aram|ou)\s+do\s+julgamento,?\s+" + _TRAT + r"\s+(.+?)" + _FIM, t):
        marca(_lista(m.group(1)), "nao_participou")
    for m in re.finditer(r"(?:Afirm(?:ou|aram)\s+(?:suspei[çc][ãa]o|impedimento)|Declar(?:ou|aram)-se\s+(?:impedid|suspeit)[oa]s?|Impedid[oa]s?|Suspeit[oa]s?)"
                         r",?\s+(?:para\s+o\s+julgamento,?\s+)?" + _TRAT + r"\s+(.+?)" + _FIM, t):
        marca(_lista(m.group(1)), "impedido")
    # "Participaram do julgamento ...": a certidão só lista quem participou. Em decisão unânime, todos votaram no mesmo sentido;
    # em decisão por maioria, quem não foi nomeado vencido fica "participou" (o voto não é deduzido por exclusão).
    for m in re.finditer(r"Particip(?:aram|ou)\s+do\s+julgamento,?\s+" + _TRAT + r"\s+(.+?)" + _FIM, t):
        marca(_lista(m.group(1)), "participou_unanime" if res == "unanimidade" else "participou")
    m = re.search(r"Presidiu o julgamento (?:o Sr\.|a Sra\.)\s+Ministr[oa]\s+(.+?)" + _FIM, t)
    presidente = m.group(1) if m and "Presidente do STJ" not in m.group(1) else None
    return {"resultado": res, "dispositivo": dispositivo, "posicoes": pos, "presidiu": presidente, "grafias": grafias}


def _nome_bonito(texto: str, chave: str, relator_campo: str | None) -> str:
    """Nome como aparece escrito na certidão (com maiúsculas e acentos); o campo do relator vem todo em maiúsculas."""
    for m in re.finditer(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ'.]*(?:\s+(?:de|da|do|dos|das|e)?\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ÿ'.]*)+", " ".join((texto or "").split())):
        if chave_nome(m.group(0)) == chave and not m.group(0).isupper():
            return m.group(0)
    return re.sub(r"\s*\(.*?\)", "", relator_campo or chave).strip().title().replace(" De ", " de ").replace(" Da ", " da ").replace(" Do ", " do ").replace(" Dos ", " dos ")


def unir_apelidos(chaves) -> dict[str, str]:
    """{chave curta: chave longa} quando o nome curto é um trecho seguido de UM único nome mais longo
    ("MARLUCE CALDAS" → "MARIA MARLUCE CALDAS", "ROGERIO SCHIETTI" → "ROGERIO SCHIETTI CRUZ"). Na dúvida (dois candidatos), não une."""
    out = {}
    for k in chaves:
        cand = [o for o in chaves if o != k and len(o.split()) <= 5 and (o.startswith(k + " ") or o.endswith(" " + k))]
        if len(cand) == 1 and len(k.split()) >= 2:
            out[k] = cand[0]
    return out


def recursos(cli: httpx.Client, pacote: str, meses: int) -> list[dict]:
    r = cli.get(CKAN.format(pacote), timeout=60)
    r.raise_for_status()
    js = sorted((x for x in r.json()["result"]["resources"] if (x.get("format") or "").upper() == "JSON" and re.match(r"\d{8}\.json$", x.get("name") or "")),
                key=lambda x: x["name"])
    return js[-meses:]


def separar_grudados(freq: dict[str, int]) -> dict[str, list[str]]:
    """Nomes que a certidão grudou sem vírgula ("OG FERNANDES ROGERIO SCHIETTI CRUZ") → os dois ministros conhecidos que o formam.
    Só separa quando as duas partes já aparecem sozinhas e mais vezes que o nome grudado."""
    out = {}
    for k, q in freq.items():
        w = k.split()
        for i in range(1, len(w)):
            a, b = " ".join(w[:i]), " ".join(w[i:])
            if freq.get(a, 0) > q and freq.get(b, 0) > q:
                out[k] = [a, b]
                break
    return out


def unir_chaves(freq: dict[str, int]) -> dict[str, list[str]]:
    """{chave lida: [chaves finais]}: separa nomes grudados e une apelidos ao nome completo (só se o completo aparece mais)."""
    grud = separar_grudados(freq)
    limpas = {k: q for k, q in freq.items() if k not in grud}
    for partes in grud.values():
        for p in partes:
            limpas[p] = limpas.get(p, 0)
    ap = {c: lg for c, lg in unir_apelidos(list(limpas)).items() if limpas.get(lg, 0) >= limpas.get(c, 0)}
    fim = lambda k: fim(ap[k]) if k in ap else k  # noqa: E731
    out = {k: [fim(k)] for k in limpas}
    out.update({k: [fim(p) for p in partes] for k, partes in grud.items()})
    return out


def coletar_stj_votos(meses: int = 12):
    """Posição de cada ministro nos acórdãos dos últimos `meses` meses publicados como espelho, por órgão julgador."""
    meses = int(meses)
    with registrar_coleta("stj", "votos", meses=meses) as (db, n), httpx.Client(headers=UA, follow_redirects=True) as cli:
        vistos: set[str] = set()
        lidos = []  # (órgão, resultado, {chave: posição}, metadados se por maioria)
        orgaos: dict = {}
        freq: dict[str, int] = {}
        bonito: dict[str, str] = {}
        periodo = [None, None]
        for pacote, orgao in ORGAOS.items():
            try:
                res = recursos(cli, pacote, meses)
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"{orgao}: lista de arquivos não abriu ({type(e).__name__})")
                continue
            o = orgaos.setdefault(orgao, {"acordaos": 0, "unanimidade": 0, "maioria": 0, "sem_resultado": 0, "arquivos": [], "pagina": PAGINA.format(pacote)})
            for x in res:
                try:
                    r = cli.get(x["url"], timeout=180)
                    r.raise_for_status()
                    itens = r.json()
                except Exception as e:  # noqa: BLE001
                    n.avisos.append(f"{orgao} {x['name']}: {type(e).__name__}")
                    continue
                o["arquivos"].append(x["name"][:8])
                for a in itens:
                    aid = str(a.get("id") or "")
                    if not aid or aid in vistos or (a.get("tipoDeDecisao") or "").upper() != "ACÓRDÃO":
                        continue
                    vistos.add(aid)
                    d = ler_decisao(a.get("decisao"), a.get("ministroRelator"))
                    data = a.get("dataDecisao") or ""
                    data = f"{data[:4]}-{data[4:6]}-{data[6:8]}" if re.fullmatch(r"\d{8}", data) else None
                    if data:
                        periodo[0] = min(periodo[0] or data, data)
                        periodo[1] = max(periodo[1] or data, data)
                    o["acordaos"] += 1
                    o[d["resultado"] or "sem_resultado"] += 1
                    for k in d["posicoes"]:
                        freq[k] = freq.get(k, 0) + 1
                        g = d["grafias"].get(k)
                        if g and (k not in bonito or (bonito[k].isascii() and not g.isascii())):
                            bonito[k] = g  # grafia da certidão, de preferência com acento
                        elif k not in bonito:
                            rel = a.get("ministroRelator") if chave_nome(a.get("ministroRelator") or "") == k else None
                            bonito[k] = _nome_bonito(a.get("decisao"), k, rel)
                    meta = None
                    if d["resultado"] == "maioria":
                        meta = {"id": aid, "classe": a.get("siglaClasse"), "numero": a.get("numeroProcesso"), "orgao": orgao, "data": data,
                                "relator": a.get("ministroRelator"), "dispositivo": d["dispositivo"], "presidiu": d["presidiu"],
                                "ementa": re.sub(r"\s+", " ", a.get("ementa") or "")[:400], "pagina": PAGINA.format(pacote)}
                    lidos.append((orgao, d["resultado"], d["posicoes"], meta))
        if len(vistos) < 2000:
            raise RuntimeError(f"leitura incompleta: {len(vistos)} acórdãos do STJ")
        mapa = unir_chaves(freq)
        por_ministro: dict = {}
        maioria = []
        for orgao, resultado, pos, meta in lidos:
            final: dict[str, str] = {}
            for k, p in pos.items():
                for kk in mapa.get(k, [k]):
                    final.setdefault(kk, p)
            for k, p in final.items():
                m = por_ministro.setdefault(k, {"nome": bonito.get(k) or k.title(), "orgaos": {}, **{c: 0 for c in POSICOES}, "maioria_vencedor": 0, "maioria_vencido": 0})
                m[p] += 1
                m["orgaos"][orgao] = m["orgaos"].get(orgao, 0) + 1
                if resultado == "maioria":
                    if p in ("vencido", "vencido_parte"):
                        m["maioria_vencido"] += 1
                    elif p in ("acompanhou", "relator", "relator_acordao"):
                        m["maioria_vencedor"] += 1
            if meta:
                maioria.append({**meta, "posicoes": [{"ministro": bonito.get(k) or k.title(), "posicao": p} for k, p in final.items()]})
        for k, m in por_ministro.items():
            votou = m["acompanhou"] + m["relator"] + m["relator_acordao"] + m["vencido"] + m["vencido_parte"] + m["participou_unanime"]
            if votou < 5:  # convocados de passagem e grafias soltas ficam de fora da lista (continuam nas decisões)
                continue
            upsert(db, Registro, {"fonte": "stj", "tipo": "stj_ministro", "chave": k},
                   {"titulo": m["nome"], "valor": votou, "dados": {**m, "votos_registrados": votou}})
            n += 1
        maioria.sort(key=lambda x: x["data"] or "", reverse=True)
        arqs = sorted({a for o in orgaos.values() for a in o["arquivos"]})
        upsert(db, Registro, {"fonte": "stj", "tipo": "stj_resumo", "chave": "ultimo"},
               {"titulo": "STJ: votos nos acórdãos", "valor": len(vistos),
                "dados": {"acordaos": len(vistos), "periodo": periodo, "publicados": [arqs[0][:6], arqs[-1][:6]] if arqs else None, "meses": meses,
                          "orgaos": orgaos, "maioria": maioria[:400], "maioria_total": len(maioria), "coletado_em": date.today().isoformat()}})
        db.commit()
    return n.itens
