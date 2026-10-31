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


def test_caged_estoque_le_comunicado_secoes_e_total_confere():
    from app import lacunas
    from app.collectors import caged_estoque as ce
    html = "<p>o estoque de referência do Novo Caged em dezembro de 2025 foi atualizado para 47.110.663 vínculos . A partir</p>"
    assert ce.ler_comunicado(html, 2026) == {"competencia": "2025-12", "total_oficial": 47110663, "fonte_texto": True}
    assert ce.ler_comunicado("sem frase", 2026)["competencia"] == "2025-12"
    assert [lacunas.secao_da_divisao(d) for d in (1, 10, 47, 64, 85, 99, 4)] == ["A", "C", "G", "K", "P", "U", "Z"]


def test_fila_de_escandalos_le_data_real_ignora_comentario_e_nao_extrai_nomes():
    from app.collectors import escandalos_fila as f
    pagina = ('<meta property="og:title" content="PF deflagra operação X contra fraude" /><meta property="og:description" content="Cumpre mandados" />'
              '<span class="documentPublished"><span>Publicado em</span><!-- ex.: 15/10/2019 às 14:01 --><span class="value">30/10/2026 07h49</span></span>')
    a = f.ler_artigo(pagina)
    assert a == {"titulo": "PF deflagra operação X contra fraude", "resumo": "Cumpre mandados", "data": "2026-10-30"}
    item = f.montar(f.FONTES[0], {**a, "url": "https://www.gov.br/pf/pt-br/assuntos/noticias/2026/10/x"}, "2026-10-31T00:00:00")
    assert item["status_revisao"] == "pendente" and item["pessoas_ou_instituicoes"] == [] and item["etapa_sugerida"] == "investigacao" and item["situacao_atual"].startswith("Não verificada")
    assert f.links_da_lista('<a href="https://www.gov.br/pf/pt-br/assuntos/noticias/2026/10/a">1</a><a href="https://www.gov.br/pf/pt-br/assuntos/noticias/2026/10/a">2</a>', f.FONTES[0]["padrao"]) == ["https://www.gov.br/pf/pt-br/assuntos/noticias/2026/10/a"]
    assert [x["id"] for x in f.FONTES if not x.get("ativo", True)] == ["mpf", "stj", "tcu"]


def test_reforma_publicacoes_separam_cbs_receita_de_ibs_cgibs():
    from app.collectors import reforma as r
    html = ('<a href="/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/arrecadacao-federal/2026/analise-mensal-set-2026.pdf/view">x</a>'
            '<a href="https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/arrecadacao-federal/2026/analise-mensal-set-2026-anexo.xlsx/view">y</a>'
            '<a href="/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/arrecadacao-federal/2026/analise-mensal-set-2026.pdf/view">repetido</a>')
    p = r.publicacoes_receita(html, 2026)
    assert [(x["competencia"], x["formato"]) for x in p] == [("2026-09", "pdf"), ("2026-09", "xlsx")] and p[0]["url"].startswith("https://www.gov.br/receitafederal")
    c = r.publicacoes_cgibs('<a href="/upload/arquivos/202606/a.pdf"><span>Relatórios fiscais</span></a>')
    assert len(c) == 1 and {k: c[0][k] for k in ("url", "titulo", "formato", "publicado_em_mes")} == {"url": "https://cgibs.gov.br/upload/arquivos/202606/a.pdf", "titulo": "Relatórios fiscais", "formato": "pdf", "publicado_em_mes": "2026-06"}
    import io, openpyxl
    wb = openpyxl.Workbook(); wb.active.append(["Tributo", "COFINS"]); b = io.BytesIO(); wb.save(b)
    assert r.menciona_cbs_ibs(b.getvalue(), "xlsx") is False
    wb.active.append(["CBS", 1]); b = io.BytesIO(); wb.save(b)
    assert r.menciona_cbs_ibs(b.getvalue(), "xlsx") is True


def test_mapbiomas_resume_alertas_por_bioma_sem_misturar_com_prodes():
    from app.collectors import mapbiomas as m
    dados = {"alertStatusByBiomes": [{"biome": b, "total": 10, "totalProcessed": 9, "totalNotprocessed": 1, "yearMonth": ym} for b in sorted(m.BIOMAS) for ym in ("2025-12", "2026-01")]
             + [{"biome": "Oceano", "total": 1, "totalProcessed": 1, "totalNotprocessed": 0, "yearMonth": "2026-01"}],
             "lastAlertPublication": {"publishedAt": "2026-06-05", "total": 500, "publicationRange": "2026-05"}}
    d = m.resumir(dados)
    assert len(d["por_bioma_mes"]) == 6 and d["ultimo_mes"] == "2026-01" and d["por_bioma_ano"]["Cerrado"] == {"2025": 10, "2026": 10} and d["ultima_publicacao"]["alertas"] == 500


# ---------- CBS / IBS separados (31/10/2026) ----------
CGIBS_HTML = ('<div id="accordion-1" class="panel-group accordion"><div class="panel panel-default"><div class="panel-heading"><h4 class="panel-title">DECLARAÇÃO DE AUSÊNCIA<br> 1º QUADRIMESTRE DO EXERCÍCIO FINANCEIRO DE 2026</h4></div>'
              '<div class="panel-body"><p><a href="/upload/arquivos/202606/15-rel.pdf" download=""> Relatorios Fiscais <small>(.pdf 2,95 MBytes)</small> </a></p></div></div></div>'
              '<div class="panel panel-default"><div class="panel-heading"><h4 class="panel-title">Arrecadação do IBS em julho de 2026</h4></div><div class="panel-body"><a href="/upload/arquivos/202609/9-arr.xlsx">Planilha</a></div></div>')


def test_cgibs_le_painel_competencia_e_mes_de_publicacao():
    from app.collectors import reforma
    p = reforma.publicacoes_cgibs(CGIBS_HTML)
    assert [x["competencia"] for x in p] == ["2026-Q1", "2026-07"]
    assert [x["publicado_em_mes"] for x in p] == ["2026-06", "2026-09"]
    assert p[0]["arquivo"] == "Relatorios Fiscais" and p[0]["url"] == "https://cgibs.gov.br/upload/arquivos/202606/15-rel.pdf"
    assert reforma.competencia_cgibs("Sem data nenhuma", "https://x/y.pdf") == {"competencia": None, "periodo": None, "publicado_em_mes": None}


def test_situacoes_nunca_se_confundem():
    from app.collectors import reforma
    s = reforma.situacao_do_tributo
    assert s(False, [], False) == "indisponivel" and s(True, [], False) == "sem_publicacao"
    assert s(True, [{"a": 1}], False) == "publicacoes_sem_arrecadacao" and s(True, [{"a": 1}], True) == "arrecadacao_publicada"


def test_buscar_pagina_distingue_erro_de_conexao_e_http(monkeypatch):
    import httpx
    from app import http as h
    from app.collectors import reforma
    monkeypatch.setattr(reforma.time, "sleep", lambda s: None)

    class Cli:
        def __init__(self, f): self.f = f
        def get(self, url, **kw): return self.f(url)
    req = httpx.Request("GET", "https://x")
    def cai(url): raise httpx.ConnectTimeout("t", request=req)
    monkeypatch.setattr(h, "_cliente", Cli(cai))
    assert reforma.buscar_pagina(["https://a", "https://www.a"], tentativas=2)["estado"] == "erro_conexao"
    monkeypatch.setattr(h, "_cliente", Cli(lambda u: httpx.Response(404, request=req, text="nao")))
    assert reforma.buscar_pagina(["https://a"], tentativas=1)["estado"] == "erro_http"
    # primeiro endereço fora do ar, segundo responde: usa o segundo
    monkeypatch.setattr(h, "_cliente", Cli(lambda u: (_ for _ in ()).throw(httpx.ConnectTimeout("t", request=req)) if "www" not in u else httpx.Response(200, request=httpx.Request("GET", u), text="oi")))
    r = reforma.buscar_pagina(["https://a", "https://www.a"], tentativas=1)
    assert r["estado"] == "ok" and r["url"] == "https://www.a" and r["tentativas"][0]["resultado"] == "ConnectTimeout"


def test_ibs_detecta_publicacao_nova_mantem_dados_quando_portal_cai_e_nao_inventa_arrecadacao(monkeypatch):
    from app.collectors import reforma
    from app.db import SessionLocal, criar_tabelas
    from app.models import Registro
    criar_tabelas()
    alertas = []
    monkeypatch.setattr(reforma.alertas, "enviar", lambda m, *a, **k: alertas.append(m))
    monkeypatch.setattr(reforma.time, "sleep", lambda s: None)
    html = {"v": CGIBS_HTML.split('<div class="panel panel-default"><div class="panel-heading"><h4 class="panel-title">Arrecadação')[0]}   # só o 1º documento

    def pagina(urls, **kw):
        if "relatorios" in urls[0] and html["v"] is not None:
            return {"estado": "ok", "texto": html["v"], "url": urls[0], "tentativas": []}
        return {"estado": "erro_conexao", "texto": None, "url": None, "tentativas": [{"url": urls[0], "resultado": "ConnectTimeout"}]}
    monkeypatch.setattr(reforma, "buscar_pagina", pagina)
    db = SessionLocal()
    try:
        db.query(Registro).filter_by(fonte="cgibs", tipo="ibs_monitor").delete()
        db.commit()

        class N:
            avisos: list = []
        d1 = reforma._conferir_ibs(db, N())
        assert d1["situacao"] == "publicacoes_sem_arrecadacao" and len(d1["publicacoes"]) == 1 and d1["primeira_conferencia"] and not alertas
        html["v"] = CGIBS_HTML   # sai um documento novo, com "Arrecadação" no título
        d2 = reforma._conferir_ibs(db, N())
        assert d2["situacao"] == "arrecadacao_publicada" and [p["titulo"][:11] for p in d2["novas_nesta_conferencia"]] == ["Arrecadação"] and len(alertas) == 1
        assert {p["descoberto_em"] for p in d2["publicacoes"]} == {d1["publicacoes"][0]["descoberto_em"]}
        html["v"] = None   # portal fora do ar: não apaga nem vira "sem publicação"
        d3 = reforma._conferir_ibs(db, N())
        assert d3["situacao"] == "indisponivel" and len(d3["publicacoes"]) == 2 and d3["paginas"]["relatorios"]["estado"] == "erro_conexao"
        assert [h["situacao"] for h in d3["historico"]] == ["publicacoes_sem_arrecadacao", "arrecadacao_publicada", "indisponivel"]
        assert db.query(Registro).filter_by(fonte="cgibs", tipo="ibs_monitor").count() == 1
    finally:
        db.close()


# ---------- Overpass em partes, com retomada (31/10/2026) ----------
def _resp(js=None, status=200, texto=None):
    import httpx
    import json as _j
    return httpx.Response(status, request=httpx.Request("POST", "https://x"), text=texto if texto is not None else _j.dumps(js))


def _agora_iso(dias=0):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _via(i, lat=-10.0, tipo="primary", nome="Av. X"):
    return {"type": "way", "id": i, "tags": {"highway": tipo, "name": nome}, "geometry": [{"lat": lat, "lon": -48.0}, {"lat": lat + 0.01, "lon": -48.0}]}


def test_overpass_gira_espelhos_recusa_base_velha_e_resposta_cortada(monkeypatch):
    import httpx
    from app.collectors import osm_malha as om
    chamadas = []
    def post(url, **kw):
        chamadas.append(url.split("/")[2])
        if "overpass-api" in url:
            return _resp(status=504, texto="Gateway Time-out")
        if "private.coffee" in url:
            return _resp({"osm3s": {"timestamp_osm_base": _agora_iso(90)}, "elements": []})   # base de 3 meses atrás
        return _resp({"osm3s": {"timestamp_osm_base": _agora_iso()}, "elements": [_via(1)]})
    monkeypatch.setattr(om.httpx, "post", post)
    monkeypatch.setattr(om.httpx, "get", lambda *a, **k: _resp(texto="Rate limit: 0\n2 slots available now."))
    cli = om.Overpass(dormir=lambda s: None, intervalo=0)
    d, esp = cli.consultar("[out:json][timeout:60];out;")
    assert esp == "maps.mail.ru" and chamadas == ["overpass-api.de", "overpass.private.coffee", "maps.mail.ru"]
    assert len(cli.falhas) == 2 and "base OSM velha" in cli.falhas[1]
    # 200 com `remark` de erro (resultado cortado pelo servidor) é recusado em todos os espelhos
    monkeypatch.setattr(om.httpx, "post", lambda url, **kw: _resp({"osm3s": {"timestamp_osm_base": _agora_iso()}, "remark": "runtime error: Query timed out in \"query\"", "elements": [_via(2)]}))
    import pytest
    with pytest.raises(RuntimeError, match="Overpass indisponível"):
        om.Overpass(dormir=lambda s: None, intervalo=0).consultar("[out:json];out;")
    # JSON cortado no meio
    monkeypatch.setattr(om.httpx, "post", lambda url, **kw: _resp(texto='{"osm3s": {"timestamp'))
    with pytest.raises(RuntimeError, match="Overpass indisponível"):
        om.Overpass(dormir=lambda s: None, intervalo=0).consultar("[out:json];out;")


def test_overpass_espera_a_vaga_do_status(monkeypatch):
    from app.collectors import osm_malha as om
    esperas = []
    monkeypatch.setattr(om.httpx, "get", lambda *a, **k: _resp(texto="0 slots available now.\nSlot available after: 2026-10-31T12:00:00Z, in 17 seconds."))
    monkeypatch.setattr(om.httpx, "post", lambda url, **kw: _resp({"osm3s": {"timestamp_osm_base": _agora_iso()}, "elements": []}))
    om.Overpass(dormir=esperas.append, intervalo=0).consultar("[out:json];out;")
    assert 18 in esperas


def test_partes_sao_disjuntas_e_completas_e_dedupe_por_id():
    from app.collectors import osm_malha as om
    import re
    todos = ["motorway", "primary_link", "tertiary", "residential", "living_street", "unclassified", "service", "road", "busway", "footway", "track", "path", "steps"]
    def cai(grupo, tipo):
        filtro = om.GRUPOS[grupo]
        regs = re.findall(r'\["highway"(!?~|=)"([^"]+)"\]', filtro)
        ok = True
        for op, val in regs:
            casa = bool(re.fullmatch(val.strip("^$"), tipo)) if "~" in op else tipo == val
            ok = ok and (casa if "!" not in op else not casa)
        return ok
    for t in todos:
        n = sum(cai(g, t) for g in om.GRUPOS)
        assert n == (0 if t in om.EXCLUIDAS.split("|") else 1), (t, n)
    p = om.resumir_parte([_via(1), _via(1), _via(2, nome="Rua B"), {"type": "node", "id": 9}])
    assert p["vias"] == 2 and p["ids_duplicados"] == 1 and len(p["nomes_crc32"]) == 2
    j = om.juntar_partes({"a": p, "b": om.resumir_parte([_via(3, tipo="residential", nome="Av. X")])})
    assert j["vias_nomeadas"] == 2 and j["trechos"] == 3   # "Av. X" aparece nas duas partes e conta uma vez


def test_malha_salva_por_partes_e_retoma_depois_de_falha(monkeypatch):
    import pytest
    from app.collectors import osm_malha as om, transito
    from app.db import SessionLocal, criar_tabelas
    from app.models import Registro
    criar_tabelas()
    monkeypatch.setitem(transito.MINIMO_KM, "TO", 1)
    pedidos = []
    falhar = {"grupo": "servico"}
    def consultar(self, q, timeout_servidor=180):
        pedidos.append(q)
        if "out ids" in q:
            return {"osm3s": {"timestamp_osm_base": _agora_iso()}, "elements": [{"type": "relation", "id": 123}]}, "overpass-api.de"
        if falhar["grupo"] and 'highway"="service"' in q:
            raise RuntimeError("Overpass indisponível: teste")
        return {"osm3s": {"timestamp_osm_base": _agora_iso()}, "elements": [_via(len(pedidos), tipo="primary" if "motorway" in q else "residential")]}, "overpass-api.de"
    monkeypatch.setattr(om.Overpass, "consultar", consultar)
    db = SessionLocal()
    try:
        for t in ("malha_parte", "malha_capital", "relacao_municipio"):
            db.query(Registro).filter_by(fonte="osm", tipo=t).delete()
        db.commit()
        cli = om.Overpass(dormir=lambda s: None, intervalo=0)
        with pytest.raises(RuntimeError):
            om.coletar_capital(db, cli, "TO")
        assert db.query(Registro).filter_by(fonte="osm", tipo="malha_parte").count() == 2   # principais e locais ficaram salvas
        assert db.query(Registro).filter_by(fonte="osm", tipo="malha_capital").count() == 0   # capital incompleta: nada publicado
        antes = len(pedidos)
        falhar["grupo"] = None
        d = om.coletar_capital(db, cli, "TO")
        assert len(pedidos) - antes == 2 and d["partes_reaproveitadas"] == 2   # só pediu as duas que faltavam
        assert set(d["partes"]) == set(om.GRUPOS) and d["osm_base"] and d["relacao_osm"] == 123 and d["metodo"] == "overpass"
        assert "area(3600000123)" in pedidos[-1]
        om.coletar_capital(db, cli, "TO")   # nova rodada: tudo no cache, nenhuma consulta nova
        assert len(pedidos) - antes == 2
        assert db.query(Registro).filter_by(fonte="osm", tipo="malha_capital", chave="TO").count() == 1
        assert db.query(Registro).filter_by(fonte="osm", tipo="malha_parte").count() == 4
    finally:
        db.close()


def _pbf_de_teste(caminho):
    """PBF minúsculo: um quadrado de ~1,1 km de lado em Palmas com uma avenida dentro (≈1,1 km), uma rua local dentro, uma via FORA do limite, uma calçada (excluída) e uma área."""
    import osmium
    w = osmium.SimpleWriter(str(caminho))
    ns = {}
    for i, (lat, lon) in enumerate([(-10.20, -48.34), (-10.19, -48.34), (-10.19, -48.33), (-10.20, -48.33), (-10.195, -48.335), (-10.30, -48.30), (-10.31, -48.30)], start=1):
        w.add_node(osmium.osm.mutable.Node(id=i, location=(lon, lat)))
        ns[i] = i
    for wid, nos, tags in ((100, [1, 2], {"highway": "primary", "name": "Av. Teste"}), (101, [4, 5, 3], {"highway": "residential", "name": "Rua A"}), (102, [6, 7], {"highway": "primary", "name": "Fora"}),
                           (103, [1, 4], {"highway": "footway"}), (104, [1, 2], {"highway": "service", "area": "yes"}), (105, [1, 2], {"highway": "service"})):
        w.add_way(osmium.osm.mutable.Way(id=wid, nodes=nos, tags=tags))
    w.close()


def test_pbf_le_cabecalho_atribui_pelo_ponto_do_meio_e_exclui_o_que_nao_e_via(tmp_path):
    from shapely.geometry import box
    from shapely.prepared import prep
    from app.collectors import osm_pbf
    arq = tmp_path / "t.osm.pbf"
    _pbf_de_teste(arq)
    g = box(-48.345, -10.205, -48.325, -10.185)
    res = osm_pbf.processar_pbf(arq, {"TO": (g, prep(g))})
    ids = sorted(e["id"] for e in res["vias"]["TO"])
    assert ids == [100, 101, 105]   # a via de fora, a calçada e a área não entram
    assert res["estatisticas"]["vias_highway_lidas"] == 6
    p = osm_pbf.resumir_parte(res["vias"]["TO"])
    assert p["vias"] == 3 and p["ids_duplicados"] == 0
    km = sum(c["km"] for c in p["por_categoria"].values())
    assert abs(km - 3.784) < 0.01   # avenida 1,112 km + rua em zigue-zague 2 × 0,78 km + serviço 1,112 km (haversine, conferido à mão)
    assert "osm_base" in osm_pbf.cabecalho_pbf(arq)
    # fora do ar sem erro de MD5: o MD5 do arquivo bate com o calculado
    from app.downloads import md5
    assert len(md5(arq)) == 32


def _zip_prodes(caminho, truncar_shx=False, sem_prj=False):
    import io
    import zipfile
    import shapefile
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POINT)
    for nome, tipo, tam, dec in (("state", "C", 2, 0), ("year", "N", 9, 0), ("area_km", "N", 24, 15), ("main_class", "C", 32, 0), ("uuid", "C", 80, 0)):
        w.field(nome, tipo, tam, dec)
    for i, (uf, ano, km, cls, uid) in enumerate([("MG", 2020, 1.5, "DESMATAMENTO", "a"), ("MG", 2020, 0.5, "DESMATAMENTO", "b"), ("MG", 2020, 0.5, "DESMATAMENTO", "b"),   # "b" repetido
                                                  ("SP", 2024, 2.0, "DESMATAMENTO", "c"), ("SP", 2024, 9.0, "RESERVATORIO", "d"), ("SP", 2002, 7.0, "DESMATAMENTO", "e")]):   # classe de fora e ano < 2004
        w.point(i, i)
        w.record(uf, ano, km, cls, uid)
    w.close()
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("prodes_x.shp", shp.getvalue())
        z.writestr("prodes_x.shx", shx.getvalue()[:-8] if truncar_shx else shx.getvalue())
        z.writestr("prodes_x.dbf", dbf.getvalue())
        if not sem_prj:
            z.writestr("prodes_x.prj", "GEOGCS[]")


def test_prodes_mata_valida_zip_somas_por_uf_ano_sem_duplicidade_e_importa_idempotente(tmp_path):
    import pytest
    from app.collectors import prodes_mata as pm
    from app.db import SessionLocal, criar_tabelas
    from app.models import Registro
    z = tmp_path / "ok.zip"
    _zip_prodes(z)
    v = pm.validar_zip(z)
    assert v["feicoes"] == 6 and set(v["componentes"]) == {".shp", ".shx", ".dbf", ".prj"}
    por_uf, est = pm.ler_incrementos(z)
    assert por_uf == {"MG": {"2020": 2.0}, "SP": {"2024": 2.0}}   # b só uma vez; reservatório e 2002 fora
    assert est["duplicados"] == 1 and est["outras_classes"] == 1 and est["desmatamento"] == 3 and est["ano_min"] == 2020
    for kw, msg in (({"sem_prj": True}, "faltam componentes"), ({"truncar_shx": True}, "inconsistente")):
        ruim = tmp_path / f"{msg[:4]}.zip"
        _zip_prodes(ruim, **kw)
        with pytest.raises(RuntimeError, match=msg):
            pm.validar_zip(ruim)
    lixo = tmp_path / "lixo.zip"
    lixo.write_bytes(b"isso nao e um zip")
    with pytest.raises(RuntimeError, match="ZIP inválido"):
        pm.validar_zip(lixo)
    criar_tabelas()
    db = SessionLocal()
    try:
        db.query(Registro).filter(Registro.fonte == "inpe", Registro.tipo.in_(["prodes_bioma", "prodes_download"]), Registro.chave.like("mata_atlantica%")).delete(synchronize_session=False)
        db.commit()
        # ano antigo já existente e que o arquivo não traz: é preservado; ano que o arquivo traz: é substituído
        from app.utils import upsert
        upsert(db, Registro, {"fonte": "inpe", "tipo": "prodes_bioma", "chave": "mata_atlantica"}, {"titulo": "x", "dados": {"por_uf": {"MG": {"2019": 7.0, "2020": 99.0}}}})
        db.commit()
    finally:
        db.close()
    assert pm.coletar_prodes_mata_atlantica(arquivo=str(z)) == 1
    assert pm.coletar_prodes_mata_atlantica(arquivo=str(z)) == 0   # mesma versão e mesmo SHA-256: não repete
    db = SessionLocal()
    try:
        r = db.query(Registro).filter_by(fonte="inpe", tipo="prodes_bioma", chave="mata_atlantica").one().dados
        assert r["por_uf"]["MG"] == {"2019": 7.0, "2020": 2.0} and r["por_uf"]["SP"] == {"2024": 2.0} and r["total"]["2020"] == 2.0
        assert r["feicoes"] == 3 and r["origem"] == "arquivo" and len(r["sha256"]) == 64 and r["ultimo_ano"] == "2024"
        assert db.query(Registro).filter(Registro.fonte == "inpe", Registro.tipo == "prodes_download", Registro.chave.like("mata_atlantica%")).count() == 1
    finally:
        db.close()


def test_prodes_escolhe_o_shapefile_certo_no_catalogo():
    import pytest
    from app.collectors import prodes_mata as pm
    cat = [{"enabled": True, "lang": "pt-br", "link": "/download/dataset/mata-atlantica-prodes/vector/prodes_biome_mata_atlantica_v1.gpkg.zip", "created": "2026-08-07"},
           {"enabled": True, "lang": "en", "link": "/download/dataset/mata-atlantica-prodes/vector/yearly_deforestation_biome_mata_atlantica_v2.zip", "created": "2026-08-07"},
           {"enabled": True, "lang": "pt-br", "link": "/download/dataset/mata-atlantica-prodes/vector/yearly_deforestation_biome_mata_atlantica_v20260806.zip", "created": "2026-08-07 10:16:17", "description": "d", "metadata": "/geonetwork/x"},
           {"enabled": False, "lang": "pt-br", "link": "/download/dataset/mata-atlantica-prodes/vector/yearly_deforestation_biome_mata_atlantica_v20270101.zip", "created": "2027-01-01"}]
    e = pm.escolher(cat)
    assert e["versao"] == "20260806" and e["url"].startswith("https://terrabrasilis.dpi.inpe.br/download/dataset/") and e["metadados"].endswith("/geonetwork/x")
    with pytest.raises(RuntimeError, match="não traz"):
        pm.escolher([cat[0]])


def _membro(papel, pts):
    return {"type": "way", "role": papel, "geometry": [{"lon": x, "lat": y} for x, y in pts]}


def test_limite_do_osm_junta_caminhos_e_tira_buracos_e_cai_para_o_osm_quando_o_ibge_nao_responde(monkeypatch):
    import pytest
    from shapely.geometry import box
    from app.collectors import osm_pbf
    from app.db import SessionLocal, criar_tabelas
    from app.models import Registro
    rel = {"members": [_membro("outer", [(0, 0), (2, 0), (2, 2)]), _membro("outer", [(2, 2), (0, 2), (0, 0)]), _membro("inner", [(0.5, 0.5), (1, 0.5), (1, 1), (0.5, 1), (0.5, 0.5)])]}
    g = osm_pbf.poligono_da_relacao(rel)
    assert abs(g.area - (4 - 0.25)) < 1e-9   # quadrado 2×2 montado de dois caminhos, menos o buraco de 0,5×0,5
    with pytest.raises(RuntimeError, match="não fecha"):
        osm_pbf.poligono_da_relacao({"members": [_membro("outer", [(0, 0), (1, 0)])]})
    criar_tabelas()
    db = SessionLocal()
    try:
        db.query(Registro).filter_by(fonte="osm", tipo="limite_municipio", chave="TO").delete()
        db.commit()
        chamadas = []
        def ibge_fora(ibge): chamadas.append("ibge"); raise RuntimeError("IBGE não respondeu")
        def osm_ok(db_, uf, ibge): chamadas.append("osm"); return box(0, 0, 1, 1)
        monkeypatch.setattr(osm_pbf, "limite_ibge", ibge_fora)
        monkeypatch.setattr(osm_pbf, "limite_osm", osm_ok)
        _g, _p, fonte = osm_pbf.limite_municipio(db, "TO", "1721000")
        assert chamadas == ["ibge", "osm"] and fonte.startswith("OpenStreetMap")
        _g, pr, fonte = osm_pbf.limite_municipio(db, "TO", "1721000")   # segunda vez: vem do banco, sem rede
        assert chamadas == ["ibge", "osm"] and fonte.endswith("(guardado)") and pr.contains(osm_pbf.__dict__["__builtins__"]["__import__"]("shapely.geometry", fromlist=["Point"]).Point(0.5, 0.5))
        db.query(Registro).filter_by(fonte="osm", tipo="limite_municipio", chave="TO").delete()
        db.commit()
        monkeypatch.setattr(osm_pbf, "limite_osm", lambda *a: (_ for _ in ()).throw(RuntimeError("Overpass indisponível")))
        with pytest.raises(RuntimeError, match="sem limite do município.*IBGE.*OpenStreetMap"):
            osm_pbf.limite_municipio(db, "TO", "1721000")
    finally:
        db.close()
