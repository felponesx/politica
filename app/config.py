from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./brasilplus.db"
    transparencia_api_key: str = ""
    mapbiomas_email: str = ""           # MAPBIOMAS_EMAIL / MAPBIOMAS_SENHA: conta da plataforma MapBiomas Alerta (login da API); só no servidor, nunca no site nem no repositório
    mapbiomas_senha: str = ""
    tomtom_api_key: str = ""            # TOMTOM_API_KEY: só no servidor, nunca no site
    tomtom_limite_dia: int = 2000       # franquia gratuita do TomTom: 2.500 chamadas por dia
    admin_token: str = "troque-este-token"
    # CSV "Arrecadação por Estado" da Receita Federal (dataset "Resultado da Arrecadação" no dados.gov.br).
    # Se o link mudar, troque aqui ou baixe o arquivo e use arquivo_local=...
    receita_arrecadacao_url: str = "https://www.gov.br/receitafederal/dados/arrecadacao-estado.csv"
    # CAPAG dos municípios (CKAN do Tesouro Transparente)
    capag_ckan_url: str = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=capag-municipios"
    # Cadastro CNPJ (dados abertos da Receita servidos pela BrasilAPI)
    cnpj_api_url: str = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    cnpj_api_reserva: str = "https://minhareceita.org/{cnpj}"  # mesmo formato da BrasilAPI, usado se ela falhar
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
    pasta_arquivos_coleta: str = "./dados_locais"  # único lugar de onde POST /coletas aceita arquivo_local/pasta_local
    bloquear_rede_interna: bool = True   # coletores não acessam localhost, rede privada nem metadados de nuvem (SSRF)
    cache_segundos: int = 600            # respostas pesadas (contadores, obras, economia) ficam em memória por este tempo; 0 desliga
    limite_req_por_minuto: int = 120     # por IP; 0 desliga
    corpo_max_bytes: int = 262144        # maior corpo aceito em POST/PUT (256 KB); 0 desliga
    consulta_timeout_ms: int = 30000     # Postgres + somente_leitura: tempo máximo de cada consulta (0 desliga)
    # Limites compartilhados entre os processos (tabela uso_limites no mesmo banco; sem Redis)
    proxies_confiaveis: str = ""         # CSV de redes (CIDR) dos proxies que podem informar o IP real em X-Forwarded-For; vazio = ignora o cabeçalho
    limite_pesado_por_minuto: int = 20   # por IP, rotas pesadas (busca, exportação, relatórios); 0 desliga
    limite_ia_ip_minuto: int = 4         # por IP, chamadas pagas à IA (/ia/web e /busca/web)
    limite_ia_ip_dia: int = 40
    limite_ia_global_minuto: int = 30    # todas as chamadas pagas juntas
    ia_orcamento_dia_usd: float = 5.0    # teto de gasto estimado por dia (0 = sem teto)
    ia_custo_chamada_usd: float = 0.02   # custo estimado de uma pergunta (/ia/web); a busca usa ia_custo_busca_usd
    ia_custo_busca_usd: float = 0.005
    ia_concorrencia: int = 4             # chamadas pagas ao mesmo tempo por processo
    ia_max_saida_tokens: int = 1200      # teto de tokens da resposta (Agent API)
    ia_cache_segundos: int = 3600
    ia_log_dias: int = 90
    alerta_telegram_token: str = ""
    alerta_telegram_chat: str = ""
    alerta_webhook_url: str = ""         # alternativa: POST JSON {"texto": ...} para qualquer webhook
    # IA do site: pesquisa na internet pelo Perplexity (POST /ia/web). Sem chave, a rota responde 503.
    perplexity_api_key: str = ""
    perplexity_preset: str = "low"
    perplexity_limite_dia: int = 300     # perguntas por dia (0 = sem limite)
    perplexity_busca_limite_dia: int = 1000  # buscas por dia na Search API, POST /busca/web (0 = sem limite)
    http_timeout: float = 60.0
    http_retries: int = 4


settings = Settings()
