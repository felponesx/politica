"""Coletor da Câmara dos Deputados — https://dadosabertos.camara.leg.br/swagger/api.html"""
from datetime import date

import httpx

from app import http
from app.collectors.base import marcar_em_exercicio, registrar_coleta
from app.models import Despesa, Parlamentar, Proposicao, Registro, Votacao, Voto
from app.utils import so_digitos, extrair_materia, extrair_placar, hash_curto, meses, para_data, para_float, upsert

BASE = "https://dadosabertos.camara.leg.br/api/v2"
CASA = "camara"


def paginar(caminho: str, params: dict | None = None):
    """Segue os links rel=next da API até acabar."""
    url, params = f"{BASE}{caminho}", dict(params or {})
    while url:
        resp = http.get_json(url, params=params) or {}
        params = None  # o link "next" já traz os parâmetros
        yield from resp.get("dados", [])
        url = next((l["href"] for l in resp.get("links", []) if l.get("rel") == "next"), None)


def _deputado(db, d: dict) -> Parlamentar:
    return upsert(db, Parlamentar, {"casa": CASA, "id_externo": str(d["id"])}, {
        "nome": d.get("nome") or d.get("nomeCivil") or "",
        "partido": d.get("siglaPartido"),
        "uf": d.get("siglaUf"),
        "foto_url": d.get("urlFoto"),
        "email": d.get("email"),
    })


def coletar_deputados():
    with registrar_coleta("camara", "deputados") as (db, n):
        vistos = set()
        for d in paginar("/deputados", {"itens": 100, "ordem": "ASC", "ordenarPor": "nome"}):
            _deputado(db, d)
            vistos.add(str(d["id"]))
            n += 1
        marcar_em_exercicio(db, CASA, vistos, minimo=400)  # a Câmara tem 513 cadeiras
    return n.itens


def coletar_proposicoes(inicio: date, fim: date, tipos: list[str] | None = None):
    """Proposições apresentadas no período. `tipos` (ex.: PEC,PLP,MPV) limita a coleta aos tipos pedidos: serve para o
    histórico longo, em que tudo (requerimentos, indicações) seria grande demais."""
    with registrar_coleta("camara", "proposicoes", inicio=inicio, fim=fim, tipos=",".join(tipos or [])) as (db, n):
        for ini, f in meses(inicio, fim):
            for p in paginar("/proposicoes", {
                "dataApresentacaoInicio": ini.isoformat(), "dataApresentacaoFim": f.isoformat(),
                "itens": 100, "ordem": "ASC", "ordenarPor": "id",
                **({"siglaTipo": ",".join(tipos)} if tipos else {}),
            }):
                upsert(db, Proposicao, {"casa": CASA, "id_externo": str(p["id"])}, {
                    "sigla_tipo": p.get("siglaTipo"),
                    "numero": str(p.get("numero") or ""),
                    "ano": p.get("ano"),
                    "ementa": p.get("ementa"),
                    "data_apresentacao": para_data(p.get("dataApresentacao")),
                })
                n += 1
            db.commit()
    return n.itens


def coletar_votacoes(inicio: date, fim: date, com_votos: bool = True):
    """Votações (plenário e comissões) + voto de cada deputado."""
    with registrar_coleta("camara", "votacoes", inicio=inicio, fim=fim) as (db, n):
        for ini, f in meses(inicio, fim):
            for v in paginar("/votacoes", {"dataInicio": ini.isoformat(), "dataFim": f.isoformat(),
                                           "itens": 200, "ordem": "ASC", "ordenarPor": "dataHoraRegistro"}):
                aprov = v.get("aprovacao")
                votacao = upsert(db, Votacao, {"casa": CASA, "id_externo": str(v["id"])}, {
                    "data": para_data(v.get("data") or v.get("dataHoraRegistro")),
                    "orgao": v.get("siglaOrgao"),
                    "descricao": v.get("descricao"),
                    # proposicaoObjeto costuma vir vazio; a matéria e o placar estão no texto da descrição
                    "materia": v.get("proposicaoObjeto") or extrair_materia(v.get("descricao")),
                    "placar_oficial": extrair_placar(v.get("descricao")),
                    "resultado": None if aprov is None else ("Aprovada" if aprov else "Rejeitada"),
                })
                db.flush()
                n += 1
                if com_votos:
                    try:
                        votos = http.get_json(f"{BASE}/votacoes/{v['id']}/votos") or {}
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code != 404:
                            raise
                        votos = {}  # votação simbólica: a API responde 404 em vez de lista vazia
                    for voto in votos.get("dados", []):
                        dep = voto.get("deputado_") or {}
                        if not dep.get("id"):
                            continue
                        parl = _deputado(db, dep)
                        db.flush()
                        upsert(db, Voto, {"votacao_id": votacao.id, "parlamentar_id": parl.id}, {
                            "voto": voto.get("tipoVoto") or "?",
                            "partido_na_data": dep.get("siglaPartido"),
                        })
                db.commit()
    return n.itens


COTAS_URL = "https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip"


def ler_cotas(texto: str):
    """Linhas do arquivo anual da cota (CEAP): CSV com ';', aspas e cabeçalho (txNomeParlamentar, ideCadastro...).
    `ideCadastro` é o id do deputado na API de dados abertos; vem vazio nas notas de lideranças."""
    import csv
    import io
    for l in csv.DictReader(io.StringIO(texto.lstrip("\ufeff")), delimiter=";"):
        if (l.get("ideCadastro") or "").strip():
            yield l


def coletar_despesas(ano: int, apenas_ids: list[str] | None = None, arquivo_local: str | None = None):
    """Cota parlamentar (CEAP) dos deputados no ano.

    Usa o arquivo anual da Câmara (Ano-AAAA.csv.zip, um download): desde out/2026 o endpoint
    /deputados/{id}/despesas da API responde lista vazia. Recarga idempotente: apaga as notas do ano
    e grava de novo. Notas de lideranças (sem deputado) ficam de fora. Liga pelo `ideCadastro` do arquivo.
    """
    import os
    import tempfile
    import zipfile

    from sqlalchemy import delete
    with registrar_coleta("camara", "despesas", ano=ano) as (db, n):
        caminho = arquivo_local or http.baixar(COTAS_URL.format(ano=ano), os.path.join(tempfile.gettempdir(), f"cotas_{ano}.zip"))
        with zipfile.ZipFile(caminho) as z:
            nome = next(m for m in z.namelist() if m.lower().endswith(".csv"))
            texto = z.read(nome).decode("utf-8-sig", errors="replace")
        deputados = {d.id_externo: d for d in db.query(Parlamentar).filter_by(casa=CASA)}
        if apenas_ids:
            deputados = {k: v for k, v in deputados.items() if k in apenas_ids}
        notas = {}
        for l in ler_cotas(texto):
            dep = deputados.get(l["ideCadastro"].strip())
            if not dep:
                continue
            id_ext = (l.get("ideDocumento") or "").strip() or hash_curto(
                l.get("txtNumero"), l.get("datEmissao"), l.get("vlrLiquido"), l.get("txtCNPJCPF"), l.get("numParcela"))
            chave = (dep.id, id_ext[:80])
            if chave in notas:  # parcelas e restituições repetem o documento: os valores se somam
                notas[chave]["valor"] = round(notas[chave]["valor"] + (para_float(l.get("vlrLiquido")) or 0.0), 2)
                continue
            notas[chave] = {"parlamentar_id": dep.id, "id_externo": id_ext[:80], "ano": int(l.get("numAno") or ano),
                           "mes": int(l["numMes"]) if (l.get("numMes") or "").strip().isdigit() else None,
                           "tipo": (l.get("txtDescricao") or "")[:200] or None,
                           "fornecedor": (l.get("txtFornecedor") or "")[:300] or None,
                           "cnpj_cpf": so_digitos(l.get("txtCNPJCPF")) or None,
                           "valor": para_float(l.get("vlrLiquido")) or 0.0,
                           "url_documento": (l.get("urlDocumento") or "")[:500] or None}
        linhas = list(notas.values())
        ids = [d.id for d in deputados.values()]
        db.execute(delete(Despesa).where(Despesa.ano == ano, Despesa.parlamentar_id.in_(ids or [0])))
        for i in range(0, len(linhas), 5000):
            db.bulk_insert_mappings(Despesa, linhas[i:i + 5000])
        db.commit()
        n += len(linhas)
    return n.itens


def coletar_orgaos():
    """Órgãos da Câmara (comissões, plenário, CPIs...)."""
    with registrar_coleta("camara", "orgaos") as (db, n):
        for o in paginar("/orgaos", {"itens": 100}):
            upsert(db, Registro, {"fonte": "camara", "tipo": "orgao", "chave": str(o["id"])}, {
                "titulo": o.get("nome"), "dados": o,
            })
            n += 1
    return n.itens
