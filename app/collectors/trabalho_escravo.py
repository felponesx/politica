"""Cadastro de Empregadores (lista suja do trabalho escravo), Ministério do Trabalho e Emprego: totais por estado e ano.

CSV oficial: https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/cadastro_de_empregadores.csv
Colunas: ID;Ano da ação fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;Decisão administrativa de procedência;Inclusão no Cadastro de Empregadores.
Só totais (empregadores e trabalhadores resgatados por estado e ano da ação fiscal): nomes, CPF e CNPJ NÃO são guardados."""
import csv
import io

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import UFS, sem_acento, upsert

URL = "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/cadastro_de_empregadores.csv"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
MINIMO = 100


def ler(texto: str) -> dict:
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = [sem_acento(c).lower().strip() for c in next(leitor)]
    try:
        i = {"ano": next(k for k, c in enumerate(cab) if c.startswith("ano da")), "uf": cab.index("uf"),
             "trab": next(k for k, c in enumerate(cab) if c.startswith("trabalhadores")), "incl": next(k for k, c in enumerate(cab) if c.startswith("inclusao"))}
    except (ValueError, StopIteration) as e:
        raise ValueError(f"MTE: colunas mudaram ({cab[:8]})") from e
    por_uf: dict = {}
    por_ano: dict = {}
    total = trab_total = 0
    for l in leitor:
        if len(l) <= max(i.values()):
            continue
        uf = l[i["uf"]].strip().upper()
        ano = l[i["ano"]].strip()
        if uf not in UFS or not ano.isdigit():
            continue
        try:
            t = int(float(l[i["trab"]].strip().replace(",", ".") or 0))
        except ValueError:
            t = 0
        total += 1
        trab_total += t
        for d, chave in ((por_uf.setdefault(uf, {"empregadores": 0, "trabalhadores": 0}), None), (por_ano.setdefault(ano, {"empregadores": 0, "trabalhadores": 0}), None)):
            d["empregadores"] += 1
            d["trabalhadores"] += t
    return {"total": total, "trabalhadores": trab_total, "por_uf": dict(sorted(por_uf.items())), "por_ano": dict(sorted(por_ano.items()))}


def coletar_lista_suja():
    with registrar_coleta("mte", "lista_suja") as (db, n):
        bruto = http.get(URL, headers=UA).content
        try:
            texto = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = bruto.decode("latin-1")
        r = ler(texto)
        if r["total"] < MINIMO:
            raise RuntimeError(f"vieram {r['total']} empregadores (esperado ao menos {MINIMO}); nada foi gravado")
        upsert(db, Registro, {"fonte": "mte", "tipo": "lista_suja", "chave": "BR"}, {"titulo": "Cadastro de Empregadores", "valor": float(r["total"]), "dados": r})
        db.commit()
        n += 1
    return n.itens
