"""Modelos do BRASIL+.

Dados legislativos (Câmara e Senado) têm tabelas próprias.
As demais fontes entram primeiro em `registros` (staging com JSON bruto + campos-chave),
para depois serem normalizadas em tabelas específicas conforme as telas exigirem.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


class Parlamentar(Base):
    __tablename__ = "parlamentares"
    __table_args__ = (UniqueConstraint("casa", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    casa: Mapped[str] = mapped_column(String(10), index=True)  # camara | senado
    id_externo: Mapped[str] = mapped_column(String(40))
    nome: Mapped[str] = mapped_column(String(200), index=True)
    partido: Mapped[str | None] = mapped_column(String(30), index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    foto_url: Mapped[str | None] = mapped_column(String(500))
    email: Mapped[str | None] = mapped_column(String(200))
    em_exercicio: Mapped[bool] = mapped_column(default=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Proposicao(Base):
    __tablename__ = "proposicoes"
    __table_args__ = (UniqueConstraint("casa", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    casa: Mapped[str] = mapped_column(String(10), index=True)
    id_externo: Mapped[str] = mapped_column(String(40))
    sigla_tipo: Mapped[str | None] = mapped_column(String(20), index=True)
    numero: Mapped[str | None] = mapped_column(String(20))
    ano: Mapped[int | None] = mapped_column(Integer, index=True)
    ementa: Mapped[str | None] = mapped_column(Text)
    data_apresentacao: Mapped[date | None] = mapped_column(Date)
    situacao: Mapped[str | None] = mapped_column(String(300))
    urn_final: Mapped[str | None] = mapped_column(String(300), index=True)  # URN LexML da norma gerada


class Norma(Base):
    """Legislação federal (leis, LCs, emendas constitucionais, MPs, decretos...)."""
    __tablename__ = "normas"
    __table_args__ = (UniqueConstraint("fonte", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fonte: Mapped[str] = mapped_column(String(20), default="senado")
    id_externo: Mapped[str] = mapped_column(String(60))
    tipo: Mapped[str] = mapped_column(String(20), index=True)       # LEI, LCP, EMC, MPV, DEC...
    numero: Mapped[str | None] = mapped_column(String(20), index=True)
    ano: Mapped[int | None] = mapped_column(Integer, index=True)
    data: Mapped[date | None] = mapped_column(Date, index=True)
    ementa: Mapped[str | None] = mapped_column(Text)
    url_texto: Mapped[str | None] = mapped_column(String(500))
    urn: Mapped[str | None] = mapped_column(String(300), index=True)
    proposicao_id: Mapped[int | None] = mapped_column(ForeignKey("proposicoes.id"), index=True)
    dados: Mapped[dict] = mapped_column(JsonType, default=dict)
    esfera: Mapped[str] = mapped_column(String(10), default="federal", server_default="federal", index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)  # normas estaduais
    proposicao: Mapped["Proposicao | None"] = relationship()


class Votacao(Base):
    __tablename__ = "votacoes"
    __table_args__ = (UniqueConstraint("casa", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    casa: Mapped[str] = mapped_column(String(10), index=True)
    id_externo: Mapped[str] = mapped_column(String(60))
    data: Mapped[date | None] = mapped_column(Date, index=True)
    orgao: Mapped[str | None] = mapped_column(String(40))
    descricao: Mapped[str | None] = mapped_column(Text)
    materia: Mapped[str | None] = mapped_column(String(200))
    resultado: Mapped[str | None] = mapped_column(String(200))
    ementa: Mapped[str | None] = mapped_column(Text)
    secreta: Mapped[bool] = mapped_column(default=False)
    proposicao_id: Mapped[int | None] = mapped_column(ForeignKey("proposicoes.id"), index=True)
    placar_oficial: Mapped[dict | None] = mapped_column(JsonType, nullable=True)  # totais informados pela casa
    votos: Mapped[list["Voto"]] = relationship(back_populates="votacao", cascade="all, delete-orphan")


class Voto(Base):
    __tablename__ = "votos"
    __table_args__ = (UniqueConstraint("votacao_id", "parlamentar_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    votacao_id: Mapped[int] = mapped_column(ForeignKey("votacoes.id", ondelete="CASCADE"), index=True)
    parlamentar_id: Mapped[int] = mapped_column(ForeignKey("parlamentares.id"), index=True)
    voto: Mapped[str] = mapped_column(String(40))  # Sim, Não, Abstenção, Obstrução...
    partido_na_data: Mapped[str | None] = mapped_column(String(30))
    votacao: Mapped[Votacao] = relationship(back_populates="votos")
    parlamentar: Mapped[Parlamentar] = relationship()


class Despesa(Base):
    """Cota parlamentar (CEAP) da Câmara."""
    __tablename__ = "despesas_parlamentares"
    __table_args__ = (UniqueConstraint("parlamentar_id", "id_externo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    parlamentar_id: Mapped[int] = mapped_column(ForeignKey("parlamentares.id"), index=True)
    id_externo: Mapped[str] = mapped_column(String(80))
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int | None] = mapped_column(Integer)
    tipo: Mapped[str | None] = mapped_column(String(200), index=True)
    fornecedor: Mapped[str | None] = mapped_column(String(300))
    cnpj_cpf: Mapped[str | None] = mapped_column(String(20), index=True)
    valor: Mapped[float] = mapped_column(Float, default=0)
    url_documento: Mapped[str | None] = mapped_column(String(500))


class Registro(Base):
    """Staging genérico das demais fontes (IBGE, SICONFI, PNCP, Transparência, ObrasGov, TSE...)."""
    __tablename__ = "registros"
    __table_args__ = (UniqueConstraint("fonte", "tipo", "chave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fonte: Mapped[str] = mapped_column(String(30), index=True)
    tipo: Mapped[str] = mapped_column(String(60), index=True)
    chave: Mapped[str] = mapped_column(String(200))
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    ano: Mapped[int | None] = mapped_column(Integer, index=True)
    titulo: Mapped[str | None] = mapped_column(Text)
    valor: Mapped[float | None] = mapped_column(Float)
    dados: Mapped[dict] = mapped_column(JsonType, default=dict)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Coleta(Base):
    """Log de cada execução de coletor."""
    __tablename__ = "coletas"

    id: Mapped[int] = mapped_column(primary_key=True)
    fonte: Mapped[str] = mapped_column(String(30))
    tarefa: Mapped[str] = mapped_column(String(60))
    parametros: Mapped[dict] = mapped_column(JsonType, default=dict)
    inicio: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    fim: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="rodando")
    itens: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str | None] = mapped_column(Text)


class ResultadoEleicao(Base):
    """Votação total de cada candidato por turno (agregada de município/zona)."""
    __tablename__ = "resultados_eleicao"
    __table_args__ = (UniqueConstraint("ano", "turno", "sq_candidato"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    turno: Mapped[int] = mapped_column(Integer, default=1)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    unidade: Mapped[str | None] = mapped_column(String(120), index=True)  # município (eleição municipal) ou UF
    cargo: Mapped[str] = mapped_column(String(60), index=True)
    sq_candidato: Mapped[str] = mapped_column(String(20))
    numero: Mapped[str | None] = mapped_column(String(10))
    nome: Mapped[str] = mapped_column(String(200), index=True)
    partido: Mapped[str | None] = mapped_column(String(30), index=True)
    votos: Mapped[int] = mapped_column(Integer, default=0)
    situacao: Mapped[str | None] = mapped_column(String(60))
    eleito: Mapped[bool] = mapped_column(default=False, index=True)


class VotoMunicipio(Base):
    """Votos de candidatos majoritários por município (para mapas)."""
    __tablename__ = "votos_municipio"
    __table_args__ = (UniqueConstraint("ano", "turno", "sq_candidato", "cd_municipio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    turno: Mapped[int] = mapped_column(Integer, default=1)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    cd_municipio: Mapped[str] = mapped_column(String(10), index=True)  # código TSE do município
    municipio: Mapped[str | None] = mapped_column(String(120))
    cargo: Mapped[str] = mapped_column(String(60), index=True)
    sq_candidato: Mapped[str] = mapped_column(String(20), index=True)
    votos: Mapped[int] = mapped_column(Integer, default=0)


# ============ Tabelas normalizadas (geradas a partir de `registros` por app/normalizar.py) ============

class Contrato(Base):
    __tablename__ = "contratos"

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_id: Mapped[int] = mapped_column(ForeignKey("registros.id", ondelete="CASCADE"), unique=True)
    fonte: Mapped[str] = mapped_column(String(20), index=True)  # pncp | transparencia
    numero_controle: Mapped[str] = mapped_column(String(120), index=True)
    esfera: Mapped[str | None] = mapped_column(String(1), index=True)  # F, E, M
    orgao: Mapped[str | None] = mapped_column(String(300))
    cnpj_orgao: Mapped[str | None] = mapped_column(String(20), index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    municipio: Mapped[str | None] = mapped_column(String(120), index=True)
    fornecedor: Mapped[str | None] = mapped_column(String(300))
    cnpj_fornecedor: Mapped[str | None] = mapped_column(String(20), index=True)
    objeto: Mapped[str | None] = mapped_column(Text)
    valor: Mapped[float | None] = mapped_column(Float, index=True)
    data_assinatura: Mapped[date | None] = mapped_column(Date, index=True)
    vigencia_fim: Mapped[date | None] = mapped_column(Date)
    ano: Mapped[int | None] = mapped_column(Integer, index=True)
    normalizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Obra(Base):
    __tablename__ = "obras"

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_id: Mapped[int] = mapped_column(ForeignKey("registros.id", ondelete="CASCADE"), unique=True)
    id_unico: Mapped[str] = mapped_column(String(40), index=True)
    nome: Mapped[str | None] = mapped_column(String(500))
    descricao: Mapped[str | None] = mapped_column(Text)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    situacao: Mapped[str | None] = mapped_column(String(60), index=True)
    natureza: Mapped[str | None] = mapped_column(String(60))
    especie: Mapped[str | None] = mapped_column(String(60))
    tipo: Mapped[str | None] = mapped_column(String(120), index=True)
    executor: Mapped[str | None] = mapped_column(String(300))
    valor_previsto: Mapped[float | None] = mapped_column(Float)
    valor_federal: Mapped[float | None] = mapped_column(Float)
    inicio_previsto: Mapped[date | None] = mapped_column(Date)
    fim_previsto: Mapped[date | None] = mapped_column(Date)
    normalizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Candidato(Base):
    __tablename__ = "candidatos"

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_id: Mapped[int] = mapped_column(ForeignKey("registros.id", ondelete="CASCADE"), unique=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    sq_candidato: Mapped[str] = mapped_column(String(20), index=True)
    numero: Mapped[str | None] = mapped_column(String(10))
    nome: Mapped[str | None] = mapped_column(String(200), index=True)
    nome_urna: Mapped[str | None] = mapped_column(String(200), index=True)
    partido: Mapped[str | None] = mapped_column(String(30), index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    unidade: Mapped[str | None] = mapped_column(String(120))
    cargo: Mapped[str | None] = mapped_column(String(60), index=True)
    situacao_candidatura: Mapped[str | None] = mapped_column(String(60))
    resultado: Mapped[str | None] = mapped_column(String(60))
    ocupacao: Mapped[str | None] = mapped_column(String(120))
    instrucao: Mapped[str | None] = mapped_column(String(60))
    genero: Mapped[str | None] = mapped_column(String(20))
    parlamentar_id: Mapped[int | None] = mapped_column(ForeignKey("parlamentares.id"), index=True)
    normalizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Indicador(Base):
    __tablename__ = "indicadores"
    __table_args__ = (UniqueConstraint("nome", "uf", "periodo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_id: Mapped[int] = mapped_column(ForeignKey("registros.id", ondelete="CASCADE"), unique=True)
    nome: Mapped[str] = mapped_column(String(60), index=True)
    descricao: Mapped[str | None] = mapped_column(String(200))
    uf: Mapped[str] = mapped_column(String(2), index=True)
    periodo: Mapped[str] = mapped_column(String(10))
    ano: Mapped[int] = mapped_column(Integer, index=True)
    valor: Mapped[float | None] = mapped_column(Float)
    unidade: Mapped[str | None] = mapped_column(String(40))
    normalizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FinancaEstadual(Base):
    """Linhas do RREO/RGF (SICONFI) e arrecadação/transferências (Receita/Tesouro) por UF."""
    __tablename__ = "financas_estaduais"

    id: Mapped[int] = mapped_column(primary_key=True)
    registro_id: Mapped[int] = mapped_column(ForeignKey("registros.id", ondelete="CASCADE"), unique=True)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes_ou_periodo: Mapped[int | None] = mapped_column(Integer)
    demonstrativo: Mapped[str] = mapped_column(String(40), index=True)  # rreo-anexo01, rgf-anexo02-divida, arrecadacao_uf...
    cod_conta: Mapped[str | None] = mapped_column(String(120), index=True)
    conta: Mapped[str | None] = mapped_column(String(300))
    coluna: Mapped[str | None] = mapped_column(String(200))
    valor: Mapped[float | None] = mapped_column(Float)
    normalizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------- fontes adicionadas na versão 0.2 ----------

class Municipio(Base):
    """Os 5.570 municípios (IBGE), com população, PIB e nota CAPAG do Tesouro."""
    __tablename__ = "municipios"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_ibge: Mapped[str] = mapped_column(String(7), unique=True)
    nome: Mapped[str] = mapped_column(String(120), index=True)
    uf: Mapped[str] = mapped_column(String(2), index=True)
    microrregiao: Mapped[str | None] = mapped_column(String(120))
    populacao: Mapped[int | None] = mapped_column(Integer)
    populacao_ano: Mapped[int | None] = mapped_column(Integer)
    pib: Mapped[float | None] = mapped_column(Float)  # R$ (já convertido de mil R$)
    pib_ano: Mapped[int | None] = mapped_column(Integer)
    capag: Mapped[str | None] = mapped_column(String(10), index=True)
    capag_ano: Mapped[int | None] = mapped_column(Integer)
    capag_detalhe: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IndicadorMunicipal(Base):
    """Indicadores sociais por município (IBGE/SIDRA ou arquivo importado: IDHM, DataSUS, INEP...)."""
    __tablename__ = "indicadores_municipais"
    __table_args__ = (UniqueConstraint("codigo_ibge", "nome", "ano"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_ibge: Mapped[str] = mapped_column(String(7), index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    nome: Mapped[str] = mapped_column(String(60), index=True)
    descricao: Mapped[str | None] = mapped_column(String(300))
    ano: Mapped[int] = mapped_column(Integer, index=True)
    valor: Mapped[float | None] = mapped_column(Float)
    unidade: Mapped[str | None] = mapped_column(String(60))
    fonte: Mapped[str | None] = mapped_column(String(120))


class DevedorPGFN(Base):
    """Empresas (CNPJ) inscritas na dívida ativa da União (PGFN), somadas por tipo de dívida.
    Pessoas físicas NÃO são gravadas individualmente — só entram nos totais por estado."""
    __tablename__ = "devedores_pgfn"
    __table_args__ = (UniqueConstraint("cnpj", "tipo_divida", "referencia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cnpj: Mapped[str] = mapped_column(String(14), index=True)
    nome: Mapped[str | None] = mapped_column(String(300), index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    tipo_divida: Mapped[str] = mapped_column(String(30))  # previdenciaria | nao_previdenciaria | fgts
    inscricoes: Mapped[int] = mapped_column(Integer, default=0)
    valor: Mapped[float] = mapped_column(Float, default=0, index=True)
    valor_ajuizado: Mapped[float] = mapped_column(Float, default=0)
    referencia: Mapped[str] = mapped_column(String(12), index=True)  # ex.: 2025T2


class EmpresaCadastro(Base):
    """Cadastro CNPJ (Receita Federal, via BrasilAPI) com o quadro societário."""
    __tablename__ = "empresas_cadastro"

    id: Mapped[int] = mapped_column(primary_key=True)
    cnpj: Mapped[str] = mapped_column(String(14), unique=True)
    razao_social: Mapped[str | None] = mapped_column(String(300), index=True)
    nome_fantasia: Mapped[str | None] = mapped_column(String(300))
    cnae: Mapped[str | None] = mapped_column(String(10), index=True)
    cnae_descricao: Mapped[str | None] = mapped_column(String(300))
    municipio: Mapped[str | None] = mapped_column(String(120))
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    situacao: Mapped[str | None] = mapped_column(String(60))
    abertura: Mapped[date | None] = mapped_column(Date)
    capital_social: Mapped[float | None] = mapped_column(Float)
    porte: Mapped[str | None] = mapped_column(String(60))
    natureza_juridica: Mapped[str | None] = mapped_column(String(200))
    socios: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class OcorrenciaDesastre(Base):
    """Desastres reconhecidos por município (Defesa Civil / S2ID ou Atlas Digital de Desastres)."""
    __tablename__ = "ocorrencias_desastre"

    id: Mapped[int] = mapped_column(primary_key=True)
    chave: Mapped[str] = mapped_column(String(40), unique=True)
    codigo_ibge: Mapped[str | None] = mapped_column(String(7), index=True)
    municipio: Mapped[str | None] = mapped_column(String(120))
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    data: Mapped[date | None] = mapped_column(Date, index=True)
    tipo: Mapped[str | None] = mapped_column(String(200), index=True)
    cobrade: Mapped[str | None] = mapped_column(String(20))
    situacao: Mapped[str | None] = mapped_column(String(120))
    fonte: Mapped[str | None] = mapped_column(String(60))


class CandidatoFinancas(Base):
    """Patrimônio declarado e dinheiro de campanha de cada candidatura (TSE)."""
    __tablename__ = "candidato_financas"
    __table_args__ = (UniqueConstraint("ano", "sq_candidato"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    sq_candidato: Mapped[str] = mapped_column(String(20), index=True)
    uf: Mapped[str | None] = mapped_column(String(2), index=True)
    patrimonio: Mapped[float | None] = mapped_column(Float)
    bens: Mapped[list | None] = mapped_column(JsonType, nullable=True)          # [{tipo, descricao, valor}] (até 30)
    bens_por_tipo: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    receitas: Mapped[float | None] = mapped_column(Float)
    receitas_por_fonte: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    despesas: Mapped[float | None] = mapped_column(Float)
    despesas_por_tipo: Mapped[dict | None] = mapped_column(JsonType, nullable=True)


class UsoLimite(Base):
    """Contadores compartilhados entre os processos (limite de requisições e da IA). Uma linha por (chave, janela de tempo)."""
    __tablename__ = "uso_limites"

    chave: Mapped[str] = mapped_column(String(160), primary_key=True)
    janela: Mapped[int] = mapped_column(Integer, primary_key=True)  # início da janela (época em segundos ÷ tamanho da janela)
    n: Mapped[int] = mapped_column(Integer, default=0)              # unidades gastas (chamadas ou micro-dólares)
    atualizado: Mapped[int] = mapped_column(Integer, index=True)    # época em segundos (para a limpeza)


class UsoIa(Base):
    """Uma linha por chamada paga à IA: sem pergunta nem resposta, só quem (hash do IP), quando, quanto e como terminou."""
    __tablename__ = "uso_ia"

    id: Mapped[int] = mapped_column(primary_key=True)
    quando: Mapped[int] = mapped_column(Integer, index=True)        # época em segundos
    rota: Mapped[str] = mapped_column(String(20))                   # ia_web | busca_web
    cliente: Mapped[str] = mapped_column(String(16))                # hash curto do IP (não é o IP)
    resultado: Mapped[str] = mapped_column(String(20))              # ok | erro | limite | bloqueado
    custo_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int | None] = mapped_column(Integer)


class CacheIa(Base):
    """Respostas da IA guardadas para todos os processos (a mesma pergunta não é cobrada duas vezes na janela)."""
    __tablename__ = "cache_ia"

    chave: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 da pergunta
    valor: Mapped[str] = mapped_column(Text)                          # JSON da resposta
    expira: Mapped[int] = mapped_column(Integer, index=True)
