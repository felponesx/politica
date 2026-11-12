"""Concursos, cursos gratuitos e eventos: leitura dos textos reais (DOU, PNCP) e as rotas."""
from datetime import date, timedelta

from app.collectors.oportunidades import NAO_SHOW, SHOW, detalhes_edital, eh_abertura, ler_show


def _show(t):
    return bool(SHOW.search(t)) and not NAO_SHOW.search(t)


def test_abertura_de_concurso_e_o_que_fica_fora():
    assert eh_abertura("EDITAL Nº 1/2026", "O Presidente torna pública a abertura de inscrições para o concurso público destinado ao "
                       "provimento de cargos de Analista Judiciário do quadro de pessoal")
    # retificação, resultado e seleção de alunos não são abertura de vaga de emprego
    assert not eh_abertura("EDITAL Nº 196", "retificação do concurso público para Professor do Magistério Superior, regido pelo Edital nº 124")
    assert not eh_abertura("EDITAL", "torna pública a abertura das inscrições para o processo seletivo de ingresso no curso de mestrado")
    assert not eh_abertura("AVISO DE LICITAÇÃO", "abertura do pregão eletrônico para aquisição de cargos")


def test_detalhes_do_edital_so_o_que_esta_escrito():
    t = ("abertura de concurso público para o cargo de Analista em Tecnologia da Informação, com total de 37 (trinta e sete) vagas. "
         "A remuneração inicial é de R$ 9.616,67. As inscrições serão realizadas de 13/11/2026 a 15/12/2026. Organizadora: FGV. "
         "Exige-se nível superior. O edital nº 1 de 2026.")
    d = detalhes_edital(t)
    assert d["vagas"] == 37 and d["salario_max"] == 9616.67 and d["banca"] == "FGV"
    assert (d["inscricoes_inicio"], d["inscricoes_fim"]) == ("2026-11-13", "2026-12-15")
    assert d["cargos"][0].startswith("Analista em Tecnologia")
    assert d["escolaridade"] == ["superior"]
    # ano não vira número de vagas; sem texto, nada é preenchido
    assert "vagas" not in detalhes_edital("para preenchimento em 2027 vagas remanescentes")
    assert detalhes_edital("texto sem nenhum dado") == {}


def test_show_no_pncp():
    assert _show("CONTRATAÇÃO DE SHOW MUSICAL DO “EDMAR & JOSIMAR”, A SER REALIZADO NO DIA 08/10/2026 NO EVENTO \"ANIVERSÁRIO DA CIDADE DE 141 ANOS\"")
    assert not _show("Fornecimento de itens para reposição do conjunto de sobressalentes e modernização da rede de Radares Meteorológicos Banda-S")
    assert not _show("Contratação de empresa para inscrições dos vereadores no XII Congresso Nacional de Agentes Públicos")


def test_artista_evento_e_data_do_objeto():
    x = ler_show("Contratação da apresentação do show da dupla “Zé Neto & Cristiano” que acontecerá no dia 12 de dezembro de 2026, na orla do Município")
    assert x["artista"] == "Dupla Zé Neto & Cristiano" and x["data_evento"] == "2026-12-12"
    x = ler_show("APRESENTAÇÃO ARTÍSTICA DA ATRAÇÃO DJALMA FERREIRA NO EVENTO MICARETA DE FEIRA 2026, NO DIA 19/11/2026, SHOW EM TRIO ELETRICO")
    assert x == {"artista": "DJALMA FERREIRA", "evento": "MICARETA DE FEIRA 2026", "data_evento": "2026-11-19"}
    x = ler_show("CONTRATAÇÃO DA BANDA MARLEY RIOS, POR MEIO DE SUA REPRESENTANTE LEGAL, PARA REALIZAÇÃO DE APRESENTAÇÃO")
    assert x["artista"] == "Banda MARLEY RIOS"
    x = ler_show("Contratação da Banda “PAULO NETO” para show no dia 28/11/2026")
    assert x == {"artista": "Banda PAULO NETO", "data_evento": "2026-11-28"}  # o nome entre aspas não vira o nome da festa
    assert ler_show("SHOW ARTÍSTICO - SMCULT") == {}  # sem artista escrito, nada é inventado


def test_rotas():
    from fastapi.testclient import TestClient
    from sqlalchemy import delete

    from app.db import SessionLocal, criar_tabelas
    from app.main import app
    from app.models import Registro
    criar_tabelas()
    client, db = TestClient(app), SessionLocal()
    tipos = ("concurso", "curso", "evento_show", "patrocinio")
    db.execute(delete(Registro).where(Registro.tipo.in_(tipos)))
    hoje = date.today()
    db.add_all([
        Registro(fonte="dou", tipo="concurso", chave="1", dados={"titulo": "EDITAL Nº 1", "orgao": "Câmara dos Deputados", "esfera": "federal",
                 "tipo": "Concurso público", "area": "Legislativo", "publicado": hoje.isoformat(), "url": "https://www.in.gov.br/web/dou/-/x",
                 "inscricoes_inicio": (hoje - timedelta(days=1)).isoformat(), "inscricoes_fim": (hoje + timedelta(days=10)).isoformat()}),
        Registro(fonte="evg", tipo="curso", chave="9", dados={"nome": "Excel básico", "ofertante": "Escola Virtual.Gov (Enap)", "tema": "Gestão",
                 "inscricoes_abertas": True, "url": "https://www.escolavirtual.gov.br/cursos/excel"}),
        Registro(fonte="pncp", tipo="evento_show", chave="a", uf="BA", dados={"artista": "Banda X", "municipio": "Feira de Santana", "uf": "BA",
                 "esfera": "municipal", "valor": 25000.0, "valor_tipo": "homologado", "publicado": hoje.isoformat(), "url": "https://pncp.gov.br/app/editais/1/2026/1",
                 "objeto": "show da Banda X", "data_evento": (hoje + timedelta(days=3)).isoformat()}),
    ])
    db.commit()
    c = client.get("/concursos").json()
    assert c["total"] == 1 and c["itens"][0]["situacao"] == "inscrições abertas" and "estaduais" in c["aviso"]
    assert client.get("/cursos").json()["itens"][0]["nome"] == "Excel básico"
    e = client.get("/eventos").json()
    assert e["total"] == 1 and e["valor_total"] == 25000 and e["por_uf"]["BA"]["qtd"] == 1 and e["proximos"][0]["artista"] == "Banda X"
    assert client.get("/eventos?uf=ba").json()["cidades"][0]["municipio"] == "Feira de Santana"
    assert client.get("/eventos?uf=XX").status_code == 422
    assert client.get("/eventos-patrocinios").status_code == 404  # sem coleta, não inventa
    db.execute(delete(Registro).where(Registro.tipo.in_(tipos)))
    db.commit()
    db.close()
