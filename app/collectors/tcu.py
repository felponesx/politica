"""Pessoas inabilitadas pelo TCU para cargo em comissão ou função de confiança (lista pública do TCU).

API: https://contas.tcu.gov.br/ords/condenacao/consulta/inabilitados (ORDS: `items`, `hasMore`, `limit`, `offset`). Cada item traz nome, CPF, processo, deliberação,
datas e UF/município. Aqui só se guardam TOTAIS (por estado, por ano do acórdão, quantos ainda estão no prazo): nomes e CPFs não são gravados."""
import re
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


URL_IRREGULARES = "https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-contas-irregulares"
MINIMO_IRREGULARES = 500


def resumir_irregulares(itens: list[dict]) -> dict:
    """Totais por UF, por ano do trânsito em julgado e por tipo de registro (CPF/CNPJ). Nome e número do registro NÃO são guardados."""
    por_uf: dict[str, int] = {}
    por_ano: dict[str, int] = {}
    por_tipo: dict[str, int] = {}
    for x in itens:
        uf = (x.get("uf") or "").strip().upper()[:2] or "ND"
        por_uf[uf] = por_uf.get(uf, 0) + 1
        m = re.search(r"(\d{4})\s*$", str(x.get("dataTransitoEmJulgado") or ""))
        if m:
            por_ano[m.group(1)] = por_ano.get(m.group(1), 0) + 1
        t = (x.get("tipoRegistro") or "ND").strip().upper()
        por_tipo[t] = por_tipo.get(t, 0) + 1
    return {"total": len(itens), "por_uf": dict(sorted(por_uf.items())), "por_ano": dict(sorted(por_ano.items())), "por_tipo": por_tipo}


def coletar_tcu_irregulares():
    with registrar_coleta("tcu", "contas_irregulares") as (db, n):
        r = http._cliente.post(URL_IRREGULARES, json={}, timeout=300, headers={"Accept": "application/json"})
        r.raise_for_status()
        itens = r.json()
        if not isinstance(itens, list) or len(itens) < MINIMO_IRREGULARES:
            raise RuntimeError(f"vieram {len(itens) if isinstance(itens, list) else 'formato inesperado'} registros (esperado ao menos {MINIMO_IRREGULARES}); nada foi gravado")
        upsert(db, Registro, {"fonte": "tcu", "tipo": "tcu_irregulares", "chave": "BR"},
               {"titulo": "Contas julgadas irregulares (TCU)", "valor": float(len(itens)), "dados": resumir_irregulares(itens)})
        db.commit()
        n += 1
    return n.itens
