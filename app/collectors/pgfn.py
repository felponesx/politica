"""Dívida ativa da União — dados abertos da PGFN (trimestrais).
Página: https://www.gov.br/pgfn/pt-br/assuntos/divida-ativa-da-uniao/transparencia-fiscal-1/dados-abertos

São três arquivos grandes (ZIP com vários CSV): não previdenciário, previdenciário e FGTS.
- Totais por estado: todas as inscrições do devedor principal (pessoas físicas e jurídicas).
- Devedores individuais: SÓ empresas (CNPJ) cujo total passe de `minimo_devedor`.
  Pessoas físicas nunca são gravadas individualmente.
"""
import csv
import io
import logging
import zipfile

from sqlalchemy import delete

from app.collectors.arquivos import baixar_temp
from app.collectors.base import registrar_coleta
from app.models import DevedorPGFN, Registro
from app.utils import para_float, para_uf, sem_acento, so_digitos, upsert

log = logging.getLogger("brasilplus.pgfn")
URL = "https://dadosabertos.pgfn.gov.br/{ano}_trimestre_{tri:02d}/Dados_abertos_{nome}.zip"
ARQUIVOS = {"nao_previdenciaria": "Nao_Previdenciario", "previdenciaria": "Previdenciario", "fgts": "FGTS"}


def _col(cab, *nomes):
    norm = {sem_acento(c).replace(" ", "_"): c for c in cab}
    return next((norm[n] for n in nomes if n in norm), None)


def ler_inscricoes(caminho_zip: str):
    """Gera dicts normalizados de cada inscrição (streaming, sem carregar o arquivo na memória)."""
    with zipfile.ZipFile(caminho_zip) as z:
        for nome in z.namelist():
            if not nome.lower().endswith((".csv", ".txt")):
                continue
            with z.open(nome) as bruto:
                leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
                cab = next(leitor)
                c = {k: _col(cab, *v) for k, v in {
                    "doc": ("CPF_CNPJ",), "pessoa": ("TIPO_PESSOA",), "devedor": ("TIPO_DEVEDOR",),
                    "nome": ("NOME_DEVEDOR",), "uf": ("UF_DEVEDOR", "UF_UNIDADE_RESPONSAVEL", "UF"),
                    "ajuizado": ("INDICADOR_AJUIZADO",), "valor": ("VALOR_CONSOLIDADO",)}.items()}
                if not c["doc"] or not c["valor"]:
                    raise ValueError(f"Colunas inesperadas em {nome}: {cab[:8]}")
                idx = {k: cab.index(v) if v else None for k, v in c.items()}
                for linha in leitor:
                    g = lambda k: linha[idx[k]] if idx[k] is not None and idx[k] < len(linha) else ""
                    yield {"doc": so_digitos(g("doc")), "pj": "JUR" in sem_acento(g("pessoa")),
                           "principal": not g("devedor") or sem_acento(g("devedor")).startswith("PRINCIPAL"),
                           "nome": g("nome").strip(), "uf": para_uf(g("uf")), "ajuizado": sem_acento(g("ajuizado")) == "SIM",
                           "valor": para_float(g("valor")) or 0.0}


def coletar_divida_ativa(ano: int, trimestre: int, tipos: list[str] | None = None, arquivo_local: str | None = None,
                         minimo_inscricao: float = 10000, minimo_devedor: float = 1_000_000):
    """Ex.: python -m scripts.coletar pgfn-divida-ativa ano=2025 trimestre=2
    Com arquivo já baixado: arquivo_local=Dados_abertos_Nao_Previdenciario.zip tipos=nao_previdenciaria"""
    ref = f"{ano}T{int(trimestre)}"
    tipos = tipos or list(ARQUIVOS)
    with registrar_coleta("pgfn", "divida_ativa", referencia=ref, tipos=",".join(tipos)) as (db, n):
        for tipo in tipos:
            caminho = arquivo_local or baixar_temp(URL.format(ano=ano, tri=int(trimestre), nome=ARQUIVOS[tipo]),
                                                   f"pgfn-{tipo}-{ref}.zip")
            por_uf, por_cnpj = {}, {}
            for i in ler_inscricoes(caminho):
                if not i["principal"]:
                    continue  # corresponsáveis repetem a mesma inscrição
                chave = (i["uf"] or "??", "PJ" if i["pj"] else "PF")
                t = por_uf.setdefault(chave, [0, 0.0, 0.0])
                t[0] += 1
                t[1] += i["valor"]
                t[2] += i["valor"] if i["ajuizado"] else 0
                if i["pj"] and i["doc"] and len(i["doc"]) == 14 and i["valor"] >= minimo_inscricao:
                    d = por_cnpj.setdefault(i["doc"], [i["nome"], i["uf"], 0, 0.0, 0.0])
                    d[2] += 1
                    d[3] += i["valor"]
                    d[4] += i["valor"] if i["ajuizado"] else 0
            for (uf, pessoa), (q, v, aj) in por_uf.items():
                upsert(db, Registro, {"fonte": "pgfn", "tipo": "divida_ativa_uf", "chave": f"{uf}-{pessoa}-{tipo}-{ref}"},
                       {"uf": uf if uf != "??" else None, "ano": ano, "titulo": f"Dívida ativa {tipo} {pessoa} {uf}",
                        "valor": round(v, 2), "dados": {"pessoa": pessoa, "tipo_divida": tipo, "referencia": ref,
                                                        "inscricoes": q, "ajuizado": round(aj, 2)}})
                n += 1
            db.execute(delete(DevedorPGFN).where(DevedorPGFN.referencia == ref, DevedorPGFN.tipo_divida == tipo))
            for cnpj, (nome, uf, q, v, aj) in por_cnpj.items():
                if v >= minimo_devedor:
                    db.add(DevedorPGFN(cnpj=cnpj, nome=nome[:300], uf=uf, tipo_divida=tipo, inscricoes=q,
                                       valor=round(v, 2), valor_ajuizado=round(aj, 2), referencia=ref))
                    n += 1
            db.commit()
            log.info("PGFN %s %s: %s estados, %s empresas acima do mínimo", tipo, ref, len(por_uf),
                     sum(1 for d in por_cnpj.values() if d[3] >= minimo_devedor))
            if arquivo_local:
                break  # um arquivo local corresponde a um tipo
    return n.itens
