from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./brasilplus.db"
    transparencia_api_key: str = ""
    admin_token: str = "troque-este-token"
    # CSV "Arrecadação por Estado" da Receita Federal (dataset "Resultado da Arrecadação" no dados.gov.br).
    # Se o link mudar, troque aqui ou baixe o arquivo e use arquivo_local=...
    receita_arrecadacao_url: str = "https://www.gov.br/receitafederal/dados/arrecadacao-estado.csv"
    # CAPAG dos municípios (CKAN do Tesouro Transparente)
    capag_ckan_url: str = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=capag-municipios"
    # Cadastro CNPJ (dados abertos da Receita servidos pela BrasilAPI)
    cnpj_api_url: str = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    cnpj_intervalo: float = 1.0          # segundos entre consultas na coleta em lote
    cnpj_sob_demanda: bool = True        # GET /empresas/{cnpj} consulta a fonte se o CNPJ estiver nas bases
    # Leis estaduais (LexML, SRU). Expressões CQL tentadas em ordem; ajuste se a primeira coleta vier vazia.
    lexml_sru_url: str = "https://www.lexml.gov.br/busca/SRU"
    lexml_cql_estadual: list[str] = [
        'urn any "br;{localidade}:estadual" and date any "{ano}"',
        'localidade="{localidade}" and date="{ano}"',
        'urn="urn:lex:br;{localidade}:estadual:*:{ano}*"',
    ]
    # Cota dos senadores (CEAPS): API de dados abertos administrativos e, se falhar, o CSV antigo
    senado_ceaps_url: str = "https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ano}"
    senado_ceaps_csv: str = "https://www.senado.leg.br/transparencia/LAI/verba/despesa_ceaps_{ano}.csv"
    # Assembleias Legislativas
    almg_url: str = "https://dadosabertos.almg.gov.br/ws"
    alesp_deputados_url: str = "https://www.al.sp.gov.br/repositorioDados/deputados/deputados.xml"
    alesp_votacoes_url: str = "https://www.al.sp.gov.br/repositorioDados/processo_legislativo/comissoes_permanentes_votacoes.xml"
    # Produção
    migrar_ao_iniciar: bool = True       # a API aplica as migrações ao subir (desligue se o usuário do banco for só leitura)
    somente_leitura: bool = False        # desliga POST /coletas na API (as coletas rodam no agendador)
    limite_req_por_minuto: int = 120     # por IP; 0 desliga
    alerta_telegram_token: str = ""
    alerta_telegram_chat: str = ""
    alerta_webhook_url: str = ""         # alternativa: POST JSON {"texto": ...} para qualquer webhook
    http_timeout: float = 60.0
    http_retries: int = 4


settings = Settings()
