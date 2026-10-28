"""Indicadores econômicos e dívida pública — Banco Central (SGS, Sistema Gerenciador de Séries Temporais).
Docs: https://dadosabertos.bcb.gov.br/  ·  formato: api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json

Os códigos estão em SERIES; confira em https://www3.bcb.gov.br/sgspub se algum vier vazio.
O BC limita séries diárias a 10 anos por consulta, por isso pedimos em janelas.
"""
import logging
from datetime import date, timedelta

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import para_data, para_float, upsert

log = logging.getLogger("brasilplus.bcb")
URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"

# nome: (código SGS, descrição, unidade, periodicidade)
SERIES = {
    "selic": (432, "Taxa Selic (meta)", "% ao ano", "diaria"),
    "ipca_mes": (433, "IPCA — variação no mês", "%", "mensal"),
    "ipca_12m": (13522, "IPCA — acumulado em 12 meses", "%", "mensal"),
    "dolar": (1, "Dólar comercial (venda, PTAX)", "R$", "diaria"),
    "desemprego": (24369, "Taxa de desocupação (PNAD Contínua)", "%", "mensal"),
    "divida_bruta_pib": (13762, "Dívida bruta do governo geral", "% do PIB", "mensal"),
    "divida_liquida_pib": (4513, "Dívida líquida do setor público", "% do PIB", "mensal"),
    "juros_nominais_pib": (5727, "Juros nominais do setor público (12 meses)", "% do PIB", "mensal"),
    "pib_12m": (4382, "PIB acumulado em 12 meses", "R$ milhões", "mensal"),
    "endividamento_familias": (29037, "Endividamento das famílias com o sistema financeiro", "% da renda", "mensal"),
    "inadimplencia_pf": (21084, "Inadimplência das pessoas físicas", "% da carteira", "mensal"),
    "inadimplencia_pj": (21083, "Inadimplência das empresas", "% da carteira", "mensal"),
    "salario_minimo": (1619, "Salário mínimo", "R$", "mensal"),
    "balanca_saldo": (22707, "Balança comercial — saldo do mês", "US$ milhões", "mensal"),
    "balanca_export": (22708, "Balança comercial — exportações do mês", "US$ milhões", "mensal"),
    "balanca_import": (22709, "Balança comercial — importações do mês", "US$ milhões", "mensal"),
    "pib_var_anual": (7326, "Crescimento do PIB (variação real no ano)", "%", "mensal"),
    # o SGS parou de publicar o Ibovespa em 2019: o fechamento de cada mês vem do Yahoo Finance (^BVSP), código 0 = fora do SGS
    "ibovespa": (0, "Ibovespa (fechamento do mês)", "pontos", "mensal"),
}


def _baixar(codigo: int, ini: date, fim: date, tentativas: int = 4):
    """A API do SGS às vezes responde HTTP 200 com uma página HTML de erro no lugar do JSON (visto em out/2026,
    de forma intermitente e mais em consultas longas): nesse caso espera e tenta de novo."""
    import time
    for t in range(1, tentativas + 1):
        try:
            return http.get_json(URL.format(codigo=codigo), params={
                "formato": "json", "dataInicial": f"{ini:%d/%m/%Y}", "dataFinal": f"{fim:%d/%m/%Y}"}) or []
        except ValueError:
            if t == tentativas:
                raise RuntimeError("a API do Banco Central respondeu uma página de erro em vez dos dados") from None
            time.sleep(5 * t)


def _ibovespa() -> list[tuple[date, float]]:
    """Fechamento mensal do Ibovespa desde 1993 (Yahoo Finance, ^BVSP). Falha com erro claro se a resposta mudar."""
    r = http.get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP", params={"range": "max", "interval": "1mo"},
                      headers={"User-Agent": "Mozilla/5.0 (BRASIL+ coletor de dados publicos)"}) or {}
    res = ((r.get("chart") or {}).get("result") or [None])[0]
    if not res:
        raise RuntimeError("Yahoo Finance sem dados do Ibovespa")
    ts = res.get("timestamp") or []
    fech = (((res.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    out = []
    for t, v in zip(ts, fech):
        if v is not None:
            out.append((date.fromtimestamp(t + 12 * 3600), float(v)))
    if len(out) < 24:
        raise RuntimeError("Yahoo Finance devolveu poucos pontos do Ibovespa")
    return out


def coletar_series(anos: int = 42, nomes: list[str] | None = None):
    """Séries do SGS desde 1985 (volta das eleições diretas); as que começam depois vêm do ano em que existem."""
    fim = date.today()
    with registrar_coleta("bcb", "series", anos=anos) as (db, n):
        falhas = []
        for nome, (codigo, desc, unidade, per) in SERIES.items():
            if nomes and nome not in nomes:
                continue
            try:
                if nome == "ibovespa":
                    for dt, v in _ibovespa():
                        upsert(db, Registro, {"fonte": "bcb", "tipo": "serie:ibovespa", "chave": f"{dt:%Y-%m-%d}"},
                               {"ano": dt.year, "titulo": desc, "valor": v,
                                "dados": {"data": dt.isoformat(), "unidade": unidade, "codigo": codigo}})
                        n += 1
                    db.commit()
                    continue
                ini = date(1985, 1, 1) if anos >= 40 else fim - timedelta(days=365 * anos)
                janela = timedelta(days=365 * 3)  # consultas curtas falham bem menos
                while ini <= fim:
                    f = min(ini + janela, fim)
                    try:
                        dados = _baixar(codigo, ini, f)
                    except Exception as e:
                        # séries que só existem a partir de certo ano respondem erro (ex.: 404) nas janelas antigas
                        if f.year >= 2005 and "404" not in str(e):
                            raise
                        ini = f + timedelta(days=1)
                        continue
                    # séries diárias: guarda só o último valor de cada mês (suficiente para gráficos)
                    por_chave = {}
                    for d in dados:
                        dt = para_data(d.get("data"))
                        if not dt:
                            continue
                        por_chave[f"{dt:%Y-%m}" if per == "diaria" else f"{dt:%Y-%m-%d}"] = (dt, para_float(d.get("valor")))
                    for chave, (dt, v) in por_chave.items():
                        upsert(db, Registro, {"fonte": "bcb", "tipo": f"serie:{nome}", "chave": chave},
                               {"ano": dt.year, "titulo": desc, "valor": v,
                                "dados": {"data": dt.isoformat(), "unidade": unidade, "codigo": codigo}})
                        n += 1
                    ini = f + timedelta(days=1)
                db.commit()
            except Exception as e:
                db.rollback()
                falhas.append(f"{nome}: {e}")
                log.warning("Série %s (%s) falhou: %s", nome, codigo, e)
        if falhas and not n.itens:
            raise RuntimeError("; ".join(falhas))
        n.avisos += falhas
    return n.itens
