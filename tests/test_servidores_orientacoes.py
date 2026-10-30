import io
import zipfile

from app.collectors import orientacoes, servidores
from app import orientacao


def _zip():
    cad = ('"Id_SERVIDOR_PORTAL";"NOME";"COD_ORG_EXERCICIO";"ORG_EXERCICIO";"ORGSUP_EXERCICIO";"UF_EXERCICIO"\n'
           '"1";"A";"26405";"Instituto X";"MEC";"CE"\n"2";"B";"26405";"Instituto X";"MEC";"CE"\n"3";"C";"25000";"Saúde";"Saúde";"SP"\n')
    rem = ('"ANO";"MES";"Id_SERVIDOR_PORTAL";"REMUNERAÇÃO BÁSICA BRUTA (R$)";"ABATE-TETO (R$)";"REMUNERAÇÃO APÓS DEDUÇÕES OBRIGATÓRIAS (R$)"\n'
           '"2026";"08";"1";"10.000,50";"0,00";"8.000,00"\n"2026";"08";"2";"50.000,00";"-3.633,81";"40.000,00"\n"2026";"08";"3";"5.000,00";"0,00";"4.000,00"\n')
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("202608_Cadastro.csv", cad.encode("latin-1"))
        z.writestr("202608_Remuneracao.csv", rem.encode("latin-1"))
    return zipfile.ZipFile(io.BytesIO(b.getvalue()))


def test_servidores_liga_cadastro_e_remuneracao_sem_dado_pessoal():
    d = servidores.resumir(servidores.agregar(_zip()), "202608")
    assert d["servidores"] == 3 and d["sem_cadastro"] == 0
    x = next(o for o in d["orgaos"] if o["codigo"] == "26405")
    assert x["n"] == 2 and x["bruta"] == 60000.5 and x["acima_teto"] == 1 and x["cortados_pelo_teto"] == 1 and x["abate_teto"] == -3633.81
    assert d["ufs"]["SP"]["n"] == 1
    assert "NOME" not in str(d) and '"A"' not in str(d)


def test_orientacoes_agrupa_por_votacao_e_mantem_vazio_como_sem_orientacao():
    g = orientacoes.agrupar([{"idVotacao": "1-2", "siglaBancada": "PL", "orientacao": "Sim", "siglaOrgao": "PLEN"},
                             {"idVotacao": "1-2", "siglaBancada": "PT", "orientacao": ""}, {"idVotacao": "", "siglaBancada": "X"}])
    assert list(g) == ["1-2"] and g["1-2"]["bancadas"] == {"PL": "Sim", "PT": ""}
    assert orientacao._chave("Podemos") == "PODE" and orientacao._voto("Não") == "Não"


def test_prf_descobre_links_pelo_titulo_sem_ligar_nada_a_mao():
    from app.collectors import prf
    pagina = ('Documento CSV de Acidentes 2025 (Agrupados por ocorrência) <a href="https://drive.google.com/file/d/AAA/view?usp=sharing/download">Baixar planilha</a>'
              'Documento CSV de Acidentes 2025 (Agrupados por pessoa) <a href="https://drive.google.com/file/d/BBB/view">Baixar planilha</a>'
              'Documento CSV de Acidentes 2024 (Agrupados por ocorrência) <a href="https://drive.google.com/file/d/CCC/view">Baixar planilha</a>')
    assert prf.descobrir(pagina) == {2025: "AAA", 2024: "CCC"}


def test_igc_acha_abas_e_link_do_ano():
    from app.collectors import inep_igc
    assert inep_igc.abas('<a data-id="2023"></a><a data-id="2025"></a>') == [2025, 2023]
    assert inep_igc.link_igc('<a href="https://download.inep.gov.br/x/2023/IGC_2023.xlsx">a</a><a href="https://download.inep.gov.br/x/2023/CPC_2023.xlsx">b</a>', 2023).endswith("IGC_2023.xlsx")
    assert inep_igc.link_igc('<a href="https://download.inep.gov.br/x/conceito_enade_2025.xlsx">a</a>', 2025) is None


def test_doadores_so_cnpj_e_data_com_ano_plausivel():
    from datetime import date
    from app.collectors import tse_doadores as t
    linhas = [{"sequencial_candidato": "10", "sg_uf": "SP", "cpf_cnpj_do_doador": "12.345.678/0001-90", "nome_do_doador_receita_federal": "EMPRESA X", "sigla_partido": "PT",
               "valor_receita": "100,50", "data_da_receita": "10/10/201400:00:00", "tipo_receita": "Recursos de pessoas jurídicas", "cargo": "Deputado Federal"},
              {"sequencial_candidato": "10", "sg_uf": "SP", "cpf_cnpj_do_doador": "12345678000190", "valor_receita": "50", "data_da_receita": "10/10/0014", "tipo_receita": "Recursos de pessoas jurídicas"},
              {"sequencial_candidato": "10", "sg_uf": "SP", "cpf_cnpj_do_doador": "12345678901", "valor_receita": "999", "tipo_receita": "Recursos de pessoas físicas"}]
    ag, n = t.agregar(linhas, 2014)
    assert n == 2 and len(ag) == 1
    e = next(iter(ag.values()))
    assert e["valor"] == 150.5 and e["n"] == 2 and e["ini"] == date(2014, 10, 10) and e["doador"] == "EMPRESA X"
    assert t.tipo_doador("Recursos de pessoas jurídicas") == "empresa" and t.tipo_doador("Recursos de partido político") == "partido_ou_comite" and t.tipo_doador("Em espécie") == "cnpj_sem_tipo"


def test_transito_malha_conta_cada_via_uma_vez_e_calcula_km_pela_geometria():
    from app.collectors import transito as t
    a = {"type": "way", "id": 1, "tags": {"highway": "primary", "name": "Av. Brasil"}, "geometry": [{"lat": 0.0, "lon": 0.0}, {"lat": 0.0, "lon": 0.01}]}
    els = [a, dict(a), {"type": "way", "id": 2, "tags": {"highway": "residential"}, "geometry": [{"lat": 0.0, "lon": 0.0}, {"lat": 0.001, "lon": 0.0}]},
           {"type": "way", "id": 3, "tags": {}, "geometry": [{"lat": 0, "lon": 0}, {"lat": 1, "lon": 1}]}]
    d = t.resumir_malha(els)
    assert d["trechos"] == 2 and d["vias_nomeadas"] == 1
    assert d["por_categoria"]["Arteriais"]["km"] == 1.1 and d["por_categoria"]["Locais"]["km"] == 0.1


def test_tomtom_ler_fluxo_e_incidentes_e_exige_chave(monkeypatch):
    import pytest
    from app.collectors import transito as t
    f = t.ler_fluxo({"flowSegmentData": {"currentSpeed": 20, "freeFlowSpeed": 40, "currentTravelTime": 100, "freeFlowTravelTime": 50, "confidence": 0.9}})
    assert f["congestionamento_pct"] == 50.0 and t.ler_fluxo({}) is None
    assert t.ler_incidentes({"incidents": [{"properties": {"iconCategory": 6, "delay": 120}}, {"properties": {"iconCategory": 6}}]}) == {"incidentes": 2, "por_categoria_tomtom": {"6": 2}, "atraso_total_s": 120}
    monkeypatch.setattr(t.settings, "tomtom_api_key", "")
    with pytest.raises(RuntimeError, match="TOMTOM_API_KEY"):
        t.coletar_tomtom_transito()


def test_querido_diario_usa_endereco_com_certificado_valido_e_enxuga_resposta(monkeypatch):
    from app.collectors import querido_diario as qd
    assert qd.BASE.startswith("https://queridodiario.ok.org.br/api") and "api.queridodiario" not in qd.BASE
    r = qd._enxugar({"total_gazettes": 10000, "gazettes": [{"territory_name": "X", "state_code": "SP", "territory_id": "3509502", "date": "2026-10-01", "url": "https://u", "excerpts": ["a" * 900]}]})
    assert r["limitado"] is True and r["diarios"][0]["uf"] == "SP" and len(r["diarios"][0]["trechos"][0]) == 400


def test_ocorrencias_vem_dos_casos_com_fonte_e_classifica_so_com_palavra_clara():
    from app import ocorrencias as oc
    assert oc.classificar("TRF-1 arquiva ação penal contra X por falta de provas.") == "arquivamento"
    assert oc.classificar("STF condena fulano a 10 anos.") == "condenacao"
    assert oc.classificar("MPF apresenta denúncia contra 5 pessoas.") == "denuncia"
    assert oc.classificar("PF deflagra a Operação Zelotes.") == "investigacao"
    assert oc.classificar("Fulano se reúne com o ministro.") == "outra"
    d = oc.listar(limit=500)
    assert d["total"] >= 100 and all(i["fonte_url"].startswith("http") for i in d["ocorrencias"]) and "presumidos inocentes" in d["aviso"]


def test_caged_agrega_so_contagens_por_uf_e_secao_e_le_7z(tmp_path):
    import py7zr
    from app.collectors import caged
    cab = "competênciamov;região;uf;município;seção;subclasse;saldomovimentação;cbo2002ocupação;salário\n"
    corpo = "202608;3;35;355030;G;4711;1;411010;1500,00\n202608;3;35;355030;G;4711;-1;411010;1500,00\n202608;3;35;355030;C;1011;1;411010;2000,00\n202608;1;99;1;G;1;1;1;1\n"
    arq = tmp_path / "CAGEDMOV202608.txt"
    arq.write_text(cab + corpo, encoding="latin-1")
    z = tmp_path / "CAGEDMOV202608.7z"
    with py7zr.SevenZipFile(z, "w") as w:
        w.write(arq, arq.name)
    cabecalho, linhas, pasta, fh = caged.ler_7z(z)
    ag = caged.agregar(linhas, cabecalho)
    fh.close()
    sp = ag["competencias"]["202608"]["SP"]
    assert ag["linhas"] == 3 and sp["adm"] == 2 and sp["desl"] == 1 and sp["secoes"]["G"] == [1, 1]
    d = caged.resumir({"CAGEDMOV": ag, "CAGEDFOR": {"linhas": 0, "competencias": {}}, "CAGEDEXC": {"linhas": 0, "competencias": {}}}, "202608")
    assert d["brasil"]["saldo_mov"] == 1 and "salario" not in str(d).lower() and d["por_uf"]["SP"]["por_secao"]["C"]["setor"] == "Indústria de transformação"


def test_ufs_do_robo_aceita_lista_e_texto():
    from app.collectors import transito as t
    assert t._lista_ufs(["TO", "DF"]) == ["TO", "DF"] and t._lista_ufs("to, df") == ["TO", "DF"] and t._lista_ufs("") == [] and t._lista_ufs("XX") == []


def test_caged_le_arquivo_em_utf8_e_em_latin1(tmp_path):
    import py7zr
    from app.collectors import caged
    for enc in ("utf-8", "latin-1"):
        arq = tmp_path / f"CAGEDMOV{enc}.txt"
        arq.write_text("competênciamov;região;uf;município;seção;subclasse;saldomovimentação\n202608;3;35;1;G;1;1\n", encoding=enc)
        z = tmp_path / f"{enc}.7z"
        with py7zr.SevenZipFile(z, "w") as w:
            w.write(arq, arq.name)
        cab, linhas, pasta, fh = caged.ler_7z(z)
        ag = caged.agregar(linhas, cab)
        fh.close()
        assert ag["linhas"] == 1, enc


def test_reforma_monitor_acha_coluna_cbs_ibs_e_diz_quando_nao_ha():
    from app.collectors import reforma
    sem = "Ano;Mês;UF;COFINS;CSLL\n2026;Setembro;SP;1.000,00;2.000,00\n"
    d = reforma.analisar_planilha(sem)
    assert d["colunas_cbs_ibs"] == [] and d["ultimo_mes"] == "2026-09"
    com = "Ano;Mês;UF;COFINS;CBS;IBS - ESTADOS\n2026;Setembro;SP;1.000,00;50,5;10,25\n2026;Setembro;RJ;1;49,5;0\n"
    d = reforma.analisar_planilha(com)
    assert d["colunas_cbs_ibs"] == ["CBS", "IBS - ESTADOS"] and d["total_por_mes"]["2026-09"]["CBS"] == 100.0
    assert "COFINS" not in str(d["colunas_cbs_ibs"])
    html = '<a href="/upload/arquivos/202607/x-resolucao-10.pdf">Resolução 10</a><a href="https://x.gov.br/a.xlsx"> Arrecadação do IBS </a>'
    a = reforma.arquivos_cgibs(html)
    assert a[0]["url"].startswith("https://www.cgibs.gov.br/upload") and a[1]["titulo"] == "Arrecadação do IBS"


def test_tomtom_tem_ponto_central_para_todas_as_capitais():
    from app.collectors import transito as t
    assert set(t.CENTROS) == set(t.CAPITAIS)
    assert all(-34 < la < 6 and -75 < lo < -34 for la, lo in t.CENTROS.values())
