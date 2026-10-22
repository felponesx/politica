"""Complementos do Congresso:
- tramitação e autores das proposições da Câmara (/proposicoes/{id}/tramitacoes e /autores)
- atuação dos deputados: comissões (/deputados/{id}/orgaos) e discursos (/deputados/{id}/discursos)
- comissões dos senadores (/senador/{codigo}/comissoes)
- cota dos senadores (CEAPS) — API de dados abertos administrativos do Senado, com o CSV antigo como reserva
"""
import csv
import io
import logging
import time
from datetime import date, timedelta

from sqlalchemy import select

from app import http
from app.collectors import camara, senado
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Despesa, Parlamentar, Proposicao, Registro, Votacao
from app.utils import achar_lista, cavar, hash_curto, para_float, pegar, sem_acento, so_digitos, upsert

log = logging.getLogger("brasilplus.congresso")


def coletar_tramitacoes(ano: int | None = None, limite: int = 1500, dias: int = 7):
    """Tramitação e autores das proposições da Câmara: as que têm votação ligada e as mais recentes.
    Pula as atualizadas há menos de `dias`."""
    with registrar_coleta("camara", "tramitacoes", ano=ano or "recentes", limite=limite) as (db, n):
        stmt = select(Proposicao).where(Proposicao.casa.in_(["camara", "senado"]))
        if ano:
            stmt = stmt.where(Proposicao.ano == ano)
        com_voto = {pid for (pid,) in db.execute(select(Votacao.proposicao_id).where(Votacao.proposicao_id.isnot(None)))}
        props = sorted(db.scalars(stmt), key=lambda p: (p.id not in com_voto, -(p.ano or 0), -p.id))[:limite]
        recentes = {r.chave: r.atualizado_em for r in db.scalars(select(Registro).where(Registro.tipo == "tramitacao"))}
        corte = date.today() - timedelta(days=dias)
        for p in props:
            at = recentes.get(str(p.id))
            if at and at.date() >= corte:
                continue
            if p.casa == "senado":
                try:
                    passos, autores = tramitacao_senado(p.id_externo)
                except Exception as e:
                    log.info("Matéria do Senado %s: %s", p.id_externo, e)
                    continue
                upsert(db, Registro, {"fonte": "senado", "tipo": "tramitacao", "chave": str(p.id)},
                       {"ano": p.ano, "titulo": f"{p.sigla_tipo} {p.numero}/{p.ano}", "dados": {"passos": passos, "autores": autores}})
                if passos and passos[-1].get("situacao"):
                    p.situacao = passos[-1]["situacao"][:300]
                n += 1
                continue
            try:
                tram = (http.get_json(f"{camara.BASE}/proposicoes/{p.id_externo}/tramitacoes") or {}).get("dados", [])
                aut = (http.get_json(f"{camara.BASE}/proposicoes/{p.id_externo}/autores") or {}).get("dados", [])
            except Exception as e:
                log.warning("Proposição %s: %s", p.id_externo, e)
                continue
            passos = [{"data": t.get("dataHora"), "orgao": t.get("siglaOrgao"), "descricao": t.get("descricaoTramitacao"),
                       "situacao": t.get("descricaoSituacao"), "despacho": (t.get("despacho") or "")[:400]}
                      for t in sorted(tram, key=lambda t: (t.get("sequencia") or 0))]
            autores = [{"nome": a.get("nome"), "tipo": a.get("tipo"),
                        "id_externo": str(a.get("uri", "")).rstrip("/").rsplit("/", 1)[-1] if "deputados" in str(a.get("uri")) else None}
                       for a in aut]
            upsert(db, Registro, {"fonte": "camara", "tipo": "tramitacao", "chave": str(p.id)},
                   {"ano": p.ano, "titulo": f"{p.sigla_tipo} {p.numero}/{p.ano}",
                    "dados": {"passos": passos, "autores": autores}})
            if passos and passos[-1].get("situacao"):
                p.situacao = passos[-1]["situacao"][:300]
            n += 1
            if n.itens % 50 == 0:
                db.commit()
    return n.itens


def tramitacao_senado(codigo: str):
    """Movimentações e autoria de uma matéria do Senado (/materia/movimentacoes e /materia/autoria)."""
    movs = achar_lista(senado.get(f"/materia/movimentacoes/{codigo}"), ("DataTramitacao", "IdentificacaoTramitacao", "DataInformacao"))
    passos = []
    for m in movs:
        it = m.get("IdentificacaoTramitacao") if isinstance(m.get("IdentificacaoTramitacao"), dict) else m
        passos.append({"data": pegar(it, "DataTramitacao", "DataInformacao"),
                       "orgao": cavar(it, "OrigemTramitacao", "Local", "SiglaLocal") or cavar(it, "Local", "SiglaLocal"),
                       "descricao": pegar(it, "TextoTramitacao", "Descricao"),
                       "situacao": cavar(it, "Situacao", "DescricaoSituacao") or None, "despacho": ""})
    passos.sort(key=lambda x: str(x["data"] or ""))
    aut = achar_lista(senado.get(f"/materia/autoria/{codigo}"), ("NomeAutor",))
    autores = [{"nome": pegar(a, "NomeAutor"), "tipo": cavar(a, "SiglaTipoAutor") or pegar(a, "DescricaoTipoAutor"),
                "id_externo": cavar(a, "IdentificacaoParlamentar", "CodigoParlamentar"), "casa": "senado"} for a in aut]
    return passos, autores


def coletar_atuacao(dias_discursos: int = 365):
    """Comissões e discursos de cada deputado em exercício e comissões dos senadores."""
    ini = date.today() - timedelta(days=dias_discursos)
    with registrar_coleta("congresso", "atuacao") as (db, n):
        for p in db.scalars(select(Parlamentar).where(Parlamentar.em_exercicio, Parlamentar.casa.in_(["camara", "senado"]))).all():
            try:
                if p.casa == "camara":
                    org = (http.get_json(f"{camara.BASE}/deputados/{p.id_externo}/orgaos",
                                         params={"itens": 100}) or {}).get("dados", [])
                    comissoes = [{"sigla": o.get("siglaOrgao"), "nome": o.get("nomePublicacao") or o.get("nomeOrgao"),
                                  "cargo": o.get("titulo"), "inicio": o.get("dataInicio"), "fim": o.get("dataFim")}
                                 for o in org if not o.get("dataFim") or str(o.get("dataFim")) >= date.today().isoformat()]
                    disc = list(camara.paginar(f"/deputados/{p.id_externo}/discursos",
                                               {"dataInicio": ini.isoformat(), "itens": 100, "ordem": "DESC", "ordenarPor": "dataHoraInicio"}))
                    dados = {"comissoes": comissoes, "discursos": len(disc),
                             "ultimos_discursos": [{"data": d.get("dataHoraInicio"), "tipo": d.get("tipoDiscurso"),
                                                    "resumo": (d.get("sumario") or d.get("transcricao") or "")[:300],
                                                    "video": cavar(d, "urlVideo") or d.get("urlAudio")} for d in disc[:10]]}
                else:
                    resp = senado.get(f"/senador/{p.id_externo}/comissoes")
                    lista = achar_lista(resp, ("SiglaComissao", "IdentificacaoComissao"))
                    dados = {"comissoes": [{"sigla": pegar(c, "SiglaComissao") or cavar(c, "IdentificacaoComissao", "SiglaComissao"),
                                            "nome": pegar(c, "NomeComissao") or cavar(c, "IdentificacaoComissao", "NomeComissao"),
                                            "cargo": pegar(c, "DescricaoParticipacao"), "inicio": pegar(c, "DataInicio"),
                                            "fim": pegar(c, "DataFim")} for c in lista if not pegar(c, "DataFim")],
                             "discursos": None, "ultimos_discursos": []}
                    try:
                        pron = achar_lista(senado.get(f"/senador/{p.id_externo}/discursos", dataInicio=f"{ini:%Y%m%d}"),
                                           ("CodigoPronunciamento", "DataPronunciamento"))
                        pron.sort(key=lambda d: str(pegar(d, "DataPronunciamento") or ""), reverse=True)
                        dados["discursos"] = len(pron)
                        dados["ultimos_discursos"] = [{"data": pegar(d, "DataPronunciamento"),
                                                       "tipo": cavar(d, "TipoUsoPalavra", "Descricao") or pegar(d, "TipoUsoPalavra"),
                                                       "resumo": (pegar(d, "TextoResumo", "Indexacao") or "")[:300]} for d in pron[:10]]
                    except Exception as e:
                        log.info("Discursos do senador %s indisponíveis: %s", p.nome, e)
            except Exception as e:
                log.warning("Atuação de %s: %s", p.nome, e)
                continue
            upsert(db, Registro, {"fonte": p.casa, "tipo": "atuacao", "chave": str(p.id)}, {"titulo": p.nome, "dados": dados})
            n += 1
            if n.itens % 25 == 0:
                db.commit()
            time.sleep(0.1)
    return n.itens


def _senador_por_nome(db):
    return {sem_acento(p.nome): p for p in db.scalars(select(Parlamentar).where(Parlamentar.casa == "senado"))}


def interpretar_ceaps_csv(texto: str):
    linhas = texto.splitlines()
    i = next((k for k, l in enumerate(linhas[:5]) if "SENADOR" in l.upper()), 0)
    for d in csv.DictReader(io.StringIO("\n".join(linhas[i:])), delimiter=";"):
        yield {k.strip().upper(): (v or "").strip() for k, v in d.items() if k}


def coletar_ceaps(ano: int):
    """Despesas da cota dos senadores (CEAPS) no ano."""
    with registrar_coleta("senado", "ceaps", ano=ano) as (db, n):
        por_nome = _senador_por_nome(db)
        por_cod = {p.id_externo: p for p in por_nome.values()}
        registros = []
        try:
            dados = http.get_json(settings.senado_ceaps_url.format(ano=ano)) or []
            for d in dados if isinstance(dados, list) else achar_lista(dados, ("codSenador", "nomeSenador")):
                registros.append({"cod": str(pegar(d, "codSenador") or ""), "nome": pegar(d, "nomeSenador"),
                                  "mes": pegar(d, "mes"), "tipo": pegar(d, "tipoDespesa"), "forn": pegar(d, "fornecedor"),
                                  "doc": pegar(d, "cpfCnpj"), "valor": para_float(pegar(d, "valorReembolsado")),
                                  "id": pegar(d, "id", "codDocumento", "documento")})
        except Exception as e:
            log.warning("API CEAPS indisponível (%s); tentando o CSV", e)
            texto = http.get(settings.senado_ceaps_csv.format(ano=ano)).content.decode("latin-1")
            for d in interpretar_ceaps_csv(texto):
                registros.append({"cod": "", "nome": d.get("SENADOR"), "mes": d.get("MES"), "tipo": d.get("TIPO_DESPESA"),
                                  "forn": d.get("FORNECEDOR"), "doc": d.get("CNPJ_CPF"), "valor": para_float(d.get("VALOR_REEMBOLSADO")),
                                  "id": d.get("COD_DOCUMENTO") or d.get("DOCUMENTO")})
        sem_par = set()
        for r in registros:
            p = por_cod.get(r["cod"]) or por_nome.get(sem_acento(r["nome"] or ""))
            if not p or r["valor"] is None:
                sem_par.add(r["nome"])
                continue
            upsert(db, Despesa, {"parlamentar_id": p.id, "id_externo": f"ceaps-{r['id'] or hash_curto(r)}"}, {
                "ano": ano, "mes": int(r["mes"]) if str(r["mes"] or "").isdigit() else None, "tipo": r["tipo"],
                "fornecedor": r["forn"], "cnpj_cpf": so_digitos(r["doc"]), "valor": r["valor"]})
            n += 1
            if n.itens % 1000 == 0:
                db.commit()
        if sem_par:
            log.info("CEAPS: %s senadores sem correspondência (ex-senadores ou nome diferente)", len(sem_par))
    return n.itens
