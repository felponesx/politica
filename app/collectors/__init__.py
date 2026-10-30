"""Registro de todas as tarefas de coleta (usado pela CLI e pela API)."""
from app.collectors import (tse_doadores, inep_igc, prf, servidores, orientacoes, queimadas, ibama, trabalho_escravo, renuncia, anac, cpis, anp, anatel, cnj, tcu, social, ambiente, economia_extra, sancoes, inep, datasus, saude, cartao, emendas, bcb_financeiro, agenda, assembleias, saneamento, isp_rj, empresas_porte, ibge_empresas, bcb, malhas, camara, capag, cnpj, cnpj_base, congresso_extra, seguranca, noticias, orcamento, bcb_scr, desastres, ibge, legislacao, lexml,
                            municipios, tse_financas, obrasgov, pgfn, pncp,
                            receita, senado, siconfi, tesouro, transparencia, tse, tse_resultados)

_TAREFAS_BRUTAS = {
    "ensino-ideb": inep.coletar_ensino_ideb,
    "tse-doadores": tse_doadores.coletar_tse_doadores,   # ano, uf
    "inep-igc": inep_igc.coletar_inep_igc,   # edicoes
    "cgu-sancoes": sancoes.coletar_sancoes,
    "tcu-inabilitados": tcu.coletar_tcu_inabilitados,
    "cnj-justica": cnj.coletar_cnj_justica,
    "anatel-banda-larga": anatel.coletar_anatel_banda_larga,
    "anp-combustiveis": anp.coletar_anp_combustiveis,
    "congresso-cpis": cpis.coletar_cpis,
    "anac-aerodromos": anac.coletar_anac_aerodromos,
    "ibama-multas": ibama.coletar_ibama_multas,
    "inpe-queimadas": queimadas.coletar_queimadas,
    "tcu-contas-irregulares": tcu.coletar_tcu_irregulares,
    "mte-lista-suja": trabalho_escravo.coletar_lista_suja,
    "receita-renuncia-fiscal": renuncia.coletar_renuncia_fiscal,
    "transparencia-social": social.coletar_social,
    "transparencia-viagens": social.coletar_viagens,       # anos
    "transparencia-servidores": servidores.coletar_servidores,   # meses
    "prf-acidentes": prf.coletar_prf_acidentes,   # anos
    "camara-orientacoes": orientacoes.coletar_camara_orientacoes,   # ano_inicial, ano_final
    "inpe-desmatamento": ambiente.coletar_desmatamento,
    "ibge-trabalho": economia_extra.coletar_trabalho,      # trimestres
    "tse-fundos": economia_extra.coletar_fundos,
    "aneel-tarifas": economia_extra.coletar_tarifas_energia,
    "ibge-saneamento": saneamento.coletar_saneamento,
    "ibge-empresas-economia": ibge_empresas.coletar_empresas_economia,  # ano
    "camara-deputados": camara.coletar_deputados,
    "camara-proposicoes": camara.coletar_proposicoes,      # inicio, fim
    "camara-votacoes": camara.coletar_votacoes,            # inicio, fim
    "camara-despesas": camara.coletar_despesas,            # ano
    "camara-orgaos": camara.coletar_orgaos,
    "senado-senadores": senado.coletar_senadores,
    "senado-votacoes": senado.coletar_votacoes,            # inicio, fim
    "senado-materias": senado.coletar_materias,            # ano, sigla
    "senado-situacao": senado.situacao_materias,           # desde (ano), siglas
    "bcb-financeiro": bcb_financeiro.coletar_sistema_financeiro,  # ano (opcional): bancos e crédito (IF.data + SGS)
    "ibge-indicadores": ibge.coletar_indicadores,          # periodos
    "siconfi-receitas": siconfi.coletar_receitas_estados,  # ano, bimestre
    "siconfi-divida": siconfi.coletar_divida_estados,      # ano, quadrimestre
    "pncp-contratos": pncp.coletar_contratos,              # inicio, fim
    "transparencia-orgaos": transparencia.coletar_orgaos,
    "transparencia-contratos": transparencia.coletar_contratos,  # codigo_orgao, inicio, fim
    "transparencia-gastos": transparencia.coletar_gastos_por_orgao,  # ano, orgao_superior
    "obrasgov-obras": obrasgov.coletar_obras,
    "tse-candidatos": tse.coletar_candidatos,              # ano, uf
    "tse-resultados": tse_resultados.coletar_resultados,  # ano, uf, arquivo_local
    "receita-arrecadacao": receita.coletar_arrecadacao_estados,  # ano_minimo, arquivo_local
    "legislacao-normas": legislacao.coletar_normas,          # ano, tipos
    "camara-proposicoes-detalhe": legislacao.enriquecer_proposicoes_camara,  # ano
    "camara-proposicoes-situacao": legislacao.situacao_proposicoes_camara,  # ano ou desde (arquivo anual)
    "tesouro-transferencias": tesouro.coletar_transferencias,    # ano
    # v0.2
    "ibge-municipios": municipios.coletar_municipios,
    "ibge-indicadores-sociais": municipios.coletar_indicadores_sociais,  # periodos, nomes
    "indicador-arquivo": municipios.importar_indicador_arquivo,        # arquivo, nome, descricao, ano, unidade, fonte
    "siconfi-despesas-funcao": siconfi.coletar_despesas_funcao,        # ano, bimestre, esferas=U,E,C
    "siconfi-tributos": siconfi.coletar_tributos_entes,              # ano, bimestre, esferas=E,M (impostômetro)
    "transparencia-gastos-todos": transparencia.coletar_gastos_todos_orgaos,  # ano
    "pgfn-divida-ativa": pgfn.coletar_divida_ativa,                    # ano, trimestre, tipos, arquivo_local
    "tesouro-capag": capag.coletar_capag,                              # arquivo_local, url, ano
    "cnpj-fornecedores": cnpj.coletar_cnpj_fornecedores,               # limite, dias
    "desastres": desastres.importar_desastres,                         # arquivo_local, url, fonte
    "lexml-estaduais": lexml.coletar_estaduais,                        # ano, ufs
    # v0.3
    "bcb-series": bcb.coletar_series,                                  # anos, nomes
    "congresso-agenda": agenda.coletar_agenda,                         # dia
    "camara-tramitacoes": congresso_extra.coletar_tramitacoes,         # ano, limite, dias
    "congresso-atuacao": congresso_extra.coletar_atuacao,
    "senado-ceaps": congresso_extra.coletar_ceaps,                     # ano
    "tse-bens": tse_financas.coletar_bens,                             # ano, uf, arquivo_local
    "tse-contas": tse_financas.coletar_contas,                         # ano, uf, arquivo_local
    "assembleias": assembleias.coletar_assembleias,                    # ufs, inicio, fim
    "assembleia-arquivo": assembleias.importar_deputados_arquivo,      # uf, arquivo
    "ibge-malhas": malhas.coletar_malhas,                              # ufs, qualidade
    # v0.5
    "receita-recuperacao-judicial": cnpj_base.coletar_recuperacao_judicial,  # mes (AAAA-MM), minutos, pasta_local
    "seguranca-prisional": seguranca.coletar_sisdepen,                 # url, arquivo_local
    "seguranca-anuario": seguranca.coletar_anuario,                    # url, arquivo_local
    "seguranca-sinesp": seguranca.coletar_sinesp,                      # ano, arquivo_local
    "seguranca-efetivo": seguranca.coletar_raiox,                      # ano, url, arquivo_local
    "receita-empresas-porte": empresas_porte.coletar_empresas_porte,     # mes, ano+trimestre (PGFN), minutos
    "isp-rj-batalhoes": isp_rj.coletar_isp_aisp,                       # arquivo_local (ISP-RJ por área de batalhão)
    "noticias-politica": noticias.coletar_noticias,                    # dias
    "transparencia-orcamento": orcamento.coletar_orcamento_orgaos,     # ano (sem chave)
    "transparencia-emendas": emendas.coletar_emendas,                  # sem parâmetros (arquivo único, sem chave)
    "transparencia-cartao": cartao.coletar_cartao,                     # ano (cartão corporativo, sem chave)
    "bcb-scr-estados": bcb_scr.coletar_scr_uf,                         # ano (mês mais recente do SCR.data)
    "saude-ubs": saude.coletar_ubs,                                    # Unidades Básicas de Saúde por município (CNES)
    "saude-mais-medicos": saude.coletar_mais_medicos,                  # vagas do Mais Médicos por município
    "saude-datasus": datasus.coletar_saude_datasus,                    # leitos, UTI, médicos e mortalidade infantil por estado (TabNet)
}


# tarefas que, ao terminar, refazem as ligações entre bases (app/ligacoes.py)
LIGAM = {"camara-votacoes", "camara-proposicoes", "senado-votacoes", "senado-materias", "tse-candidatos",
         "camara-deputados", "senado-senadores", "camara-proposicoes-detalhe", "assembleias", "assembleia-arquivo"}


def _com_normalizacao(nome, fn):
    """Depois da coleta, atualiza as tabelas normalizadas da fonte correspondente."""
    import functools

    from app.normalizar import FONTE_PARA_PROJECAO, normalizar

    projecoes = FONTE_PARA_PROJECAO.get(nome.split("-")[0])
    ligar = nome in LIGAM
    if not projecoes and not ligar:
        return fn

    @functools.wraps(fn)
    def tarefa(*args, **kwargs):
        itens = fn(*args, **kwargs)
        if projecoes:
            normalizar(projecoes)
        if ligar:
            from app.ligacoes import ligar_tudo
            ligar_tudo()
        return itens
    return tarefa


TAREFAS = {nome: _com_normalizacao(nome, fn) for nome, fn in _TAREFAS_BRUTAS.items()}
