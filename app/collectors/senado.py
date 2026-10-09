"""Coletor do Senado Federal — https://legis.senado.leg.br/dadosabertos/api-docs/swagger-ui/index.html

A API do Senado devolve JSON aninhado e às vezes troca lista por objeto único,
por isso o uso defensivo de `como_lista`, `cavar` e `primeiro`.
"""
from datetime import date

from app import http
from app.collectors.base import registrar_coleta
from app.models import Parlamentar, Proposicao, Votacao, Voto
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
        for p in como_lista(cavar(dados, "ListaParlamentarEmExercicio", "Parlamentares", "Parlamentar")):
            i = p.get("IdentificacaoParlamentar", p)
            _senador(db, i.get("CodigoParlamentar"), i.get("NomeParlamentar"),
                     i.get("SiglaPartidoParlamentar"), i.get("UfParlamentar"),
                     i.get("UrlFotoParlamentar"), i.get("EmailParlamentar"))
            n += 1
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
