"""Contadores publicados pelo Gasto Brasil (CACB/ACSP) e pelo Impostômetro (ACSP), lidos de gastobrasil.com.br.

O Gasto Brasil publica sem login:
- gastômetro: `/api/trpc/counters.spending` (despesa pública do ano: governo geral, União, estados, municípios e previdência,
  cada um com o valor em `as_of` e o ritmo por segundo);
- impostômetro: `/api/impostometro/brasil` e `/uniao` (a resposta do Impostômetro da ACSP repassada pelo site; `Ano` é o total
  arrecadado em `Data`, hora de Brasília, e `Incremento` é o ritmo por segundo naquele momento).
A API do próprio impostometro.com.br exige token e não é usada. Os números entram no site exatamente como foram publicados
(`montar` só reorganiza), com a data e a hora da leitura. Quem usa: scripts/contadores_rapido.py (robô a cada 15 min).
"""
from datetime import datetime, timedelta, timezone

from app import http

BASE = "https://gastobrasil.com.br"
UA = {"User-Agent": "Mozilla/5.0 (BRASIL+ leitor; dados publicos)", "Accept": "application/json"}
BRASILIA = timezone(timedelta(hours=-3))
SITE_IMP = "https://impostometro.com.br/"
SITE_GAS = "https://gastobrasil.com.br/"
CRITERIO_IMP = "tributos, taxas e contribuições da União, dos estados e dos municípios, com multas, juros e correção monetária"
CRITERIO_GAS = "despesa paga da União, dos estados e dos municípios (dados do Tesouro Nacional), corrigida pelo IPCA"


def _json(caminho: str) -> dict:
    r = http._cliente.get(BASE + caminho, headers=UA, timeout=30, follow_redirects=True)
    if r.status_code != 200:
        raise ValueError(f"{caminho}: HTTP {r.status_code}")
    return r.json()


def _num(x, nome: str, minimo: float = 0.0) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x <= minimo:
        raise ValueError(f"{nome} inválido: {x!r}")
    return float(x)


def _quando(texto: str, brasilia: bool) -> datetime:
    d = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    return d.replace(tzinfo=BRASILIA).astimezone(timezone.utc) if d.tzinfo is None and brasilia else d.astimezone(timezone.utc)


def ler_gastometro() -> dict:
    """Despesa pública do ano segundo o Gasto Brasil: total e ritmo de cada esfera, na hora publicada."""
    d = _json("/api/trpc/counters.spending")["result"]["data"]
    entes = {e["cod_ente"]: e for e in d["entities"]}
    out = {"ano": int(d["year"]), "como_de": _quando(d["as_of"], False).isoformat()}
    for chave, cod in (("total", 0), ("uniao", 1), ("estados", 2), ("municipios", 3)):
        out[chave] = {"total": _num(entes[cod]["base_value"], f"{chave}.total"),
                      "por_segundo": _num(entes[cod]["rate_per_second"], f"{chave}.ritmo")}
    p = d.get("previdencia") or {}
    if p.get("base_value"):
        out["previdencia"] = {"total": _num(p["base_value"], "previdencia.total"), "por_segundo": _num(p["rate_per_second"], "previdencia.ritmo")}
    return out


def _imp(caminho: str) -> dict:
    d = _json(caminho)
    return {"como_de": _quando(d["Data"], True).isoformat(), "total": _num(d["Ano"], f"{caminho} Ano"),
            "por_segundo": _num(d["Incremento"], f"{caminho} Incremento"), "ritmo_medio": _num(d["Segundo"], f"{caminho} Segundo"),
            "por_habitante": _num(d["Habitante"], f"{caminho} Habitante")}


def ler_impostometro() -> dict:
    """Arrecadação de tributos do ano segundo o Impostômetro (ACSP): Brasil e União, na hora publicada."""
    return {"brasil": _imp("/api/impostometro/brasil"), "uniao": _imp("/api/impostometro/uniao")}


def _hora(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(BRASILIA).strftime("%d/%m/%Y %H:%M")


def montar(imp: dict | None, gas: dict | None, agora: datetime | None = None) -> dict:
    """Campos no formato de GET /contadores (impostometro e gastometro), prontos para valer sobre a conta própria."""
    out = {"atualizado_em": (agora or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    if imp:
        b, u = imp["brasil"], imp["uniao"]
        quando = datetime.fromisoformat(b["como_de"])
        fed = round(100 * u["total"] / b["total"], 1)
        out["impostometro"] = {
            "por_segundo": round(b["por_segundo"], 2), "total_base": round(b["total"], 2), "ano": quando.astimezone(BRASILIA).year,
            "data_base": quando.astimezone(BRASILIA).date().isoformat(), "meses": None,
            "base": f"número do Impostômetro (ACSP) em {_hora(b['como_de'])}: R$ {b['total'] / 1e12:.2f} tri".replace(".", ","),
            "fonte": f"Impostômetro (ACSP) — {SITE_IMP}", "referencia_url": SITE_IMP,
            "nota": f"Critério da ACSP: {CRITERIO_IMP}. Lido de {BASE} (que repassa o Impostômetro) a cada 15 minutos; o contador segue o "
                    "ritmo por segundo publicado. A divisão é a do Impostômetro: o federal e, juntos, estados e municípios.",
            "partes_pct": {"federal": fed, "estados_municipios": round(100 - fed, 1)},
            "partes_ano": None,
            "ao_vivo": {"base": b["total"], "quando": b["como_de"], "taxa": b["por_segundo"]}}
    if gas:
        t = gas["total"]
        out["gastometro"] = {
            "por_segundo": round(t["por_segundo"], 2), "total_base": round(t["total"], 2), "ano": gas["ano"],
            "data_base": datetime.fromisoformat(gas["como_de"]).astimezone(BRASILIA).date().isoformat(),
            "base": f"contagem do Gasto Brasil (CACB/ACSP) em {_hora(gas['como_de'])}: R$ {t['total'] / 1e12:.2f} tri".replace(".", ","),
            "fonte": f"Gasto Brasil (CACB/ACSP) — {SITE_GAS}", "referencia_url": SITE_GAS,
            "nota": f"Critério: {CRITERIO_GAS}. Lido de {BASE} a cada 15 minutos; o contador segue o ritmo por segundo publicado.",
            "por_esfera": {"U": gas["uniao"]["total"], "E": gas["estados"]["total"], "M": gas["municipios"]["total"]},
            "bimestre": None,
            "ao_vivo": {"base": t["total"], "quando": gas["como_de"], "taxa": t["por_segundo"]}}
        if gas.get("previdencia"):
            out["gastometro"]["previdencia"] = gas["previdencia"]
    return out


def conferir(imp: dict | None, gas: dict | None, agora: datetime | None = None, tolerancia_h: float = 6.0) -> list[str]:
    """Problemas que impedem usar a leitura: número de outro ano, hora velha ou soma que não fecha. Lista vazia = pode usar."""
    agora = agora or datetime.now(timezone.utc)
    erros = []
    for nome, como_de in (("impostômetro", imp and imp["brasil"]["como_de"]), ("gastômetro", gas and gas["como_de"])):
        if como_de and abs((agora - datetime.fromisoformat(como_de)).total_seconds()) > tolerancia_h * 3600:
            erros.append(f"{nome}: a hora publicada ({_hora(como_de)}) está a mais de {tolerancia_h:g} h de agora")
    if imp and imp["uniao"]["total"] >= imp["brasil"]["total"]:
        erros.append("impostômetro: a União aparece com mais do que o Brasil inteiro")
    if gas:
        soma = gas["uniao"]["total"] + gas["estados"]["total"] + gas["municipios"]["total"]
        if abs(soma - gas["total"]["total"]) > 0.02 * gas["total"]["total"]:
            erros.append(f"gastômetro: União + estados + municípios ({soma:.3e}) não fecha com o total ({gas['total']['total']:.3e})")
    return erros
