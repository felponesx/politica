"""Querido Diário (Open Knowledge Brasil): busca nos diários oficiais municipais.

Investigação (30/10/2026, pelo robô do GitHub): `api.queridodiario.ok.org.br` recusa o handshake TLS (o servidor não tem certificado para esse nome: erro
SSLV3_ALERT_HANDSHAKE_FAILURE em TLS 1.2 e 1.3, com DNS normal), enquanto `queridodiario.ok.org.br/api` responde 200 com certificado válido. Por isso usamos
o segundo endereço, com a verificação do TLS ligada. Há retentativa com espera crescente (app/http.py), cache em memória por consulta (até `cache_segundos`), paginação por `offset`
e um histórico de disponibilidade. Se o serviço cair, a resposta diz que está indisponível: dado antigo nunca é mostrado como atual."""
import logging
import time
from datetime import date, datetime, timedelta

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import memo, upsert

log = logging.getLogger("brasilplus.qd")
BASE = "https://queridodiario.ok.org.br/api"
TERMOS = ("dispensa de licitação", "contratação emergencial", "inexigibilidade de licitação")
MAXIMO_POR_PAGINA = 50
PAUSA = 1.0   # segundos entre chamadas seguidas (serviço mantido por voluntários)


def buscar(querystring: str = "", desde: date | None = None, ate: date | None = None, territorios: list[str] | None = None, tamanho: int = 10, offset: int = 0) -> dict:
    """Uma página de resultados (cache em memória). Levanta a exceção da rede se o serviço não responder."""
    tamanho = max(1, min(int(tamanho), MAXIMO_POR_PAGINA))
    params = {"querystring": querystring, "size": tamanho, "offset": max(0, int(offset)), "sort_by": "descending_date"}
    if desde:
        params["published_since"] = desde.isoformat()
    if ate:
        params["published_until"] = ate.isoformat()
    if territorios:
        params["territory_ids"] = territorios
    chave = ("qd", querystring, params.get("published_since"), params.get("published_until"), tuple(territorios or ()), tamanho, offset)
    return memo(chave, lambda: _enxugar(http.get_json(f"{BASE}/gazettes", params=params, timeout=45)), ttl=3600)


def _enxugar(js: dict | None) -> dict:
    js = js or {}
    return {"total": js.get("total_gazettes"), "limitado": (js.get("total_gazettes") or 0) >= 10_000,
            "diarios": [{"municipio": g.get("territory_name"), "uf": g.get("state_code"), "codigo_ibge": g.get("territory_id"), "data": g.get("date"), "edicao": g.get("edition"),
                         "extra": g.get("is_extra_edition"), "url": g.get("url"), "trechos": [t[:400] for t in (g.get("excerpts") or [])[:3]]} for g in js.get("gazettes") or []]}


def sondar() -> dict:
    """Testa os dois endereços principais e devolve o resultado (sem levantar exceção)."""
    out = {"medido_em": datetime.now().isoformat(timespec="seconds"), "endpoints": {}}
    for nome, caminho, params in (("cities", "/cities", {"city_name": "campinas"}), ("gazettes", "/gazettes", {"querystring": "licitação", "size": 1})):
        t0 = time.time()
        try:
            r = http.get(BASE + caminho, params=params, timeout=45)
            out["endpoints"][nome] = {"http": r.status_code, "segundos": round(time.time() - t0, 2), "ok": True}
        except Exception as e:  # noqa: BLE001
            resp = getattr(e, "response", None)
            out["endpoints"][nome] = {"http": getattr(resp, "status_code", None), "erro": f"{type(e).__name__}: {str(e)[:100]}", "ok": False}
    out["disponivel"] = all(v["ok"] for v in out["endpoints"].values())
    return out


def coletar_querido_diario(dias: int = 30):
    """Registra a disponibilidade e conta, nos últimos `dias`, os diários que citam dispensa/emergência/inexigibilidade (contagem do serviço, limitada a 10 mil)."""
    with registrar_coleta("querido_diario", "diarios") as (db, n):
        s = sondar()
        hist = db.query(Registro).filter_by(fonte="querido_diario", tipo="disponibilidade", chave="historico").first()
        lista = ((hist.dados or {}).get("medicoes") or []) if hist else []
        lista = (lista + [{"em": s["medido_em"], "disponivel": s["disponivel"], "endpoints": s["endpoints"]}])[-200:]
        upsert(db, Registro, {"fonte": "querido_diario", "tipo": "disponibilidade", "chave": "historico"},
               {"titulo": "Disponibilidade do Querido Diário", "dados": {"medicoes": lista, "ultima": s}})
        db.commit()
        if not s["disponivel"]:
            raise RuntimeError("Querido Diário indisponível agora: " + "; ".join(f"{k}: {v.get('erro') or v.get('http')}" for k, v in s["endpoints"].items() if not v["ok"]))
        ate = date.today()
        desde = ate - timedelta(days=int(dias))
        contagens = {}
        for termo in TERMOS:
            r = buscar(f'"{termo}"', desde, ate, tamanho=1)
            contagens[termo] = {"diarios": r["total"], "limitado": r["limitado"]}
            time.sleep(PAUSA)
        upsert(db, Registro, {"fonte": "querido_diario", "tipo": "termos", "chave": f"{dias}d"},
               {"titulo": f"Diários que citam termos de contratação (últimos {dias} dias)", "dados": {"desde": desde.isoformat(), "ate": ate.isoformat(), "termos": contagens, "medido_em": s["medido_em"]}})
        db.commit()
        n += len(contagens)
    return n.itens
