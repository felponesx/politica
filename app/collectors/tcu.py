"""Pessoas inabilitadas pelo TCU para cargo em comissão ou função de confiança (lista pública do TCU).

API: https://contas.tcu.gov.br/ords/condenacao/consulta/inabilitados (ORDS: `items`, `hasMore`, `limit`, `offset`). Cada item traz nome, CPF, processo, deliberação,
datas e UF/município. Aqui só se guardam TOTAIS (por estado, por ano do acórdão, quantos ainda estão no prazo): nomes e CPFs não são gravados."""
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

URL = "https://contas.tcu.gov.br/ords/condenacao/consulta/inabilitados"
PAGINA = 500
MINIMO = 300   # itens esperados no mínimo (guarda contra leitura cortada)
TETO_PAGINAS = 200


def ler_itens() -> list[dict]:
    itens: list[dict] = []
    for i in range(TETO_PAGINAS):
        r = http.get_json(URL, params={"limit": PAGINA, "offset": i * PAGINA}) or {}
        itens += r.get("items") or []
        if not r.get("hasMore"):
            return itens
    raise RuntimeError("TCU: paginação sem fim")


def resumir(itens: list[dict], hoje: date | None = None) -> dict:
    hoje = (hoje or date.today()).isoformat()
    por_uf: dict[str, dict] = {}
    por_ano: dict[str, int] = {}
    ativos = 0
    for x in itens:
        uf = (x.get("uf") or "").strip().upper()[:2] or "ND"
        ativo = bool(x.get("data_final")) and str(x["data_final"])[:10] >= hoje
        u = por_uf.setdefault(uf, {"total": 0, "ativos": 0})
        u["total"] += 1
        u["ativos"] += ativo
        ativos += ativo
        ano = str(x.get("data_acordao") or "")[:4]
        if ano.isdigit():
            por_ano[ano] = por_ano.get(ano, 0) + 1
    return {"total": len(itens), "ativos": ativos, "por_uf": dict(sorted(por_uf.items())), "por_ano": dict(sorted(por_ano.items())), "referencia": hoje}


def coletar_tcu_inabilitados():
    with registrar_coleta("tcu", "inabilitados") as (db, n):
        itens = ler_itens()
        if len(itens) < MINIMO:
            raise RuntimeError(f"vieram {len(itens)} registros (esperado ao menos {MINIMO}); nada foi gravado")
        upsert(db, Registro, {"fonte": "tcu", "tipo": "tcu_inabilitados", "chave": "BR"},
               {"titulo": "Inabilitados pelo TCU", "valor": float(len(itens)), "dados": resumir(itens)})
        db.commit()
        n += 1
    return n.itens
