from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator


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
    em_exercicio: bool | None = None


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
    situacao: str | None = None


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

    @field_validator("erro", mode="before")
    @classmethod
    def _erro_sem_segredos(cls, v):
        from app.limpeza import mascarar
        return mascarar(v, 400)

    @field_validator("parametros", mode="before")
    @classmethod
    def _parametros_sem_segredos(cls, v):
        from app.limpeza import mascarar
        if not isinstance(v, dict):
            return v
        return {k: (mascarar(x, 200) if isinstance(x, str) else x) for k, x in v.items()}


class Pagina(BaseModel):
    total: int
    itens: list
