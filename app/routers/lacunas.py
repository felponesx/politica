from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import lacunas
from app.db import get_db
from app.models import Registro
from app.utils import memo, para_uf

router = APIRouter()


def _ou_404(d, tarefa: str):
    if not d:
        raise HTTPException(404, f"Sem dados. Rode a coleta {tarefa}.")
    return d


@router.get("/social", tags=["Social"])
def social(db: Session = Depends(get_db)):
    """Bolsa Família e BPC por estado (beneficiários, valor, por 100 habitantes)."""
    return _ou_404(memo(("social",), lambda: lacunas.social(db)), "transparencia-social")


@router.get("/social/municipios", tags=["Social"])
def social_municipios(uf: str = Query(..., min_length=2, max_length=2), limit: int = Query(60, ge=1, le=500), db: Session = Depends(get_db)):
    """Municípios de um estado (os maiores primeiro) com Bolsa Família e BPC por 100 habitantes."""
    sigla = para_uf(uf)
    if not sigla:
        raise HTTPException(422, "UF inválida.")
    return {"uf": sigla, "itens": lacunas.social_municipios(db, sigla, limit)}


@router.get("/trabalho", tags=["Social"])
def trabalho(db: Session = Depends(get_db)):
    """Desocupação e rendimento do trabalho por estado (PNAD Contínua)."""
    return _ou_404(memo(("trabalho",), lambda: lacunas.trabalho(db)), "ibge-trabalho")


@router.get("/ambiente", tags=["Meio ambiente"])
def ambiente(db: Session = Depends(get_db)):
    """Desmatamento por estado (PRODES, por bioma) e alertas recentes (DETER)."""
    return _ou_404(memo(("ambiente",), lambda: lacunas.ambiente(db)), "inpe-desmatamento")


@router.get("/viagens", tags=["Dinheiro público"])
def viagens(db: Session = Depends(get_db)):
    """Viagens a serviço do governo federal: diárias e passagens por órgão e ano."""
    return _ou_404(memo(("viagens",), lambda: lacunas.viagens(db)), "transparencia-viagens")


@router.get("/acidentes-rodovias", tags=["Segurança"])
def acidentes_rodovias(db: Session = Depends(get_db)):
    """Acidentes nas rodovias federais (PRF): por ano, estado, mês, causa, tipo e rodovia."""
    return _ou_404(memo(("acidentes",), lambda: lacunas.acidentes_rodovias(db)), "prf-acidentes")


@router.get("/transito/malha", tags=["Cidades"])
def transito_malha(db: Session = Depends(get_db)):
    """Quilômetros de via das capitais (OpenStreetMap), por categoria. Não é trânsito em tempo real."""
    return _ou_404(memo(("transito_malha",), lambda: lacunas.transito_malha(db)), "osm-malha-capitais")


@router.get("/transito/agora", tags=["Cidades"])
def transito_agora(db: Session = Depends(get_db)):
    """Congestionamento e velocidade observada nas capitais (TomTom, amostra de vias) e histórico diário."""
    return _ou_404(memo(("transito_agora",), lambda: lacunas.transito_agora(db)), "tomtom-transito")


@router.get("/diarios-oficiais", tags=["Dinheiro público"])
def diarios_oficiais(q: str = Query("", max_length=200), desde: date | None = None, ate: date | None = None, ibge: str | None = Query(None, pattern=r"^\d{7}$"),
                     limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0, le=9950)):
    """Busca nos diários oficiais municipais (Querido Diário). Consulta ao vivo; se o serviço estiver fora do ar, responde 503 (nunca devolve dado antigo como atual)."""
    from app.collectors import querido_diario as qd
    try:
        d = qd.buscar(q, desde, ate, [ibge] if ibge else None, limit, offset)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, f"Querido Diário indisponível no momento ({type(e).__name__}). Tente de novo mais tarde.") from e
    return {**d, "aviso": "Trechos de diários oficiais publicados pelas prefeituras, reunidos pelo projeto Querido Diário (Open Knowledge Brasil). Aparecer num diário não indica irregularidade.", "fonte": "Querido Diário"}


@router.get("/diarios-oficiais/status", tags=["Dinheiro público"])
def diarios_oficiais_status(db: Session = Depends(get_db)):
    """Disponibilidade do Querido Diário (histórico das últimas verificações) e a contagem de diários com termos de contratação."""
    h = db.query(Registro).filter_by(fonte="querido_diario", tipo="disponibilidade", chave="historico").first()
    if not h:
        raise HTTPException(404, "Sem verificações do Querido Diário. Rode a coleta querido-diario.")
    t = db.query(Registro).filter_by(fonte="querido_diario", tipo="termos").order_by(Registro.atualizado_em.desc()).first()
    ultima = (h.dados or {}).get("ultima") or {}
    return {"disponivel_na_ultima_verificacao": ultima.get("disponivel"), "ultima_verificacao": ultima.get("medido_em"), "historico": ((h.dados or {}).get("medicoes") or [])[-50:],
            "termos": (t.dados if t else None), "aviso": "Se 'disponivel' for falso, os números de termos podem ser antigos: confira a data de 'medido_em'."}


@router.get("/ocorrencias", tags=["Escândalos"])
def ocorrencias(etapa: str | None = Query(None, pattern="^(investigacao|denuncia|condenacao|absolvicao|arquivamento|outra)$"), q: str | None = Query(None, max_length=100),
                limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Marcos dos casos curados (investigação, denúncia, condenação, absolvição, arquivamento), cada um com a fonte original."""
    from app import ocorrencias as oc
    return oc.listar(etapa, q, limit, offset)


@router.get("/caged", tags=["Trabalho"])
def caged(db: Session = Depends(get_db)):
    """Novo CAGED: admissões, desligamentos e saldo por estado e setor nos últimos meses coletados."""
    return _ou_404(memo(("caged",), lambda: lacunas.caged(db)), "caged-saldos")


@router.get("/iva", tags=["Dinheiro público"])
def iva(db: Session = Depends(get_db)):
    """Reforma tributária do consumo (CBS + IBS): calendário e o que as fontes oficiais já publicam sobre a arrecadação."""
    return memo(("iva",), lambda: lacunas.iva(db))


@router.get("/servidores", tags=["Dinheiro público"])
def servidores(db: Session = Depends(get_db)):
    """Servidores civis federais por órgão e estado: quantidade, remuneração bruta, abate-teto e líquida (só somas)."""
    return _ou_404(memo(("servidores",), lambda: lacunas.servidores(db)), "transparencia-servidores")


@router.get("/fundos", tags=["Dinheiro público"])
def fundos(db: Session = Depends(get_db)):
    """Fundo eleitoral (FEFC) por partido e eleição."""
    return _ou_404(memo(("fundos",), lambda: lacunas.fundos(db)), "tse-fundos")


@router.get("/energia-tarifas", tags=["Indicadores"])
def energia_tarifas(db: Session = Depends(get_db)):
    """Tarifa residencial de energia por distribuidora (ANEEL)."""
    return _ou_404(memo(("energia",), lambda: lacunas.energia(db)), "aneel-tarifas")


@router.get("/cpis", tags=["Congresso"])
def cpis(db: Session = Depends(get_db)):
    """CPIs e CPMIs da Câmara e do Senado (nome, datas, situação)."""
    return _ou_404(memo(("cpis",), lambda: lacunas.cpis(db)), "congresso-cpis")


@router.get("/aeroportos", tags=["Infraestrutura"])
def aeroportos(db: Session = Depends(get_db)):
    """Aeródromos públicos (ANAC): total, por estado, situação e operação noturna."""
    return _ou_404(memo(("aeroportos",), lambda: lacunas.aeroportos(db)), "anac-aerodromos")


@router.get("/multas-ambientais", tags=["Meio ambiente"])
def multas_ambientais(db: Session = Depends(get_db)):
    """Autos de infração do IBAMA por estado e ano (quantidade e valor aplicado), sem nomes."""
    return _ou_404(memo(("multas-amb",), lambda: lacunas.multas_ambientais(db)), "ibama-multas")


@router.get("/lista-suja", tags=["Trabalho"])
def lista_suja(db: Session = Depends(get_db)):
    """Cadastro de Empregadores (trabalho análogo ao de escravo): totais por estado e ano, sem nomes."""
    return _ou_404(memo(("lista-suja",), lambda: lacunas.lista_suja(db)), "mte-lista-suja")


@router.get("/renuncia-fiscal", tags=["Dinheiro"])
def renuncia_fiscal(db: Session = Depends(get_db)):
    """Gastos tributários (renúncia fiscal) por função orçamentária e região, ano-base mais novo."""
    return _ou_404(memo(("renuncia",), lambda: lacunas.renuncia_fiscal(db)), "receita-renuncia-fiscal")


@router.get("/tcu-irregulares", tags=["Empresas punidas"])
def tcu_irregulares(db: Session = Depends(get_db)):
    """Totais de responsáveis com contas julgadas irregulares pelo TCU (por estado, ano e tipo). Sem nomes nem documentos."""
    return _ou_404(memo(("tcu-irreg",), lambda: lacunas.tcu_irregulares(db)), "tcu-contas-irregulares")
