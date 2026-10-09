from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ParlamentarOut(Base):
    id: int
    casa: str
    nome: str
    partido: str | None
    uf: str | None
    foto_url: str | None
    email: str | None


class VotacaoOut(Base):
    id: int
    casa: str
    id_externo: str
    data: date | None
    orgao: str | None
    descricao: str | None
    materia: str | None
    resultado: str | None
    ementa: str | None = None
    secreta: bool = False
    placar_oficial: dict | None = None


class ProposicaoOut(Base):
    id: int
    casa: str
    sigla_tipo: str | None
    numero: str | None
    ano: int | None
    ementa: str | None
    data_apresentacao: date | None


class DespesaOut(Base):
    id: int
    ano: int
    mes: int | None
    tipo: str | None
    fornecedor: str | None
    cnpj_cpf: str | None
    valor: float
    url_documento: str | None


class RegistroOut(Base):
    id: int
    fonte: str
    tipo: str
    chave: str
    uf: str | None
    ano: int | None
    titulo: str | None
    valor: float | None
    dados: dict


class ColetaOut(Base):
    id: int
    fonte: str
    tarefa: str
    parametros: dict
    inicio: datetime | None
    fim: datetime | None
    status: str
    itens: int
    erro: str | None


class Pagina(BaseModel):
    total: int
    itens: list
