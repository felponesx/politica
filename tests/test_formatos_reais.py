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


# Sisdepen (Senappen), base semestral por estabelecimento: CSV UTF-8, ';', ~1.700 colunas; trecho com as que usamos
SISDEPEN_CAB = ["ciclo", "Ano", "Referência", "Tipo do Estabelecimento", "Nome do Estabelecimento", "UF",
                "1.3 Capacidade do estabelecimento | Masculino | Total", "1.3 Capacidade do estabelecimento | Feminino | Total",
                "4.1 População prisional | Presos provisórios (sem condenação) | Total", "4.1 População prisional | Total",
                "4.5 Movimentação no Sistema Prisional (total do período de referência) | Entradas | Número de inclusões originárias | Total",
                "4.5 Movimentação no Sistema Prisional (total do período de referência) | Saídas | Alvarás de soltura | Total",
                "4.5 Movimentação no Sistema Prisional (total do período de referência) | Saídas | Abandonos | Total",
                "4.5 Movimentação no Sistema Prisional (total do período de referência) | Saídas | Total de óbitos | Total",
                "4.5 Movimentação no Sistema Prisional (total do período de referência) | Autorizações de saída | Permissão de saída | Total",
                "4.5 Movimentação no Sistema Prisional (total do período de referência) | Autorizações de saída | Saída temporária | Total"]
SISDEPEN_LINHAS = [
    ["19", "2025", "2025/2", "Domiciliar com monitoramento eletrônico", "NÚCLEO DE MONITORAMENTO DE BRASILÉIA", "AC",
     "190.0", "15.0", "38.0", "205", "55.0", "61.0", "0.0", "4.0", "0.0", "0.0"],
    ["19", "2025", "2025/2", "Penitenciária", "PENITENCIÁRIA ESTADUAL DE RIO BRANCO", "AC",
     "800.0", "", "120.0", "950", "300.0", "250.0", "12.0", "3.0", "40.0", "180.0"],
    ["19", "2025", "2025/2", "Penitenciária", "PENITENCIÁRIA DE TESTE", "SP", "1000", "0", "10", "1500", "400", "380", "20", "1", "0", "90"],
]


def test_sisdepen_soma_por_estado(tmp_path):
    from app.collectors import seguranca
    texto = "﻿" + ";".join(SISDEPEN_CAB) + "\n" + "\n".join(";".join(l) for l in SISDEPEN_LINHAS) + "\n"
    r = seguranca.agregar_sisdepen(texto.lstrip("﻿"))
    assert r["referencia"] == "2025/2" and r["colunas_faltando"] == []
    ac = r["por_uf"]["AC"]
    assert ac["populacao"] == 1155 and ac["populacao_domiciliar"] == 205 and ac["populacao_celas"] == 950
    assert ac["vagas"] == 1005 and ac["entradas"] == 355 and ac["abandonos"] == 12 and ac["saidas_temporarias"] == 180
    caminho = tmp_path / "sisdepen.csv"
    caminho.write_bytes(texto.encode("utf-8"))
    assert seguranca.coletar_sisdepen(arquivo_local=str(caminho)) == 2
    html = ('<a href="/senappen/pt-br/servicos/sisdepen/bases-de-dados/2025/18o-ciclo-base-de-dados-2025-1-semestre.csv/@@download/file">'
            '<a href="/senappen/pt-br/servicos/sisdepen/bases-de-dados/2025/19o-ciclo-base-de-dados-2025-2-semestre.csv/@@download/file">')
    assert seguranca.links_sisdepen(html)[0].endswith("19o-ciclo-base-de-dados-2025-2-semestre.csv/@@download/file")


# Anuário Brasileiro de Segurança Pública 2026, aba T01 (linhas como o openpyxl entrega; trecho real)
T01 = [("TABELA 01", None), ("Mortes violentas intencionais (1)",), ("Brasil e Unidades da Federação - 2024-2025",), (None,),
       ("Brasil e Unidades da Federação", "Crimes Violentos Letais Intencionais", None, None, None, None, None,
        "Policiais Civis e Militares vítimas de CVLI", None, "Morte Decorrente de Intervenção Policial", None,
        "Mortes Violentas Intencionais", None, None, None, None),
       (None, "Homicídio Doloso", None, "Latrocínio", None, "Lesão Corporal Seguida de Morte", None, None, None, None, None,
        None, None, None, None, None),
       (None, "Ns. Absolutos", None, "Ns. Absolutos", None, "Ns. Absolutos", None, "Ns. Absolutos", None, "Ns. Absolutos",
        None, "Ns. Absolutos", None, "Taxa (2)", None, "Variação (%)"),
       (None, "2024 (3)", 2025, "2024 (3)", 2025, "2024 (3)", 2025, "2024 (3)", 2025, "2024 (3)", 2025, "2024 (3)", 2025,
        "2024 (3)", 2025, None),
       ("Brasil", 36440, 32914, 969, 807, 774, 659, 144, 139, 6237, 6602, 44220, 40775, 20.80121363933038, 19.105426800076884, -8.15),
       (None,), ("Norte",),
       ("Acre", 165, 175, 1, 6, 3, 1, "-", "-", 10, 9, 179, 191, 20.3263341853739, 21.59724640762032, 6.25),
       ("São Paulo (5)", 2630, 2527, 170, 131, 138, 122, 32, 30, 813, 835, 3751, 3615, 8.159102454356336, 7.844745477721238, -3.85),
       ("Fonte: Secretarias Estaduais de Segurança Pública e/ou Defesa Social",)]


def test_anuario_tabela_01():
    from app.collectors import seguranca
    d = seguranca.ler_t01([tuple(l) + (None,) * (16 - len(l)) for l in T01])
    assert set(d) == {2024, 2025}
    assert d[2025]["BR"]["mvi"] == 40775 and d[2025]["BR"]["taxa_mvi"] == 19.11
    assert d[2025]["SP"]["homicidio_doloso"] == 2527 and d[2024]["AC"]["policiais_mortos"] is None
    assert d[2025]["AC"]["mortes_intervencao"] == 9


def test_rota_seguranca(tmp_path):
    """Junta prisional e mortes violentas por estado, com taxas pela população do IBGE."""
    from app.collectors import seguranca
    from app.models import Indicador
    db = SessionLocal()
    for uf, pop in (("AC", 900000), ("SP", 46000000)):
        reg = Registro(fonte="ibge", tipo="indicador_teste_seg", chave=f"pop-{uf}", dados={})
        db.add(reg)
        db.flush()
        db.add(Indicador(registro_id=reg.id, nome="populacao", uf=uf, periodo="2099", ano=2099, valor=pop))
    db.commit()
    db.close()
    texto = ";".join(SISDEPEN_CAB) + "\n" + "\n".join(";".join(l) for l in SISDEPEN_LINHAS) + "\n"
    (tmp_path / "s.csv").write_text(texto, encoding="utf-8")
    seguranca.coletar_sisdepen(arquivo_local=str(tmp_path / "s.csv"))
    d = cliente.get("/seguranca").json()
    ac = d["estados"]["AC"]["prisional"]
    assert ac["taxa_aprisionamento"] == round(1155 / 900000 * 1e5, 1) and ac["presos_por_dia"] == round(355 / 184, 1)
    assert ac["deficit_vagas"] == 950 - 1005 and ac["nao_voltaram_por_mil_saidas"] == round(1000 * 12 / 180, 1)
    assert d["brasil"]["prisional"]["populacao"] == 2655 and d["referencias"]["prisional"] == "2025/2"


# Sinesp VDE 2026 (bancovde-2026.xlsx): cabeçalho e linhas reais, resumidos
VDE_CAB = ("uf", "municipio", "evento", "data_referencia", "agente", "arma", "faixa_etaria", "feminino", "masculino",
           "nao_informado", "total_vitima", "total", "total_peso", "abrangencia")


def test_sinesp_vde_por_estado_e_mes(tmp_path):
    import datetime
    from app.collectors import seguranca
    d = lambda m: datetime.datetime(2026, m, 1)
    linhas = [VDE_CAB,
              ("AC", "ACRELÂNDIA", "Feminicídio", d(1), None, None, None, 0, 0, 0, 0, None, None, "Estadual"),
              ("AC", "RIO BRANCO", "Homicídio doloso", d(1), None, None, None, 1, 6, 0, 7, None, None, "Estadual"),
              ("AC", "XAPURI", "Homicídio doloso", d(1), None, None, None, 0, 2, 0, 2, None, None, "Estadual"),
              ("AC", "RIO BRANCO", "Homicídio doloso", d(2), None, None, None, 0, 3, 0, 3, None, None, "Estadual"),
              ("AC", "RIO BRANCO", "Mandado de prisão cumprido", d(1), None, None, None, None, None, None, None, 40, None, "Estadual"),
              ("AC", "XAPURI", "Mandado de prisão cumprido", d(2), None, None, None, None, None, None, None, 5, None, "Estadual"),
              ("AC", "RIO BRANCO", "Suicídio", d(1), None, None, None, 0, 1, 0, 1, None, None, "Estadual")]
    r = seguranca.agregar_sinesp(linhas)
    assert r["AC"]["2026-01"] == {"feminicidio": 0, "homicidio_doloso": 9, "mandados_cumpridos": 40}
    assert r["AC"]["2026-02"] == {"homicidio_doloso": 3, "mandados_cumpridos": 5}
    import openpyxl
    wb = openpyxl.Workbook()
    for l in linhas:
        wb.active.append(l)
    wb.save(tmp_path / "vde.xlsx")
    seguranca.coletar_sinesp(ano=2026, arquivo_local=str(tmp_path / "vde.xlsx"))
    o = cliente.get("/seguranca").json()
    ac = o["estados"]["AC"]["ocorrencias"]
    assert ac["homicidio_doloso"] == 12 and ac["mandados_cumpridos"] == 45 and ac["detidos_por_dia"] == round(45 / 59, 1)
    assert o["referencias"]["ocorrencias"] == {"de": "2026-01", "ate": "2026-02", "meses": 2, "dias": 59}
    assert o["historico"]["ocorrencias"]["2026"]["brasil"]["homicidio_doloso"] == 12
    assert o["brasil"]["serie_mensal"][0]["homicidio_doloso"] == 9


# Raio-X das Forças de Segurança Pública 2026 (FBSP), Tabela 02 resumida; SP sem bombeiros (fazem parte da PM)
RAIOX_T02 = [
    ("TABELA 02", "(Voltar ao índice)"),
    ("Efetivo da ativa das agências de segurança pública",),
    ("Brasil e Unidades da Federação - 2025",),
    ("Brasil e Unidades da Federação", "Polícia Militar (1)", "Corpo de Bombeiros (1)", "Polícia Civil (1)",
     "Perícia Técnica (1)", "Polícia Penal (1)", "Polícia Federal (2)", "Polícia Rodoviária Federal (1)",
     "Polícia Penal Federal (3)", "Polícia Legislativa (4)", "Guarda Civil \nMunicipal (5)", "Total"),
    ("Brasil", 413319, 63002, 96902, 19340, 91850, 12536, 12328, 1224, 563, 107457, 818521),
    ("Acre (6)", 2375, 680, 994, 78, 1155, "...", "...", "...", "...", "-", 5282),
    ("São Paulo (7)", 82250, None, 19420, 4785, 24898, "...", "...", "...", "...", 30184, 161537),
    ("Fonte: Portais da Transparência do Governo Federal e dos Estados",),
]


def test_raiox_efetivo_por_estado():
    from app.collectors import seguranca
    ano, d = seguranca.ler_raiox_t02([tuple(l) + (None,) * (12 - len(l)) for l in RAIOX_T02])
    assert ano == 2025 and set(d) == {"BR", "AC", "SP"}
    assert d["BR"]["policia_federal"] == 12536 and d["BR"]["policia_penal_federal"] == 1224
    assert d["BR"]["policia_penal"] == 91850 and d["BR"]["guardas_municipais"] == 107457
    assert d["AC"]["guardas_municipais"] == 0 and d["AC"]["policia_federal"] is None
    assert d["SP"]["bombeiros"] is None and d["SP"]["policia_militar"] == 82250 and d["SP"]["total"] == 161537


# RSS do g1 Política (10/10/2026), resumido: o resumo vem em atom:subtitle
G1_RSS = """<?xml version='1.0' encoding='UTF-8'?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/" version="2.0">  <channel>
<title>g1 &gt; Política</title> <item> <title>Justiça italiana marca para o fim de outubro novo julgamento sobre extradição de Zambelli</title>
<atom:subtitle>Justiça da Itália vai reavaliar, em 29 de outubro, um pedido de extradição feito pelo Brasil.</atom:subtitle>
<link>https://g1.globo.com/politica/noticia/2026/10/10/justica-italiana.ghtml</link>
<guid isPermaLink="true">https://g1.globo.com/politica/noticia/2026/10/10/justica-italiana.ghtml</guid>
<pubDate>Sat, 10 Oct 2026 13:41:00 -0000</pubDate></item></channel></rss>"""
UOL_RSS = """<rss><channel><item><title><![CDATA[Chuva forte atinge capital paulista]]></title><link>https://noticias.uol.com.br/a</link>
<description>Temporal</description><pubDate>Sat, 10 Oct 2026 10:00:00 -0300</pubDate></item>
<item><title><![CDATA[Senado aprova projeto de lei da reforma]]></title><link>https://noticias.uol.com.br/b</link>
<description>Votação no plenário</description><pubDate>Sat, 10 Oct 2026 11:00:00 -0300</pubDate></item></channel></rss>"""


def test_noticias_rss():
    from app.collectors import noticias
    it = noticias.ler_feed(G1_RSS, "g1", True)
    assert len(it) == 1 and it[0]["resumo"].startswith("Justiça da Itália") and it[0]["data"].startswith("2026-10-10T13:41")
    uol = noticias.ler_feed(UOL_RSS, "UOL", False)  # feed geral: só a de política fica
    assert [i["titulo"] for i in uol] == ["Senado aprova projeto de lei da reforma"]


# Orçamento da despesa 2026 (Portal da Transparência, arquivo de dados abertos), cabeçalho real e 2 linhas
ORC_CAB = ('"EXERCÍCIO";"CÓDIGO ÓRGÃO SUPERIOR";"NOME ÓRGÃO SUPERIOR";"CÓDIGO ÓRGÃO SUBORDINADO";"NOME ÓRGÃO SUBORDINADO";'
           '"CÓDIGO UNIDADE ORÇAMENTÁRIA";"NOME UNIDADE ORÇAMENTÁRIA";"CÓDIGO FUNÇÃO";"NOME FUNÇÃO";"CÓDIGO SUBFUNÇÃO";'
           '"NOME SUBFUNÇÃO";"CÓDIGO PROGRAMA ORÇAMENTÁRIO";"NOME PROGRAMA ORÇAMENTÁRIO";"CÓDIGO AÇÃO";"NOME AÇÃO";'
           '"CÓDIGO CATEGORIA ECONÔMICA";"NOME CATEGORIA ECONÔMICA";"CÓDIGO GRUPO DE DESPESA";"NOME GRUPO DE DESPESA";'
           '"CÓDIGO ELEMENTO DE DESPESA";"NOME ELEMENTO DE DESPESA";"ORÇAMENTO INICIAL (R$)";"ORÇAMENTO ATUALIZADO (R$)";'
           '"ORÇAMENTO EMPENHADO (R$)";"ORÇAMENTO REALIZADO (R$)";"% REALIZADO DO ORÇAMENTO (COM RELAÇÃO AO ORÇAMENTO ATUALIZADO)"')
ORC_LINHAS = [
    '"2026";"03000";"Tribunal de Contas da União";"03000";"Tribunal de Contas da União - Unidades com vínculo direto";"03101";'
    '"TRIBUNAL DE CONTAS DA UNIAO";"01";"Legislativa";"032";"Controle externo";"0034";"PROGRAMA";"4018";"FISCALIZACAO";"3";'
    '"DESPESAS CORRENTES";"3";"Outras Despesas Correntes";"40";"TI";"0,00";"0,00";"4317,26";"2368,56";"0,00%"',
    '"2026";"03000";"Tribunal de Contas da União";"03000";"Tribunal de Contas da União - Unidades com vínculo direto";"03101";'
    '"TRIBUNAL DE CONTAS DA UNIAO";"01";"Legislativa";"032";"Controle externo";"0034";"PROGRAMA";"4018";"FISCALIZACAO";"3";'
    '"DESPESAS CORRENTES";"3";"Outras Despesas Correntes";"39";"Serviços";"1.000,00";"2.000,50";"837808,44";"484104,03";"0,00%"']


def test_orcamento_por_orgao():
    from app.collectors import orcamento
    d = orcamento.agregar_orcamento(ORC_CAB + "\n" + "\n".join(ORC_LINHAS) + "\n")
    o = d["03000"]
    assert o["orgaoSuperior"] == "Tribunal de Contas da União" and o["pago"] == round(2368.56 + 484104.03, 2)
    assert o["orcamento_atualizado"] == 2000.5 and o["empenhado"] == round(4317.26 + 837808.44, 2)
    assert o["funcoes"] == {"Legislativa": round(2368.56 + 484104.03, 2)}


def test_rota_orgaos_com_orcamento():
    from app.collectors import orcamento
    db = SessionLocal()
    # ano antigo de propósito: o banco dos testes é compartilhado e o "ano mais recente" das outras rotas não muda
    orcamento.gravar_orcamento(db, 2001, orcamento.agregar_orcamento(ORC_CAB + "\n" + "\n".join(ORC_LINHAS) + "\n"))
    db.commit()
    db.close()
    d = cliente.get("/orgaos", params={"ano": 2001}).json()
    tcu = next(i for i in d["itens"] if i["codigo"] == "03000")
    assert tcu["orcamento_atualizado"] == 2000.5 and tcu["pago"] == round(2368.56 + 484104.03, 2)
    det = cliente.get("/orgaos/03000").json()
    assert det["funcoes"][0]["funcao"] == "Legislativa" and det["por_ano"][-1]["orcamento_atualizado"] == 2000.5


# SCR.data (Banco Central), planilha_202603.csv: cabeçalho real e linhas resumidas
SCR_LINHAS = [
    "﻿data_base;uf;tcb;sr;cliente;ocupacao;cnae_secao;cnae_subclasse;porte;modalidade;origem;indexador;numero_de_operacoes;"
    "a_vencer_ate_90_dias;a_vencer_de_91_ate_360_dias;a_vencer_de_361_ate_1080_dias;a_vencer_de_1081_ate_1800_dias;"
    "a_vencer_de_1801_ate_5400_dias;a_vencer_acima_de_5400_dias;vencido_acima_de_15_dias;carteira_ativa;"
    "carteira_inadimplida_arrastada;ativo_problematico",
    '2026-03-31;AC;-;S1;PF;PF - Aposentado/pensionista;"-";"-";PF - Acima de 20 salários mínimos            ;PF - Cartão de crédito;'
    'Sem destinação específica;Prefixado;621;5098891,65;1513370,81;57469,66;874,51;1128,42;0,00;303671,42;6975406,47;251431,29;330069,52',
    '2026-03-31;AC;-;S1;PF;PF - Aposentado/pensionista;"-";"-";PF - Acima de 20 salários mínimos            ;PF - Empréstimo com '
    'consignação em folha;Sem destinação específica;Prefixado;515;1568792,70;5088565,71;11118144,02;7276579,65;6476836,67;0,00;'
    '85598,08;31614516,83;408834,68;484833,04',
    '2026-03-31;AC;-;S1;PJ;-;"C";"-";PJ - Médio;PJ - Capital de giro;Sem destinação específica;Prefixado;<= 15;0,00;0,00;0,00;0,00;0,00;0,00;0,00;1000,00;100,00;100,00',
]


def test_scr_por_estado():
    from app.collectors import bcb_scr
    ref, d = bcb_scr.agregar_scr(l.lstrip("﻿") if i == 0 else l for i, l in enumerate(SCR_LINHAS))
    assert ref == "2026-03-31"
    assert d["AC"]["pf"]["carteira"] == round(6975406.47 + 31614516.83, 2)
    assert d["AC"]["pf"]["inadimplencia"] == round(100 * (251431.29 + 408834.68) / (6975406.47 + 31614516.83), 2)
    assert d["AC"]["pj"] == {"carteira": 1000.0, "inadimplida": 100.0, "inadimplencia": 10.0}


def test_unidades_da_wikipedia():
    from scripts.midia_site import sigla_de, unidade_de_resultado
    u = unidade_de_resultado("Batalhão de Operações Policiais Especiais (Rio de Janeiro)",
                             'O <span class="searchmatch">BOPE</span> é uma unidade da Polícia Militar do Estado do Rio de Janeiro',
                             "Rio de Janeiro", "RJ")
    assert u and u["sigla"] == "BOPE" and u["corp"] == "pm" and u["uf"] == "RJ"
    # unidade do Exército não entra
    assert unidade_de_resultado("Batalhão de Infantaria Blindado", "Exército Brasileiro em Santa Maria, Rio Grande do Sul",
                                "Rio Grande do Sul", "RS") is None
    # de outro estado não entra
    assert unidade_de_resultado("Batalhão de Choque", "da Polícia Militar da Bahia", "Ceará", "CE") is None
    assert sigla_de("Batalhão de Missões Especiais") == "BME"


def test_noticias_charset_e_html_escapado():
    from app.collectors import noticias
    xml = ('<?xml version="1.0" encoding="ISO-8859-1"?><rss><channel><item><title>Decisão jurídica do TSE</title>'
           '<link>https://www1.folha.uol.com.br/a</link><description>O presidente do &lt;a href="https://x.com/tse/"&gt;TSE&lt;/a&gt; disse</description>'
           '<pubDate>Mon, 12 Oct 2026 10:00:00 -0300</pubDate></item></channel></rss>').encode("latin-1")
    texto = noticias.decodificar(xml)
    it = noticias.ler_feed(texto, "Folha de S.Paulo", True, "economia")[0]
    assert it["titulo"] == "Decisão jurídica do TSE" and it["tema"] == "economia"
    assert it["resumo"] == "O presidente do TSE disse"


def test_situacao_proposicoes_arquivo_anual(monkeypatch):
    """Arquivo anual da Câmara (proposicoes-AAAA.json): situação atual e data de apresentação das proposições já salvas."""
    from app.collectors import legislacao
    from app.models import Proposicao
    with SessionLocal() as db:
        for ide in ("880001", "880002"):
            if not db.query(Proposicao).filter_by(casa="camara", id_externo=ide).first():
                db.add(Proposicao(casa="camara", id_externo=ide, sigla_tipo="PEC", numero="1", ano=2025))
        db.commit()
    arquivo = {"dados": [
        {"id": 880001, "uri": "x", "siglaTipo": "PEC", "numero": 1, "ano": 2025, "ementa": "Altera a Constituição",
         "dataApresentacao": "2025-03-04T10:00", "ultimoStatus": {"dataHora": "2026-09-01T12:00", "siglaOrgao": "PLEN",
                                                                   "descricaoTramitacao": "Recebimento",
                                                                   "descricaoSituacao": "Aguardando Deliberação"}},
        {"id": 880002, "siglaTipo": "PEC", "ementa": "Outra", "ultimoStatus": {"descricaoSituacao": None,
                                                                               "descricaoTramitacao": "Arquivamento"}},
        {"id": 999999, "siglaTipo": "PL", "ementa": "Não está no banco", "ultimoStatus": {"descricaoSituacao": "Arquivada"}},
    ]}
    monkeypatch.setattr(http, "get_json", lambda url, *a, **k: arquivo if "2025" in url else {"dados": []})
    assert legislacao.situacao_proposicoes_camara(ano=2025) == 2
    with SessionLocal() as db:
        p = {x.id_externo: x for x in db.query(Proposicao).filter(Proposicao.id_externo.in_(["880001", "880002"]))}
    assert p["880001"].situacao == "Aguardando Deliberação" and p["880001"].data_apresentacao == date(2025, 3, 4)
    assert p["880002"].situacao == "Arquivamento"
    lista = cliente.get("/proposicoes", params={"ano": 2025, "tipo": "PEC", "limit": 500}).json()
    assert any(i.get("situacao") == "Aguardando Deliberação" for i in lista["itens"])


def test_obrasgov_pagina_mesmo_com_last_true(monkeypatch):
    """A API real devolve `last: true` em toda página; só uma página curta encerra (22/10/2026)."""
    paginas = {0: 3, 1: 3, 2: 1}  # tamanho 3: duas páginas cheias e uma curta

    def pagina(url, params=None, headers=None):
        p = params["pagina"]
        n = paginas.get(p, 0)
        return {"content": [{"idUnico": f"x{p}-{i}", "nome": "Obra"} for i in range(n)], "last": True,
                "totalElements": n, "totalPages": 1}

    monkeypatch.setattr(http, "get_json", pagina)
    assert obrasgov.coletar_obras(ufs=["AC"], tamanho=3) == 7


def test_economia_empresas_e_resumo_contratos(monkeypatch):
    from app.models import Contrato
    db = SessionLocal()
    db.add(Registro(fonte="ibge", tipo="empresas_economia", chave="2024", ano=2024, dados={"ano": 2024, "setores": {
        "servicos": {"empresas": 100, "pessoal": 1000, "receita": 1e9, "gastos_pessoal": 2e8, "valor_adicionado": 6e8}}}))
    db.commit()
    d = cliente.get("/economia-empresas").json()
    s = d["setores"][0]
    assert s["receita_media"] == 1e7 and s["margem"] == 40.0 and s["partes"]["insumos"] == 40.0
    assert d["total"]["empresas"] == 100
    db.close()


def test_atuacao_presenca_e_temas():
    from datetime import date as _d, timedelta
    from app.models import Parlamentar, Votacao, Voto
    db = SessionLocal()
    p = Parlamentar(casa="camara", id_externo="999001", nome="Fulana Teste", partido="PT", uf="SP")
    db.add(p)
    db.flush()
    hoje = _d.today()
    vs = [Votacao(casa="camara", id_externo=f"t{i}", data=hoje - timedelta(days=i + 1), orgao="PLEN", descricao="x", secreta=False) for i in range(3)]
    db.add_all(vs)
    db.flush()
    db.add_all([Voto(votacao_id=vs[0].id, parlamentar_id=p.id, voto="Sim"), Voto(votacao_id=vs[1].id, parlamentar_id=p.id, voto="Não")])
    outra = Parlamentar(casa="camara", id_externo="999002", nome="Outro", partido="PL", uf="RJ")
    db.add(outra)
    db.flush()
    db.add(Voto(votacao_id=vs[2].id, parlamentar_id=outra.id, voto="Sim"))
    db.commit()
    pid = p.id
    db.close()
    a = cliente.get(f"/parlamentares/{pid}/atuacao").json()
    assert a["presenca"]["votou"] == 2 and a["presenca"]["total"] >= 3
    assert "luta" in a


def test_saneamento_pessoas_e_pct():
    from app.collectors.saneamento import _serie, montar_saneamento
    resp = [{"resultados": [
        {"classificacoes": [{"categoria": {"72129": "Total"}}], "series": [{"localidade": {"id": "35"}, "serie": {"2022": "100"}}]},
        {"classificacoes": [{"categoria": {"72144": "Rede"}}], "series": [{"localidade": {"id": "35"}, "serie": {"2022": "90"}}]}]}]
    tot, com = _serie(resp, 72129), _serie(resp, 72144)
    d = montar_saneamento({"agua": (tot, com)}, {"SP": 1000.0}, {"SP": 99.0})
    assert d["SP"]["agua"]["pct"] == 90.0 and d["SP"]["agua"]["pessoas"] == 900 and d["SP"]["luz"]["sem_pessoas"] == 10


def test_obras_gestao_porcentagens_e_atraso():
    from datetime import date
    from types import SimpleNamespace as N
    from app.obras_gestao import categoria, eh_estadual, nome_municipio, resumir
    d = date(2026, 10, 22)
    o = lambda i, s, f, v: N(id=i, nome="n", descricao="d", situacao=s, executor="X", valor_previsto=v, fim_previsto=f)
    r = resumir([o(1, "Concluída", date(2020, 1, 1), 100), o(2, "Em execução", date(2026, 1, 1), 300), o(3, "Paralisada", date(2027, 1, 1), 100),
                 o(4, "Cancelada", None, 999), o(5, "Cadastrada", None, 0)], d)
    assert r["total"] == 5 and r["pct_concluido"] == 25.0 and r["pct_concluido_valor"] == 20.0
    assert r["atraso"]["obras"] == 1 and r["atraso"]["dias_maior"] == 294 and r["no_prazo"] == 1 and r["sem_data_prevista"] == 1
    assert categoria("Inacabada") == "parada" and eh_estadual("ESTADO DO RIO DE JANEIRO") and not eh_estadual("DEPARTAMENTO NACIONAL DE INFRAESTRUTURA DE TRANSPORTES")
    assert nome_municipio("PREFEITURA MUNICIPAL DE SÃO JOSÉ (SC)") == "SAO JOSE" and nome_municipio("MUNICÍPIO DE JUIZ DE FORA") == "JUIZ DE FORA"


def test_rota_obras_gestao():
    from datetime import date as _d
    from app.models import Obra
    db = SessionLocal()
    base = Registro(fonte="obrasgov", tipo="obra", chave="og1", dados={})
    db.add(base)
    db.flush()
    for i, (s, ex, fim) in enumerate([("Concluída", "ESTADO DO ZZ", _d(2020, 1, 1)), ("Em execução", "ESTADO DO ZZ", _d(2021, 1, 1)),
                                      ("Paralisada", "PREFEITURA MUNICIPAL DE BELA VISTA", _d(2022, 1, 1))]):
        r = Registro(fonte="obrasgov", tipo="obra", chave=f"og-zz{i}", dados={}, uf="ZZ")
        db.add(r)
        db.flush()
        db.add(Obra(registro_id=r.id, id_unico=f"zz{i}", nome="n", uf="ZZ", situacao=s, executor=ex, valor_previsto=100.0, fim_previsto=fim))
    db.commit()
    uf = cliente.get("/obras-gestao", params={"escopo": "uf", "uf": "ZZ"}).json()
    assert uf["total"] == 2 and uf["pct_concluido"] == 50.0 and uf["atraso"]["obras"] == 1
    mun = cliente.get("/obras-gestao", params={"escopo": "municipios", "uf": "ZZ"}).json()["municipios"]
    assert mun["BELA VISTA"]["total"] == 1 and mun["BELA VISTA"]["atraso"]["obras"] == 1
    assert cliente.get("/obras-gestao").json()["total"] >= 3
    db.close()


def test_obras_gestao_ignora_prazo_absurdo():
    from datetime import date
    from types import SimpleNamespace as N
    from app.obras_gestao import resumir
    o = N(id=1, nome="n", descricao="d", situacao="Em execução", executor="X", valor_previsto=1.0, fim_previsto=date(1900, 1, 1))
    r = resumir([o], date(2026, 10, 22))
    assert r["atraso"]["obras"] == 0 and r["sem_data_prevista"] == 1


def test_rota_obras_gestao_lista():
    from app.models import Obra
    db = SessionLocal()
    r = Registro(fonte="obrasgov", tipo="obra", chave="og-yy1", dados={}, uf="YY")
    db.add(r)
    db.flush()
    db.add(Obra(registro_id=r.id, id_unico="yy1", nome="n", descricao="Escola nova", uf="YY", situacao="Cadastrada",
                executor="PREFEITURA MUNICIPAL DE BELA VISTA", valor_previsto=500.0))
    db.commit()
    d = cliente.get("/obras-gestao/lista", params={"uf": "YY"}).json()
    row = dict(zip(d["campos"], d["itens"][0]))
    assert row["cat"] == "nao_iniciada" and row["tipo"] == "M" and row["municipio"] == "BELA VISTA" and row["nome"] == "Escola nova" and row["fim"] == ""
    db.close()


def test_obras_categoria_paralisada():
    from app.obras_gestao import categoria
    assert categoria("Paralisada") == "parada" and categoria("Em execução") == "execucao" and categoria("Cadastrada") == "nao_iniciada"


def test_propostas_resumo_por_tema():
    from scripts.propostas_resumo import resumir
    txt = ("Vamos ampliar o policiamento ostensivo e reduzir a criminalidade nos bairros mais violentos da capital.\n\n"
           "Vamos construir novas linhas de ônibus e ampliar a mobilidade urbana com ciclovias e corredores exclusivos.\n\n"
           "Vamos atrair investimento privado e gerar emprego e renda com apoio às microempresas e ao turismo regional.\n\n"
           "Texto curto.\n\nA saúde, a educação, a segurança, o transporte, a economia e o meio ambiente são prioridades de todos os governos.")
    r = resumir(txt)
    assert "policiamento" in r["seguranca"][0] and "ônibus" in r["transporte"][0] and "emprego" in r["economia"][0]
    assert not any("prioridades de todos" in f for f in r.get("saude", []))  # frase que lista todos os assuntos não resume nenhum
