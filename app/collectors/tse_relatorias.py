"""TSE: decisões de cada ministro relator (tarefa tse-relatorias). NÃO são votos individuais.

Fonte: dados abertos do TSE, "Processual <ano>" → processos_eleitorais_decisoes_<ano>.zip (cdn.tse.jus.br): uma linha por decisão com
instância, data, autor (o relator) e tipo (Acórdão, Decisão monocrática, Despacho, Resolução). Só a instância 3 é o TSE.
O voto de cada ministro nos acórdãos do TSE não sai em base aberta: o arquivo traz só quem relatou, e o portal de jurisprudência
(jurisprudencia.tse.jus.br) recusa acesso automatizado. Por isso aqui só entram as relatorias, e a tela diz que o voto individual
não está disponível — nunca deduz voto do resultado do colegiado.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date

import httpx

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.tse_relatorias")

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/processual/processos_eleitorais_decisoes_{ano}.zip"
PAGINA = "https://dadosabertos.tse.jus.br/dataset/processual-{ano}"
MOTIVO = ("O TSE não publica em base aberta como votou cada ministro: os dados abertos trazem só o relator de cada decisão, "
          "e o portal de jurisprudência não permite leitura automática. Nenhum voto individual é deduzido do resultado.")


def somar_relatorias(linhas) -> dict:
    """{relator: {tipo: n, ultima: data}} só da instância 3 (o próprio TSE)."""
    out: dict = {}
    for l in linhas:
        if (l.get("NR_INSTANCIA") or "").strip() != "3":
            continue
        nome = " ".join((l.get("NM_AUTOR_DECISAO") or "").split())
        if not nome:
            continue
        r = out.setdefault(nome, {"acordaos": 0, "monocraticas": 0, "despachos": 0, "resolucoes": 0, "outras": 0, "ultima": None})
        tipo = (l.get("DS_TIPO_DECISAO") or "").strip().lower()
        chave = {"acórdão": "acordaos", "decisão": "monocraticas", "despacho": "despachos", "resolução": "resolucoes"}.get(tipo, "outras")
        r[chave] += 1
        d = (l.get("DT_DECISAO") or "").strip()
        if len(d) == 10:
            iso = f"{d[6:]}-{d[3:5]}-{d[:2]}"
            r["ultima"] = max(r["ultima"] or iso, iso)
    return out


def coletar_tse_relatorias(anos: list[int] | None = None):
    hoje = date.today().year
    if isinstance(anos, str):
        anos = anos.split(",")
    anos = [int(a) for a in (anos or [a for a in range(hoje - 4, hoje + 1) if a % 2 == 0])]
    with registrar_coleta("tse", "relatorias", anos=",".join(map(str, anos))) as (db, n), httpx.Client(follow_redirects=True, timeout=600) as cli:
        por_ano = {}
        for ano in anos:
            r = cli.get(URL.format(ano=ano))
            if r.status_code == 404:
                n.avisos.append(f"{ano}: arquivo de decisões não publicado")
                continue
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            nome = next(x for x in z.namelist() if x.lower().endswith(".csv"))
            with z.open(nome) as f:
                rel = somar_relatorias(csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"))
            if not rel:
                n.avisos.append(f"{ano}: nenhuma decisão da instância 3 (TSE) no arquivo")
                continue
            por_ano[ano] = rel
            upsert(db, Registro, {"fonte": "tse", "tipo": "tse_relatorias", "chave": str(ano)},
                   {"ano": ano, "titulo": f"relatorias TSE {ano}", "valor": sum(x["acordaos"] for x in rel.values()),
                    "dados": {"ano": ano, "relatores": rel, "fonte": PAGINA.format(ano=ano), "arquivo": URL.format(ano=ano),
                              "votos_individuais": False, "motivo": MOTIVO}})
            n += 1
        if not por_ano:
            raise RuntimeError("nenhum arquivo de decisões do TSE lido")
        db.commit()
    return n.itens
