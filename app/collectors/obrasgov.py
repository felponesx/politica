"""Obras / projetos de investimento federais — ObrasGov.br.
Docs: https://api.obrasgov.gestao.gov.br/obrasgov/api/swagger-ui/index.html
"""
from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, primeiro, para_float, upsert

BASE = "https://api.obrasgov.gestao.gov.br/obrasgov/api"


def _valor_previsto(o: dict) -> float | None:
    """O valor vem por fonte de recurso (Federal, Estadual...): somamos todas."""
    fontes = o.get("fontesDeRecurso") or []
    valores = [para_float(f.get("valorInvestimentoPrevisto")) for f in fontes if isinstance(f, dict)]
    valores = [v for v in valores if v is not None]
    return round(sum(valores), 2) if valores else para_float(primeiro(o, "valorInvestimentoPrevisto", "valorTotal"))


def coletar_obras(ufs: list[str] | None = None, tamanho: int = 100):
    with registrar_coleta("obrasgov", "obras") as (db, n):
        for uf in ufs or UFS:
            pagina = 0
            while True:
                resp = http.get_json(f"{BASE}/projeto-investimento",
                                     params={"uf": uf, "pagina": pagina, "tamanhoDaPagina": tamanho})
                itens = resp if isinstance(resp, list) else (resp or {}).get("content") or (resp or {}).get("data") or []
                for o in itens:
                    chave = primeiro(o, "idUnico", "id")
                    if not chave:
                        continue
                    upsert(db, Registro, {"fonte": "obrasgov", "tipo": "obra", "chave": str(chave)}, {
                        "uf": uf, "titulo": primeiro(o, "nome", "descricao"),
                        "valor": _valor_previsto(o),
                        "dados": o,
                    })
                    n += 1
                db.commit()
                ultima = resp.get("last") if isinstance(resp, dict) else None
                if ultima is True or len(itens) < tamanho:
                    break
                pagina += 1
    return n.itens
