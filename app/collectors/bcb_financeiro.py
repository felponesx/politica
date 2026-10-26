"""Sistema financeiro (bancos, cooperativas e crédito) — Banco Central do Brasil.

- IF.data (Olinda): balanço (relatório 1, de dezembro) e demonstração de resultado (relatório 4, semestral: soma de junho e dezembro) de cada
  conglomerado prudencial e instituição independente (TipoInstituicao=1), em reais. Cadastro com nome e UF.
- SGS: carteira de crédito (total, pessoas e empresas), concessões, juros, spread, inadimplência e crédito/PIB.

Guarda um registro (fonte "bcb", tipo "financeiro") com os totais, a conta "para onde vai cada R$ 100 da receita", as maiores instituições
e as séries do crédito. A receita é a soma das rendas de crédito, títulos, aplicações, serviços e tarifas, transações de pagamento e
outras receitas (letras a, b, c, d, e, i, j, l, m, n, s e t da demonstração de resultado do IF.data); o gasto é o que sai dessa receita
(captações, perdas com crédito, pessoal, administração, tributos e outras despesas). Não é a contabilidade de uma empresa comum.
"""
import logging
import re
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.bcb_financeiro")
IFDATA = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"
SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"  # "ultimos/N" só aceita até 20: pedimos por datas

# código SGS: (chave, descrição, unidade)
SERIES = {
    20539: ("credito_total", "Saldo da carteira de crédito total", "R$ milhões"),
    20540: ("credito_pf", "Saldo de crédito — pessoas físicas", "R$ milhões"),
    20541: ("credito_pj", "Saldo de crédito — empresas", "R$ milhões"),
    20631: ("concessoes", "Concessões de crédito no mês", "R$ milhões"),
    20622: ("credito_pib", "Crédito em relação ao PIB", "% do PIB"),
    20714: ("juros_medio", "Taxa média de juros do crédito", "% ao ano"),
    20783: ("spread", "Spread médio (juros cobrados menos custo do dinheiro)", "pontos percentuais"),
    21082: ("inadimplencia", "Inadimplência (atraso de mais de 90 dias)", "% da carteira"),
}

RECEITAS = ("a", "b", "c", "d", "e", "i", "j", "l", "m", "n", "s", "t")   # letras do IF.data somadas na receita
DESPESAS = {"captacao": ("g", "h", "aa"), "perdas": ("f", "f4", "f5", "q"), "pessoal": ("o",), "administracao": ("p", "r", "x", "y"),
            "outras": ("u",)}


def _norm(nome: str) -> str:
    return re.sub(r"\s+", " ", nome or "").strip()


def _letra(nome: str) -> str | None:
    m = re.search(r"\(([a-z]{1,2}\d?)\)", _norm(nome))
    return m.group(1) if m else None


def _odata(rota: str, anomes: str, relatorio: str, extra: dict | None = None) -> list[dict]:
    """IfDataValores de todos os conglomerados prudenciais e instituições independentes (TipoInstituicao 1) em um relatório."""
    params = {"@AnoMes": anomes, "@TipoInstituicao": 1, "@Relatorio": f"'{relatorio}'", "$top": 100000, "$format": "json",
              "$select": "CodInst,Conta,NomeColuna,Saldo", **(extra or {})}
    r = http.get_json(f"{IFDATA}/{rota}(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,Relatorio=@Relatorio)", params=params) or {}
    return r.get("value") or []


def _cadastro(anomes: str) -> dict[str, dict]:
    params = {"@AnoMes": anomes, "$top": 100000, "$format": "json", "$select": "CodInst,NomeInstituicao,Sr,Uf,Atividade,Tcb,CodConglomeradoPrudencial"}
    r = http.get_json(f"{IFDATA}/IfDataCadastro(AnoMes=@AnoMes)", params=params) or {}
    return {x["CodInst"]: x for x in r.get("value") or []}


def _serie(codigo: int, anos: int = 5) -> list[dict]:
    hoje = date.today()
    ini = date(hoje.year - anos, hoje.month, 1)
    dados = http.get_json(SGS.format(codigo=codigo), params={"formato": "json", "dataInicial": f"{ini:%d/%m/%Y}", "dataFinal": f"{hoje:%d/%m/%Y}"}) or []
    out = []
    for p in dados:
        try:
            d = p["data"].split("/")
            out.append({"data": f"{d[2]}-{d[1]}-{d[0]}", "valor": float(str(p["valor"]).replace(",", "."))})
        except (KeyError, ValueError, IndexError):
            continue
    return out


def _anomes_disponivel(ano: int | None) -> str:
    """Dezembro do último ano fechado (flui o ano todo); se o BC ainda não publicou, junho ou o ano anterior."""
    hoje = date.today()
    candidatos = [f"{ano}12"] if ano else [f"{hoje.year - 1}12", f"{hoje.year - 1}06", f"{hoje.year - 2}12"]
    for am in candidatos:
        try:
            if _odata("IfDataValores", am, "1", {"$top": 1}):
                return am
        except Exception as e:  # noqa: BLE001 - tenta a próxima data
            log.info("IF.data %s: %s", am, e)
    raise RuntimeError("IF.data sem dados para as datas tentadas")


def calcular(balanco: list[dict], resultado: list[dict], cadastro: dict[str, dict]) -> dict:
    """Soma o sistema e monta as maiores instituições. Os valores do IF.data já vêm em reais."""
    inst: dict[str, dict] = {}

    def ent(cod):
        return inst.setdefault(cod, {"cod": cod, "r": {}, "b": {}})

    for x in balanco:
        nome = _norm(x.get("NomeColuna")).lower()
        k = ("ativo" if nome.startswith("ativo total") else "carteira" if nome.startswith("carteira de crédito") else "captacoes" if nome.startswith("captações")
             else "patrimonio" if nome.startswith("patrimônio líquido") else "basileia" if nome.startswith("índice de basileia") else None)
        if k and x.get("Saldo") is not None:
            ent(x["CodInst"])["b"][k] = x["Saldo"]
    for x in resultado:
        letra = _letra(x.get("NomeColuna"))
        if letra and x.get("Saldo") is not None:  # o resultado do IF.data é semestral: soma os dois semestres do ano
            r = ent(x["CodInst"])["r"]
            r[letra] = r.get(letra, 0) + x["Saldo"]
    linhas = []
    for cod, e in inst.items():
        r = e["r"]
        receita = sum(r.get(l, 0) for l in RECEITAS)
        d = {k: -sum(r.get(l, 0) for l in ls) for k, ls in DESPESAS.items()}
        lucro = r.get("z")
        if lucro is None or receita <= 0 or not e["b"].get("ativo"):
            continue
        cad = cadastro.get(cod) or {}
        linhas.append({"cod": cod, "nome": cad.get("NomeInstituicao") or cod, "segmento": cad.get("Sr"), "uf": cad.get("Uf"), "atividade": cad.get("Atividade"),
                       "ativo": e["b"]["ativo"], "carteira": e["b"].get("carteira") or 0, "captacoes": e["b"].get("captacoes") or 0,
                       "patrimonio": e["b"].get("patrimonio") or 0, "basileia": e["b"].get("basileia"),
                       "receita": receita, "lucro": lucro, **d})
    if not linhas:
        raise RuntimeError("Nenhuma instituição com balanço e resultado")
    soma = {k: sum(l[k] for l in linhas) for k in ("ativo", "carteira", "captacoes", "patrimonio", "receita", "lucro", "captacao", "perdas", "pessoal", "administracao", "outras")}
    outros = soma["receita"] - soma["lucro"] - sum(soma[k] for k in ("captacao", "perdas", "pessoal", "administracao", "outras"))
    maiores = sorted(linhas, key=lambda l: -l["ativo"])[:15]
    return {"instituicoes": len(linhas), "totais": soma, "outros_custos": outros,
            "maiores": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in l.items() if k not in ("cod",)} for l in maiores]}


def coletar_sistema_financeiro(ano: int | None = None):
    with registrar_coleta("bcb", "financeiro", ano=ano or "ultimo") as (db, n):
        am = _anomes_disponivel(ano)
        balanco = _odata("IfDataValores", am, "1")
        # a demonstração de resultado é semestral: o ano é a soma de junho e dezembro (se junho faltar, só dezembro e o aviso)
        resultado = _odata("IfDataValores", am, "4")
        if am.endswith("12"):
            try:
                resultado += _odata("IfDataValores", am[:4] + "06", "4")
            except Exception as e:  # noqa: BLE001
                n.avisos.append(f"resultado do 1º semestre: {type(e).__name__}: {e}"[:200])
        dados = calcular(balanco, resultado, _cadastro(am))
        series = {}
        for codigo, (chave, desc, unidade) in SERIES.items():
            try:
                h = _serie(codigo)
            except Exception as e:  # noqa: BLE001 - uma série fora do ar não derruba as outras
                n.avisos.append(f"SGS {codigo}: {type(e).__name__}: {e}"[:200])
                continue
            if h:
                ult = h[-1]
                antes = next((p for p in reversed(h) if p["data"][:7] == f"{int(ult['data'][:4]) - 1}{ult['data'][4:7]}"), None)
                series[chave] = {"descricao": desc, "unidade": unidade, "ultimo": ult, "doze_meses_antes": antes, "historico": h}
        dados.update({"referencia": f"{am[:4]}-{am[4:]}", "series": series})
        upsert(db, Registro, {"fonte": "bcb", "tipo": "financeiro", "chave": "sistema"},
               {"ano": int(am[:4]), "titulo": "Sistema financeiro (IF.data e SGS)", "valor": dados["instituicoes"], "dados": dados})
        db.commit()
        n += dados["instituicoes"]
    return n.itens
