"""Testes com o formato REAL das respostas (copiado das APIs em 07/10/2026)."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import obrasgov, pncp, senado  # noqa: E402
from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Parlamentar, Registro  # noqa: E402

criar_tabelas()
cliente = TestClient(app)

SENADORES = {"ListaParlamentarEmExercicio": {"Metadados": {"Versao": "07/10/2026"}, "Parlamentares": {"Parlamentar": [
    {"IdentificacaoParlamentar": {"CodigoParlamentar": "5672", "NomeParlamentar": "Alan Rick",
                                  "SiglaPartidoParlamentar": "REPUBLICANOS", "UfParlamentar": "AC",
                                  "UrlFotoParlamentar": "http://www.senado.leg.br/senadores/img/fotos-oficiais/senador5672.jpg",
                                  "EmailParlamentar": "sen.alanrick@senado.leg.br"},
     "Mandato": {"CodigoMandato": "596"}}]}}}

VOTACOES = {"ListaVotacoes": {"Metadados": {"Descontinuacao": {"UrlServicoSubstituto": "https://legis.senado.leg.br/dadosabertos/votacao"}},
                              "Votacoes": {"Votacao": [{
    "CodigoSessao": "586477", "DataSessao": "2026-09-01", "CodigoSessaoVotacao": "7104", "Secreta": "S",
    "DescricaoVotacao": "Votação nominal do Projeto de Decreto Legislativo nº 995, de 2026.", "Resultado": "A",
    "TotalVotosSim": "63", "TotalVotosNao": "4", "TotalVotosAbstencao": "0",
    "SiglaMateria": "PDL", "NumeroMateria": "995", "AnoMateria": "2026", "DescricaoIdentificacaoMateria": "PDL 995/2026",
    "Votos": {"VotoParlamentar": [
        {"CodigoParlamentar": "22", "NomeParlamentar": "Esperidião Amin", "SiglaPartido": "PP", "SiglaUF": "SC", "Voto": "Votou"},
        {"CodigoParlamentar": "285", "NomeParlamentar": "Marcio Bittar", "SiglaPartido": "PL", "SiglaUF": "AC",
         "Voto": "AP", "DescricaoVoto": "Atividade parlamentar"}]}}]}}}

OBRAS = {"content": [{"idUnico": "53408.35-50", "nome": "Fase 09 Lote 120", "situacao": "Cadastrada", "uf": "SP",
                      "fontesDeRecurso": [{"origem": "Estadual", "valorInvestimentoPrevisto": 11126062.60}]},
                     {"idUnico": "46849.35-06", "nome": "Construção de 30 Unidades Habitacionais", "uf": "SP",
                      "fontesDeRecurso": [{"origem": "Federal", "valorInvestimentoPrevisto": 3997500.00}]}],
         "totalPages": 1, "last": True, "size": 2}

PNCP = {"data": [{"numeroControlePNCP": "13880257000127-2-000239/2026", "anoContrato": 2026,
                  "objetoContrato": "Transporte escolar", "valorGlobal": 28608.0, "dataAssinatura": "2026-02-09",
                  "orgaoEntidade": {"cnpj": "13880257000127", "razaoSocial": "MUNICIPIO DE XIQUE-XIQUE"},
                  "unidadeOrgao": {"ufSigla": "BA", "municipioNome": "Xique-Xique"},
                  "niFornecedor": "44281151000130", "nomeRazaoSocialFornecedor": "MARIA FEITOZA DOS SANTOS"}],
        "totalPaginas": 1}


def falso(url, params=None, headers=None):
    if "senador/lista/atual" in url:
        return SENADORES
    if "plenario/lista/votacao" in url:
        return VOTACOES if "20260901" in url else {"ListaVotacoes": {"Votacoes": None}}
    if "projeto-investimento" in url:
        return OBRAS
    if "pncp" in url:
        return PNCP
    raise AssertionError(url)

# Arquivo anual da cota (https://www.camara.leg.br/cotas/Ano-2026.csv.zip, conferido em 09/10/2026).
# A 1ª linha é real (liderança, sem deputado); as outras seguem o mesmo formato com deputados de teste.
COTAS_CABECALHO = ('"txNomeParlamentar";"cpf";"ideCadastro";"nuCarteiraParlamentar";"nuLegislatura";"sgUF";"sgPartido";'
                   '"codLegislatura";"numSubCota";"txtDescricao";"numEspecificacaoSubCota";"txtDescricaoEspecificacao";'
                   '"txtFornecedor";"txtCNPJCPF";"txtNumero";"indTipoDocumento";"datEmissao";"vlrDocumento";"vlrGlosa";'
                   '"vlrLiquido";"numMes";"numAno";"numParcela";"txtPassageiro";"txtTrecho";"numLote";"numRessarcimento";'
                   '"datPagamentoRestituicao";"vlrRestituicao";"nuDeputadoId";"ideDocumento";"urlDocumento"')
COTAS_LINHAS = [
    '"LID.GOV-CD";"";"";"";"2023";"NA";"";"57";"1";"MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR";"0";"";'
    '"AMORETTO CAFES EXPRESSO LTDA";"085.324.290/0013-1";"2849";"0";"2026-01-08T00:00:00";"1467";"0";"1467";"1";"2026";'
    '"0";"";"";"2205670";"";"";"";"2812";"8044688";"https://www.camara.leg.br/cota-parlamentar/documentos/publ/2812/2026/8044688.pdf"',
]


def cotas_zip(caminho, linhas):
    import zipfile
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("Ano-2026.csv", ("\ufeff" + COTAS_CABECALHO + "\n" + "\n".join(linhas) + "\n").encode("utf-8"))
    return str(caminho)


def linha_cota(nome, dep_id, doc, valor, mes="3", tipo="COMBUSTÍVEIS E LUBRIFICANTES.", fornecedor="POSTO X", cnpj="98.765.432/0001-10"):
    # ideCadastro (3ª coluna) = id do deputado na API; nuDeputadoId (antepenúltima) é outro número interno
    return (f'"{nome}";"";"{dep_id}";"";"2023";"SP";"ABC";"57";"3";"{tipo}";"1";"";"{fornecedor}";"{cnpj}";"1";"0";'
            f'"2026-0{mes}-10T00:00:00";"{valor}";"0";"{valor}";"{mes}";"2026";"0";"";"";"1";"";"";"";"3{dep_id}";"{doc}";'
            f'"https://www.camara.leg.br/cota-parlamentar/documentos/publ/3{dep_id}/2026/{doc}.pdf"')


def test_formatos_reais(monkeypatch):
    monkeypatch.setattr(http, "get_json", falso)
    assert senado.coletar_senadores() == 1
    assert senado.coletar_votacoes(date(2026, 9, 1), date(2026, 9, 30)) == 1
    assert obrasgov.coletar_obras(ufs=["SP"]) == 2
    assert pncp.coletar_contratos(date(2026, 9, 1), date(2026, 9, 2)) == 1

    db = SessionLocal()
    assert db.query(Parlamentar).filter_by(casa="senado", id_externo="5672").one().partido == "REPUBLICANOS"
    obra = db.query(Registro).filter_by(fonte="obrasgov", chave="53408.35-50").one()
    assert obra.valor == 11126062.60
    contrato = db.query(Registro).filter_by(fonte="pncp").one()
    assert contrato.uf == "BA" and contrato.ano == 2026 and contrato.valor == 28608.0
    db.close()

    v = cliente.get("/votacoes", params={"casa": "senado", "q": "PDL 995"}).json()["itens"][0]
    assert v["resultado"] == "Aprovada" and v["secreta"] is True and v["materia"] == "PDL 995/2026"
    det = cliente.get(f"/votacoes/{v['id']}").json()
    assert det["placar"] == {"sim": 63, "nao": 4, "abstencao": 0}
    assert det["aviso"]
    votos = {x["parlamentar"]["nome"]: x["voto"] for x in det["votos"]}
    assert votos == {"Esperidião Amin": "Votou", "Marcio Bittar": "Atividade parlamentar"}


# ---------- segunda rodada de prints (07/10/2026) ----------
from app.collectors import camara, legislacao, siconfi, tesouro  # noqa: E402
from app.utils import extrair_materia, extrair_placar  # noqa: E402

CAMARA_VOT = {"dados": [{"id": "2611313-31", "data": "2026-09-03", "dataHoraRegistro": "2026-09-03T17:28:34",
                         "siglaOrgao": "PLEN", "proposicaoObjeto": None,
                         "descricao": "Aprovada a Subemenda Substitutiva ao Projeto de Lei Complementar nº 74, de 2026, "
                                      "adotada pelo relator da Comissão de Finanças e Tributação. Sim: 346; Não: 46; "
                                      "Abstenção: 3; Total: 395.", "aprovacao": 1}], "links": []}

LEGIS = {"ListaDocumento": {"Metadados": {"Versao": "07/10/2026"}, "documentos": {"documento": [
    {"id": "44095919", "tipo": "LEI-n", "descricao": "Lei Numerada", "numero": "15526", "norma": "LEI-15526-2026-09-29",
     "normaNome": "Lei nº 15.526 de 29/09/2026", "ementa": "Altera a Lei nº 8.171, de 17 de janeiro de 1991...",
     "dataassinatura": "29/09/2026", "anoassinatura": "2026", "apelido": "LEI-15526-2026-09-29"}]}}}

TESOURO_ESTADOS = {"registros": [{"codigo": 1, "nome": "Acre"}, {"codigo": 26, "nome": "São Paulo"},
                                 {"codigo": 25, "nome": "Sergipe"}], "status": "ok"}

RGF = {"items": [
    {"exercicio": 2025, "periodo": 3, "uf": "SP", "cod_conta": "DividaConsolidada", "conta": "DÍVIDA CONSOLIDADA - DC (I)",
     "coluna": "SALDO DO EXERCÍCIO ANTERIOR", "valor": 372192972626.3},
    {"exercicio": 2025, "periodo": 3, "uf": "SP", "cod_conta": "DividaConsolidada", "conta": "DÍVIDA CONSOLIDADA - DC (I)",
     "coluna": "Até o 3º Quadrimestre", "valor": 382603718968.85},
    {"exercicio": 2025, "periodo": 3, "uf": "SP", "cod_conta": "DividaConsolidada", "conta": "DÍVIDA CONSOLIDADA - DC (I)",
     "coluna": "Até o 1º Quadrimestre", "valor": 380851632137.25}], "hasMore": False}

SENADO_NOVO = [{"ano": 2026, "codigoSessaoVotacao": 7104, "dataSessao": "2026-09-01", "identificacao": "PDL 995/2026",
                "descricaoVotacao": "Votação nominal do Projeto de Decreto Legislativo nº 995, de 2026.",
                "ementa": "Escolhe o Senhor Rodrigo Otavio Soares Pacheco para o cargo de Ministro do TCU",
                "resultadoVotacao": "A", "totalVotosSim": 63, "totalVotosNao": 4, "totalVotosAbstencao": 0,
                "votacaoSecreta": "S", "votos": [
                    {"codigoParlamentar": 5672, "nomeParlamentar": "Alan Rick", "siglaPartidoParlamentar": "REPUBLICANOS",
                     "siglaUFParlamentar": "AC", "siglaVotoParlamentar": "Votou", "descricaoVotoParlamentar": None},
                    {"codigoParlamentar": 5967, "nomeParlamentar": "Angelo Coronel", "siglaPartidoParlamentar": "REPUBLICANOS",
                     "siglaUFParlamentar": "BA", "siglaVotoParlamentar": "AP",
                     "descricaoVotoParlamentar": "Atividade parlamentar"}]}]


def falso2(url, params=None, headers=None):
    if url.endswith("/votacoes"):
        return CAMARA_VOT
    if url.endswith("/votos"):
        return {"dados": []}  # votação simbólica: sem votos nominais
    if "legislacao/lista" in url:
        return LEGIS if params["tipo"] == "LEI" else {"ListaDocumento": {"documentos": None}}
    if url.endswith("/custom/estados"):
        return TESOURO_ESTADOS
    if url.endswith("/rgf"):
        return RGF if params["id_ente"] == 35 else {"items": [], "hasMore": False}
    if url.endswith("/votacao.json"):
        return SENADO_NOVO
    raise AssertionError(url)


def test_extratores():
    assert extrair_materia(CAMARA_VOT["dados"][0]["descricao"]) == "PLP 74/2026"
    assert extrair_materia("Aprovada a PEC... Proposta de Emenda à Constituição nº 45, de 2019") == "PEC 45/2019"
    assert extrair_materia("Projeto de Lei nº 2.338, de 2023") == "PL 2338/2023"
    assert extrair_placar(CAMARA_VOT["dados"][0]["descricao"]) == {"sim": 346, "nao": 46, "abstencao": 3}


def test_segunda_rodada(monkeypatch):
    monkeypatch.setattr(http, "get_json", falso2)
    assert camara.coletar_votacoes(date(2026, 9, 1), date(2026, 9, 5)) == 1
    v = cliente.get("/votacoes", params={"casa": "camara", "q": "PLP 74/2026"}).json()["itens"][0]
    assert v["materia"] == "PLP 74/2026" and v["placar_oficial"]["sim"] == 346 and v["resultado"] == "Aprovada"

    assert legislacao.coletar_normas(2026) == 1
    n = cliente.get("/legislacao", params={"q": "8.171"}).json()["itens"][0]
    assert n["tipo"] == "LEI" and n["numero"] == "15526" and str(n["data"]) == "2026-09-29"
    assert n["urn"] == "urn:lex:br:federal:lei:2026-09-29;15526"
    assert n["url_texto"].startswith("https://www.lexml.gov.br/urn/")

    assert tesouro.codigos_estados() == {"AC": "1", "SP": "26", "SE": "25"}

    assert siconfi.coletar_divida_estados(2025, ufs=["SP"]) == 3
    div = cliente.get("/estados/SP/resumo").json()["divida"]
    assert div["consolidada"]["valor"] == 382603718968.85 and "3º" in div["consolidada"]["referencia"]

    assert senado.coletar_votacoes(date(2026, 9, 1), date(2026, 9, 30)) == 1
    sv = cliente.get("/votacoes", params={"casa": "senado", "q": "PDL 995"}).json()["itens"][0]
    assert sv["secreta"] and sv["ementa"].startswith("Escolhe") and sv["placar_oficial"]["sim"] == 63
    det = cliente.get(f"/votacoes/{sv['id']}").json()
    votos = {x["parlamentar"]["nome"]: (x["voto"], x["partido_na_data"]) for x in det["votos"]}
    assert votos["Angelo Coronel"] == ("Atividade parlamentar", "REPUBLICANOS")


# ---------- terceira rodada: IBGE e Tesouro (07/10/2026) ----------
from app.collectors import ibge  # noqa: E402
from app.models import Registro as Reg  # noqa: E402

IBGE_POP = [{"id": "9324", "variavel": "População residente estimada", "unidade": "Pessoas", "resultados": [
    {"classificacoes": [], "series": [{"localidade": {"id": "35", "nivel": {"id": "N3", "nome": "Unidade da Federação"},
                                                      "nome": "São Paulo"}, "serie": {"2026": "46179008"}}]}]}]

TRANSF = {"registros": [{"transferencia": "CIDE-Combustíveis", "codigo": 1}, {"transferencia": "FPE", "codigo": 7},
                        {"transferencia": "LC 201/2023 \u2013 COMPENSAÇÃO ICMS", "codigo": 17}], "status": "ok"}

POR_ESTADOS = {"registros": [
    {"transferencia": "CIDE-Combustíveis", "uf": "SP", "ano": "2025", "valor": 28946776.81, "mes": "01", "regiao": "Sudeste"},
    {"transferencia": "CIDE-Combustíveis", "uf": "SP", "ano": "2025", "valor": 26743556.07, "mes": "04", "regiao": "Sudeste"}],
    "status": "ok"}

# formato provável (uma linha por município); garante que municípios não se sobrescrevem
POR_MUNIC = {"registros": [
    {"uf": "SP", "ano": "2025", "mes": "01", "municipio": "Jales", "co_ibge": 3524808, "valor": 100.0},
    {"uf": "SP", "ano": "2025", "mes": "01", "municipio": "Franca", "co_ibge": 3516200, "valor": 200.0}], "status": "ok"}


def falso3(url, params=None, headers=None):
    if "agregados" in url:
        return IBGE_POP if "/9324" in url else []
    if url.endswith("/custom/estados"):
        return TESOURO_ESTADOS
    if url.endswith("/custom/transferencias"):
        return TRANSF
    if url.endswith("/custom/por_estados"):
        assert params["p_estado"] == "1:26:25" and params["p_transferencia"] == "1:7:17"
        return POR_ESTADOS
    if url.endswith("/custom/por_estado_municipio"):
        return POR_MUNIC
    raise AssertionError(url)


def test_terceira_rodada(monkeypatch):
    monkeypatch.setattr(http, "get_json", falso3)
    assert ibge.coletar_indicadores() == 1
    assert tesouro.coletar_transferencias(2025) == 4
    db = SessionLocal()
    pop = db.query(Reg).filter_by(tipo="indicador:populacao", chave="SP-2026").one()
    assert pop.valor == 46179008 and pop.ano == 2026
    est = db.query(Reg).filter_by(fonte="tesouro", tipo="transf_estado", uf="SP", titulo="CIDE-Combustíveis").all()
    assert round(sum(r.valor for r in est), 2) == 55690332.88 and {r.dados["mes"] for r in est} == {1, 4}
    mun = db.query(Reg).filter(Reg.fonte == "tesouro", Reg.tipo == "transf_municipios",
                               Reg.titulo.in_(["Jales", "Franca"])).all()
    assert sorted(r.valor for r in mun) == [100.0, 200.0]
    db.close()


def test_cota_camara_arquivo_anual(tmp_path):
    """A cota vem do arquivo anual: liga pelo ideCadastro, ignora lideranças e soma parcelas do mesmo documento."""
    from app.collectors import camara
    from app.models import Despesa
    with SessionLocal() as db:
        for ide, nome in (("990001", "Deputada Cota"), ("990002", "Deputado Cota")):
            if not db.query(Parlamentar).filter_by(casa="camara", id_externo=ide).first():
                db.add(Parlamentar(casa="camara", id_externo=ide, nome=nome, uf="SP"))
        db.commit()
    arq = cotas_zip(tmp_path / "cotas.zip", COTAS_LINHAS + [
        linha_cota("Deputada Cota", "990001", "77001", "250.5"),
        linha_cota("Deputado Cota", "990002", "77002", "100", tipo="PASSAGEM AÉREA - SIGEPA"),
        linha_cota("Deputado Cota", "990002", "77002", "-20", tipo="PASSAGEM AÉREA - SIGEPA"),
    ])
    assert camara.coletar_despesas(2026, apenas_ids=["990001", "990002"], arquivo_local=arq) == 2
    assert camara.coletar_despesas(2026, apenas_ids=["990001", "990002"], arquivo_local=arq) == 2  # recarga sem duplicar
    with SessionLocal() as db:
        notas = {d.id_externo: d for d in db.query(Despesa).filter(Despesa.id_externo.in_(["77001", "77002"]))}
    assert notas["77001"].valor == 250.5 and notas["77001"].cnpj_cpf == "98765432000110" and notas["77001"].mes == 3
    assert notas["77002"].valor == 80.0


def test_capag_planilha_com_linhas_de_resumo(tmp_path):
    """Planilha real da CAPAG (posição set/2026): 2 linhas de resumo antes do cabeçalho."""
    import openpyxl

    from app.collectors import capag
    from app.models import Municipio
    wb = openpyxl.Workbook()
    ws = wb.active
    for linha in [(None, None, "CAPAG Ano Base 2025", 70, 6, 7, 35, 37, 64, 67, None, None, "DCA Obrigatória", None),
                  (None, None, "CAPAG Ano Base 2024", 95, 10, 11, 49, 50, 88, 89, None, None, True, None),
                  ("Código Município Completo", "Nome_Município", "UF", "CAPAG", "Indicador 1", "Nota 1", "Indicador 2",
                   "Nota 2", "Indicador 3", "Nota 3", "ICF", "Observação", "Origem da Nota Final", "Possui DCA 2025?"),
                  (1100015, "Alta Floresta D'Oeste", "RO", "C", 0.0443, "A", 0.9716, "C", 0, "C", "Cicf", None,
                   "CAPAG Ano Base 2025", "Sim"),
                  (1100023, "Ariquemes", "RO", "B+", 0.1085, "A", 0.8822, "B", 0.0191, "B", "Aicf", None,
                   "CAPAG Ano Base 2025", "Sim")]:
        ws.append(linha)
    arq = tmp_path / "capag.xlsx"
    wb.save(arq)
    with SessionLocal() as db:
        for cod, nome in (("1100015", "Alta Floresta D'Oeste"), ("1100023", "Ariquemes")):
            if not db.query(Municipio).filter_by(codigo_ibge=cod).first():
                db.add(Municipio(codigo_ibge=cod, nome=nome, uf="RO"))
        db.commit()
    assert capag.coletar_capag(arquivo_local=str(arq), ano=2025) == 2
    with SessionLocal() as db:
        m = db.query(Municipio).filter_by(codigo_ibge="1100023").one()
    assert m.capag == "B+" and m.capag_ano == 2025 and m.capag_detalhe.get("Nota 1") == "A"
    with SessionLocal() as db:  # o banco de teste é compartilhado: não deixa estes municípios para os outros testes
        db.query(Municipio).filter(Municipio.codigo_ibge.in_(["1100015", "1100023"])).delete()
        db.commit()


# Base aberta do CNPJ (Receita, pasta AAAA-MM do compartilhamento do SERPRO): CSV sem cabeçalho, tudo entre aspas.
# Campos do estabelecimento: básico;ordem;dv;matriz(1)/filial(2);fantasia;situação;data;motivo;cidade exterior;país;
# início;cnae;cnaes secundárias;tipo logr.;logradouro;número;complemento;bairro;cep;uf;município;ddd1;tel1;ddd2;tel2;
# ddd fax;fax;e-mail;situação especial;data da situação especial
ESTAB_CNPJ = [
    '"11222333";"0001";"81";"1";"LOJAS EXEMPLO";"02";"20050103";"00";"";"";"19990101";"4711302";"";"RUA";"DAS FLORES";'
    '"10";"";"CENTRO";"01001000";"SP";"7107";"11";"12345678";"";"";"";"";"";"RECUPERACAO JUDICIAL";"20230119"',
    '"11222333";"0002";"62";"2";"LOJAS EXEMPLO FILIAL";"02";"20050103";"00";"";"";"20010101";"4711302";"";"RUA";"B";'
    '"1";"";"CENTRO";"20000000";"RJ";"6001";"21";"1";"";"";"";"";"";"RECUPERACAO JUDICIAL";"20230119"',
    '"44555666";"0001";"00";"1";"";"08";"20200101";"01";"";"";"20100101";"4120400";"";"AV";"C";"2";"";"X";"30000000";'
    '"MG";"4123";"31";"2";"";"";"";"";"";"FALIDO";"20190510"',
    '"77888999";"0001";"10";"1";"PADARIA";"02";"20050103";"00";"";"";"20050103";"1091102";"";"RUA";"D";"3";"";"Y";'
    '"40000000";"BA";"3849";"71";"3";"";"";"";"";"";"";""',
]
EMPRESAS_CNPJ = ['"11222333";"LOJAS EXEMPLO S.A.";"2046";"10";"1500000000,00";"05";""',
                 '"44555666";"CONSTRUTORA EXEMPLO LTDA";"2062";"49";"100000,00";"03";""',
                 '"77888999";"PADARIA DA ESQUINA LTDA";"2062";"49";"5000,00";"01";""']


def test_cnpj_base_recuperacao_judicial(tmp_path):
    import zipfile as zf

    from app.collectors import cnpj_base

    def zipar(nome, linhas, metodo=zf.ZIP_DEFLATED):  # a Receita usa deflate; o "stored" testa o outro caminho
        with zf.ZipFile(tmp_path / nome, "w", compression=metodo) as z:
            z.writestr(nome.replace(".zip", ".CSV"), ("\n".join(linhas) + "\n").encode("latin-1"))
    zipar("Estabelecimentos0.zip", ESTAB_CNPJ)
    zipar("Empresas0.zip", EMPRESAS_CNPJ)
    zipar("Municipios.zip", ['"7107";"SAO PAULO"', '"4123";"BELO HORIZONTE"'], zf.ZIP_STORED)
    zipar("Cnaes.zip", ['"4711302";"Comércio varejista de mercadorias em geral"'])
    assert cnpj_base.coletar_recuperacao_judicial(pasta_local=str(tmp_path)) == 2
    assert cnpj_base.coletar_recuperacao_judicial(pasta_local=str(tmp_path)) == 2  # idempotente

    r = cliente.get("/recuperacao-judicial").json()
    assert r["total"] == 1 and "irregularidade" in r["aviso"]
    e = r["itens"][0]
    assert e["cnpj"] == "11222333000181" and e["matriz"] is True and e["nome"] == "LOJAS EXEMPLO S.A."
    assert e["municipio"] == "SAO PAULO" and e["porte"] == "Demais" and e["capital_social"] == 1500000000.0
    assert e["data_situacao_especial"] == "2023-01-19" and e["situacao_cadastral"] == "Ativa"
    linhas = list(cnpj_base.linhas_do_zip(cnpj_base.blocos_arquivo(tmp_path / "Estabelecimentos0.zip", 7)))
    assert len(linhas) == 4 and linhas[3].endswith(b'"";""')  # lido em pedaços pequenos, como chega da rede
    assert e["cnae_descricao"].startswith("Comércio varejista")
    fal = cliente.get("/recuperacao-judicial", params={"tipo": "falencia"}).json()
    assert fal["itens"][0]["nome"] == "CONSTRUTORA EXEMPLO LTDA" and fal["itens"][0]["situacao_cadastral"] == "Baixada"
    res = cliente.get("/recuperacao-judicial/resumo").json()
    assert res["por_uf"] == {"SP": 1} and res["ativas"] == 1 and res["por_ano"] == {"2023": 1}
