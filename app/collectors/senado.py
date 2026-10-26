"""Coletor do Senado Federal — https://legis.senado.leg.br/dadosabertos/api-docs/swagger-ui/index.html

A API do Senado devolve JSON aninhado e às vezes troca lista por objeto único,
por isso o uso defensivo de `como_lista`, `cavar` e `primeiro`.
"""
import re
from datetime import date

from sqlalchemy import select

from app import http
from app.collectors.base import marcar_em_exercicio, registrar_coleta
from app.models import Parlamentar, Proposicao, Registro, Votacao, Voto
import logging

from app.utils import achar_lista, cavar, como_lista, meses, para_data, pegar, primeiro, upsert

log = logging.getLogger("brasilplus.senado")

BASE = "https://legis.senado.leg.br/dadosabertos"
CASA = "senado"


def get(caminho: str, **params):
    return http.get_json(f"{BASE}{caminho}.json", params=params or None) or {}


def _senador(db, codigo, nome, partido=None, uf=None, foto=None, email=None) -> Parlamentar:
    valores = {"nome": nome or ""}
    if partido:
        valores["partido"] = partido
    if uf:
        valores["uf"] = uf
    if foto:
        valores["foto_url"] = foto
    if email:
        valores["email"] = email
    return upsert(db, Parlamentar, {"casa": CASA, "id_externo": str(codigo)}, valores)


def coletar_senadores():
    with registrar_coleta("senado", "senadores") as (db, n):
        dados = get("/senador/lista/atual")
        vistos = set()
        for p in como_lista(cavar(dados, "ListaParlamentarEmExercicio", "Parlamentares", "Parlamentar")):
            i = p.get("IdentificacaoParlamentar", p)
            _senador(db, i.get("CodigoParlamentar"), i.get("NomeParlamentar"),
                     i.get("SiglaPartidoParlamentar"), i.get("UfParlamentar"),
                     i.get("UrlFotoParlamentar"), i.get("EmailParlamentar"))
            vistos.add(str(i.get("CodigoParlamentar")))
            n += 1
        marcar_em_exercicio(db, CASA, vistos, minimo=70)  # o Senado tem 81 cadeiras
    return n.itens


RESULTADOS = {"A": "Aprovada", "R": "Rejeitada"}
VOTOS_VALIDOS = {"Sim", "Não", "Abstenção", "Obstrução", "Votou", "Presidente (art. 51 RISF)"}


def _lista_votacoes(ini: date, f: date) -> list[dict]:
    """Serviço novo (/votacao, lista JSON em camelCase) como principal;
    o antigo (/plenario/lista/votacao, descontinuado pelo Senado) como reserva."""
    try:
        dados = http.get_json(f"{BASE}/votacao.json", params={"dataInicio": f"{ini:%Y-%m-%d}", "dataFim": f"{f:%Y-%m-%d}"})
        if isinstance(dados, list):
            return dados
        return achar_lista(dados, ("codigoSessaoVotacao", "codigoVotacao"))
    except Exception as e:
        log.warning("Serviço /votacao falhou (%s); usando o antigo", e)
        dados = get(f"/plenario/lista/votacao/{ini:%Y%m%d}/{f:%Y%m%d}")
        return como_lista(cavar(dados, "ListaVotacoes", "Votacoes", "Votacao"))


def coletar_votacoes(inicio: date, fim: date):
    """Votações nominais do plenário com o voto de cada senador.
    O Senado aceita no máximo 60 dias por consulta; usamos janelas mensais.
    Em votação secreta o voto individual vem só como "Votou"."""
    with registrar_coleta("senado", "votacoes", inicio=inicio, fim=fim) as (db, n):
        for ini, f in meses(inicio, fim):
            for v in _lista_votacoes(ini, f):
                codigo = pegar(v, "CodigoSessaoVotacao", "codigoSessaoVotacao", "CodigoVotacao", "codigoVotacao")
                if not codigo:
                    continue
                sigla, num, ano = pegar(v, "SiglaMateria", "sigla"), pegar(v, "NumeroMateria", "numero"), pegar(v, "AnoMateria", "ano")
                materia = pegar(v, "identificacao", "DescricaoIdentificacaoMateria") or (f"{sigla} {num}/{ano}" if sigla else None)
                resultado = pegar(v, "Resultado", "resultadoVotacao", "resultado")
                votacao = upsert(db, Votacao, {"casa": CASA, "id_externo": str(codigo)}, {
                    "data": para_data(pegar(v, "DataSessao", "dataSessao", "data")),
                    "orgao": "PLEN",
                    "descricao": pegar(v, "DescricaoVotacao", "descricaoVotacao", "descricao"),
                    "materia": materia,
                    "resultado": RESULTADOS.get(str(resultado).upper(), resultado) if resultado else None,
                    "ementa": pegar(v, "ementa", "EmentaMateria"),
                    "secreta": str(pegar(v, "votacaoSecreta", "Secreta") or "N").upper() in ("S", "SIM", "TRUE"),
                    "placar_oficial": {
                        "sim": int(pegar(v, "TotalVotosSim", "totalSim") or 0),
                        "nao": int(pegar(v, "TotalVotosNao", "totalNao") or 0),
                        "abstencao": int(pegar(v, "TotalVotosAbstencao", "totalAbstencao") or 0),
                    },
                })
                db.flush()
                n += 1
                votos = como_lista(cavar(v, "Votos", "VotoParlamentar")) or achar_lista(v.get("votos"), ("codigoParlamentar",))
                for vp in votos:
                    cod = pegar(vp, "CodigoParlamentar", "codigoParlamentar")
                    if not cod:
                        continue
                    partido = pegar(vp, "siglaPartidoParlamentar", "SiglaPartido")
                    parl = _senador(db, cod, pegar(vp, "NomeParlamentar", "nomeParlamentar"),
                                    partido, pegar(vp, "siglaUFParlamentar", "SiglaUF"), pegar(vp, "Foto"))
                    db.flush()
                    codigo_voto = pegar(vp, "siglaVotoParlamentar", "Voto", "SiglaVoto") or "?"
                    # códigos como "AP" (atividade parlamentar) viram o texto descritivo
                    texto = codigo_voto if codigo_voto in VOTOS_VALIDOS else (pegar(vp, "descricaoVotoParlamentar", "DescricaoVoto") or codigo_voto)
                    upsert(db, Voto, {"votacao_id": votacao.id, "parlamentar_id": parl.id}, {
                        "voto": str(texto)[:40], "partido_na_data": partido,
                    })
            db.commit()
    return n.itens


def coletar_materias(ano: int, sigla: str = "PL"):
    """Matérias (projetos) apresentadas no Senado em um ano."""
    with registrar_coleta("senado", "materias", ano=ano, sigla=sigla) as (db, n):
        dados = get("/materia/pesquisa/lista", sigla=sigla, ano=ano)
        for m in como_lista(cavar(dados, "PesquisaBasicaMateria", "Materias", "Materia")):
            ident = m.get("IdentificacaoMateria", m)
            dados_basicos = m.get("DadosBasicosMateria", m)
            codigo = primeiro(ident, "CodigoMateria", "Codigo")
            if not codigo:
                continue
            upsert(db, Proposicao, {"casa": CASA, "id_externo": str(codigo)}, {
                "sigla_tipo": primeiro(ident, "SiglaSubtipoMateria", "Sigla") or sigla,
                "numero": str(primeiro(ident, "NumeroMateria", "Numero") or ""),
                "ano": int(primeiro(ident, "AnoMateria", "Ano") or ano),
                "ementa": primeiro(dados_basicos, "EmentaMateria", "Ementa"),
                "data_apresentacao": para_data(primeiro(dados_basicos, "DataApresentacao", "Data")),
            })
            n += 1
    return n.itens


SIGLAS_SITUACAO = ("PL", "PLP", "PEC", "PDL", "PRS")
_IDENT = re.compile(r"^([A-Z]+)\s+(\d+)\s*/\s*(\d{4})")


def situacao_materias(desde: int | None = None, siglas: list[str] | None = None):
    """Situação atual de cada matéria do Senado (lista /processo, uma consulta por sigla e ano), com o texto de autoria.
    O ano corrente vem inteiro; os anos anteriores só com o que ainda tramita. Cria a matéria se ainda não estava no banco."""
    hoje = date.today().year
    with registrar_coleta("senado", "situacao", desde=desde or hoje) as (db, n):
        for ano in range(int(desde or hoje), hoje + 1):
            for sigla in siglas or SIGLAS_SITUACAO:
                params = {"sigla": sigla, "ano": ano}
                if ano < hoje:
                    params["tramitando"] = "S"
                try:
                    lista = http.get_json(f"{BASE}/processo", params=params, headers={"Accept": "application/json"}) or []
                except Exception as e:  # uma sigla/ano sem resposta não derruba o resto
                    log.warning("processos %s %s: %s", sigla, ano, e)
                    n.avisos.append(f"{sigla} {ano}: {e}")
                    continue
                for d in lista if isinstance(lista, list) else []:
                    codigo = d.get("codigoMateria")
                    m = _IDENT.match(str(d.get("identificacao") or ""))
                    if not codigo or not m:
                        continue
                    p = upsert(db, Proposicao, {"casa": CASA, "id_externo": str(codigo)}, {
                        "sigla_tipo": m.group(1), "numero": m.group(2), "ano": int(m.group(3)), "ementa": d.get("ementa"),
                        "data_apresentacao": para_data(d.get("dataApresentacao")),
                        "situacao": (d.get("situacaoAtual") or "")[:300] or None})
                    db.flush()
                    chave = {"fonte": "senado", "tipo": "tramitacao", "chave": str(p.id)}
                    if d.get("autoria") and not db.execute(select(Registro).filter_by(**chave)).scalar_one_or_none():
                        db.add(Registro(**chave, ano=p.ano, titulo=f"{p.sigla_tipo} {p.numero}/{p.ano}",
                                        dados={"passos": [], "autores": [{"nome": d["autoria"], "tipo": None}]}))
                    n += 1
                db.commit()
    return n.itens
