"""Banda larga fixa (Anatel): acessos por estado no mês mais recente, por tecnologia.

O zip de dados abertos (https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/acessos_banda_larga_fixa.zip, ~1 GB) tem um CSV por ano,
`Acessos_Banda_Larga_Fixa_AAAA.csv` (Ano;Mês;Grupo Econômico;Empresa;CNPJ;Porte;UF;Município;Código IBGE;Faixa;Velocidade;Tecnologia;Meio de Acesso;Tipo de Pessoa;Tipo de Produto;Acessos).
Lê só o CSV do ano mais novo, por pedidos Range (sem baixar o zip todo), e soma os acessos do último mês presente em cada UF."""
import csv
import re

from app.collectors.base import registrar_coleta
from app.collectors.bcb_scr import entradas_zip, linhas_entrada
from app.models import Registro
from app.utils import sem_acento, upsert

URL = "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/acessos_banda_larga_fixa.zip"
MINIMO_UF = 27
FIBRA = ("fibra",)   # coluna "Meio de Acesso" = Fibra (o rádio, o cabo metálico e o satélite são outros meios)


def _n(v) -> int:
    try:
        return int(float(str(v).replace(",", ".")))
    except ValueError:
        return 0


def agregar(linhas) -> dict:
    """{"mes": "AAAA-MM", "ufs": {uf: {"acessos", "fibra", "por_meio": {meio: n}}}} só do último mês do arquivo."""
    leitor = csv.reader(linhas, delimiter=";")
    cab = [sem_acento(c).lower().strip() for c in next(leitor)]
    try:
        i = {k: cab.index(k) for k in ("ano", "mes", "uf", "meio de acesso", "acessos")}
    except ValueError as e:
        raise ValueError(f"Anatel: colunas mudaram ({cab[:8]}): {e}") from e
    por_mes: dict[tuple[int, int], dict] = {}
    for lin in leitor:
        if len(lin) <= max(i.values()):
            continue
        ano, mes = _n(lin[i["ano"]]), _n(lin[i["mes"]])
        uf = lin[i["uf"]].strip().upper()
        if not ano or not mes or len(uf) != 2:
            continue
        m = por_mes.setdefault((ano, mes), {})
        u = m.setdefault(uf, {"acessos": 0, "fibra": 0, "por_meio": {}})
        n = _n(lin[i["acessos"]])
        meio = sem_acento(lin[i["meio de acesso"]]).strip().lower() or "outros"
        u["acessos"] += n
        u["fibra"] += n if meio in FIBRA else 0
        u["por_meio"][meio] = u["por_meio"].get(meio, 0) + n
    if not por_mes:
        raise ValueError("Anatel: arquivo sem linhas")
    ano, mes = max(por_mes)
    return {"mes": f"{ano}-{mes:02d}", "ufs": por_mes[(ano, mes)]}


def coletar_anatel_banda_larga():
    with registrar_coleta("anatel", "banda_larga") as (db, n):
        _, entradas = entradas_zip(URL)
        anos = sorted((int(m.group(1)), e) for e in entradas if (m := re.fullmatch(r"(?:.*/)?Acessos_Banda_Larga_Fixa_(\d{4})\.csv", e[0])))
        if not anos:
            raise RuntimeError("Anatel: o zip não tem Acessos_Banda_Larga_Fixa_AAAA.csv")
        ano, (_, comp, metodo, off) = anos[-1]
        r = agregar(linhas_entrada(URL, comp, metodo, off))
        if len([u for u in r["ufs"] if u in UFS_VALIDAS]) < MINIMO_UF:
            raise RuntimeError(f"Anatel: só {len(r['ufs'])} estados no mês {r['mes']}; nada foi gravado")
        for uf, d in r["ufs"].items():
            if uf in UFS_VALIDAS:
                upsert(db, Registro, {"fonte": "anatel", "tipo": "banda_larga_uf", "chave": uf}, {"uf": uf, "titulo": f"Banda larga fixa {uf}", "valor": float(d["acessos"]),
                                                                                              "dados": {"mes": r["mes"], **d}})
                n += 1
        db.commit()
    return n.itens


UFS_VALIDAS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
