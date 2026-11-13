"""Votos do STJ pela certidão do acórdão e relatorias do TSE — textos reais dos Espelhos de Acórdãos (set/2026) e do arquivo processual do TSE."""
from app.collectors.stj import ler_decisao, unir_chaves
from app.collectors.tse_relatorias import somar_relatorias

# Corte Especial, espelho de 30/09/2026 (dadosabertos.web.stj.jus.br), campo "decisao"
MAIORIA = """Vistos e relatados estes autos em que são partes as acima indicadas,
 acordam os Ministros da CORTE ESPECIAL do Superior Tribunal de
 Justiça, prosseguindo no julgamento, após o voto-vista do Sr.
 Ministro Mauro Campbell Marques, em Sessão Virtual de 08/09/2026 a
 15/09/2026, por maioria, negar provimento ao recurso, nos termos do
 voto da Sra. Ministra Maria Thereza de Assis Moura, que lavrará o
 acórdão.
 Votaram vencidos os Srs. Ministros Sebastião Reis Júnior, Luis
 Felipe Salomão e Antonio Carlos Ferreira.
 Votaram com a Sra. Ministra MARIA THEREZA DE ASSIS MOURA os Srs.
 Ministros Francisco Falcão, João Otávio de Noronha, Humberto
 Martins, Mauro Campbell Marques, Benedito Gonçalves, Raul Araújo,
 Maria Isabel Gallotti e Ricardo Villas Bôas Cueva.
 Presidiu o julgamento o Sr. Ministro Herman Benjamin.
 Afirmou suspeição o Exmo. Sr. Ministro Og Fernandes.
 Não participaram do julgamento os Srs. Ministros Sérgio Kukina,
 Teodoro Silva Santos e Nancy Andrighi."""

UNANIME = """Vistos e relatados estes autos em que são partes as acima indicadas,
 acordam os Ministros da CORTE ESPECIAL, por unanimidade, conhecer
 da questão de ordem para prorrogar, pelo prazo de 1 (um) ano, a
 contar da presente deliberação, a medida cautelar, nos termos do voto do Sr. Ministro João Otávio
 de Noronha.
 Os Srs. Ministros Humberto Martins, Maria Thereza de Assis Moura,
 Luis Felipe Salomão, Mauro Campbell Marques e Nancy
 Andrighi votaram com o Sr. Ministro Relator.
 Presidiu o julgamento o Sr. Ministro Presidente do STJ.
 Ausente, justificadamente, o Sr. Ministro Og Fernandes."""

# Terceira Turma: maioria em que a certidão só lista quem participou (o voto dos demais não é descrito)
PARTICIPARAM = ("Vistos e relatados estes autos em que são partes as acima indicadas, acordam os Ministros da TERCEIRA TURMA, por maioria, "
                "dar provimento parcial ao recurso, nos termos do voto do Sr. Ministro Moura Ribeiro, que lavrará o acórdão. Vencido o Sr. Ministro "
                "Humberto Martins. Participaram do julgamento os Srs. Ministros Nancy Andrighi, Humberto Martins, Ricardo Villas Bôas Cueva, Moura Ribeiro "
                "e Daniela Teixeira (Presidente).")


def test_maioria_com_vencidos_suspeicao_e_ausentes():
    d = ler_decisao(MAIORIA, "MARIA THEREZA DE ASSIS MOURA")
    p = d["posicoes"]
    assert d["resultado"] == "maioria" and d["dispositivo"] == "negar provimento ao recurso"
    assert p["MARIA THEREZA DE ASSIS MOURA"] == "relator_acordao"
    assert {k for k, v in p.items() if v == "vencido"} == {"SEBASTIAO REIS JUNIOR", "LUIS FELIPE SALOMAO", "ANTONIO CARLOS FERREIRA"}
    assert p["FRANCISCO FALCAO"] == p["RICARDO VILLAS BOAS CUEVA"] == "acompanhou"
    assert p["OG FERNANDES"] == "impedido" and p["NANCY ANDRIGHI"] == "nao_participou"
    assert "HERMAN BENJAMIN" not in p and d["presidiu"] == "Herman Benjamin"  # presidir não é voto
    assert d["grafias"]["RICARDO VILLAS BOAS CUEVA"] == "Ricardo Villas Bôas Cueva"


def test_unanime_e_quem_nao_aparece_fica_sem_registro():
    p = ler_decisao(UNANIME, "JOÃO OTÁVIO DE NORONHA")["posicoes"]
    assert p["JOAO OTAVIO DE NORONHA"] == "relator" and p["NANCY ANDRIGHI"] == "acompanhou" and p["OG FERNANDES"] == "ausente"
    assert "RAUL ARAUJO" not in p  # não citado: sem posição, nunca "a favor"


def test_participaram_em_maioria_nao_deduz_voto():
    p = ler_decisao(PARTICIPARAM, "NANCY ANDRIGHI")["posicoes"]
    assert p["HUMBERTO MARTINS"] == "vencido" and p["MOURA RIBEIRO"] == "relator_acordao" and p["NANCY ANDRIGHI"] == "relator"
    assert p["RICARDO VILLAS BOAS CUEVA"] == "participou" and p["DANIELA TEIXEIRA"] == "participou"


def test_nomes_grudados_e_apelidos():
    freq = {"OG FERNANDES": 9000, "ROGERIO SCHIETTI CRUZ": 8000, "OG FERNANDES ROGERIO SCHIETTI CRUZ": 3, "ROGERIO SCHIETTI": 500,
            "MARLUCE CALDAS": 136, "MARIA MARLUCE CALDAS": 8560}
    m = unir_chaves(freq)
    assert m["OG FERNANDES ROGERIO SCHIETTI CRUZ"] == ["OG FERNANDES", "ROGERIO SCHIETTI CRUZ"]
    assert m["ROGERIO SCHIETTI"] == ["ROGERIO SCHIETTI CRUZ"] and m["MARLUCE CALDAS"] == ["MARIA MARLUCE CALDAS"] and m["OG FERNANDES"] == ["OG FERNANDES"]


def test_relatorias_do_tse_so_instancia_3():
    linhas = [{"NR_INSTANCIA": "3", "NM_AUTOR_DECISAO": "NUNES MARQUES", "DS_TIPO_DECISAO": "Acórdão", "DT_DECISAO": "12/05/2025"},
              {"NR_INSTANCIA": "3", "NM_AUTOR_DECISAO": "NUNES MARQUES", "DS_TIPO_DECISAO": "Decisão", "DT_DECISAO": "02/06/2025"},
              {"NR_INSTANCIA": "1", "NM_AUTOR_DECISAO": "EDSON NASCIMENTO CAMPOS", "DS_TIPO_DECISAO": "Sentença", "DT_DECISAO": "27/01/2025"}]
    r = somar_relatorias(linhas)
    assert list(r) == ["NUNES MARQUES"] and r["NUNES MARQUES"]["acordaos"] == 1 and r["NUNES MARQUES"]["monocraticas"] == 1
    assert r["NUNES MARQUES"]["ultima"] == "2025-06-02"
