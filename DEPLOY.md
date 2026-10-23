# Colocar o BRASIL+ no ar

Tudo roda com Docker num servidor Linux (VPS) com pelo menos **2 GB de RAM e 40 GB de disco**
(a dívida ativa da PGFN e os arquivos do TSE são grandes). Qualquer provedor de VPS serve; compare preço e
localização no Brasil antes de contratar.

## Passo a passo
1. **Domínio:** no painel do seu domínio, crie um registro `A` apontando `brasilmais.seudominio.com.br` para o IP da VPS.
2. **Servidor:** acesse a VPS e instale o Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. **Código:** envie a pasta `brasil-plus` para o servidor (Git ou `scp`) e entre nela.
4. **Configuração:**
   ```bash
   cp .env.prod.example .env.prod
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # rode 2x: DB_SENHA e DB_LEITURA_SENHA
   nano .env.prod                                                  # preencha DOMINIO, senhas e (opcional) chave e alertas
   ```
5. **Subir:**
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
   ```
   O Caddy emite o certificado HTTPS sozinho em 1–2 minutos. Abra `https://SEU_DOMINIO`.
6. **Primeira carga** (demora; pode fechar o terminal):
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod exec -d agendador python -m scripts.coletar inicial
   ```
   Depois, as cargas grandes que você quiser (veja o README): TSE por estado, PGFN, desastres.
7. **Firewall:** deixe abertas só as portas 22, 80 e 443 (`ufw allow 22,80,443/tcp && ufw enable`).

A partir daí o **agendador** atualiza tudo sozinho (diário, semanal, mensal e trimestral — veja `python -m scripts.agendar --listar`).

## Como está protegido
- A API usa o usuário `brasil_leitura`, que **só consegue ler** o banco. Gravação só pelo agendador.
- `POST /coletas` fica desligado na API pública (e o Caddy recusa qualquer POST).
- O banco não tem porta aberta para a internet.
- HTTPS obrigatório com HSTS; cabeçalhos de segurança e CSP no site.
- Limite de 120 requisições por minuto por IP (`LIMITE_REQ_POR_MINUTO`).
- Senhas, a chave do Portal da Transparência e a do Perplexity (`PERPLEXITY_API_KEY`, pesquisa na internet da IA do site; opcional) ficam só no `.env.prod` (fora do Git, fora da imagem Docker).
- Backup diário em `./backups` (guarda 7 dias). **Copie essa pasta para fora da VPS** de vez em quando.

## Checklist depois de subir
- [ ] `https://SEU_DOMINIO` abre o site com o selo **Dados oficiais**
- [ ] `https://SEU_DOMINIO/saude` responde `{"status":"ok"}`
- [ ] `https://SEU_DOMINIO/coletas` mostra as coletas com status `ok`
- [ ] `curl -X POST https://SEU_DOMINIO/coletas/camara-deputados` responde 405
- [ ] Existe um arquivo novo em `./backups` no dia seguinte
- [ ] Alerta de teste chegou (opcional): `docker compose ... exec agendador python -c "from app.alertas import enviar; enviar('teste')"`

## Comandos úteis
```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f agendador   # acompanhar coletas
docker compose -f docker-compose.prod.yml --env-file .env.prod exec agendador python -m scripts.agendar --agora diario
docker compose -f docker-compose.prod.yml --env-file .env.prod pull && \
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build            # atualizar
gunzip -c backups/brasilplus-AAAAMMDD.sql.gz | docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db psql -U brasil brasilplus   # restaurar
```

## Limites e custos da IA (auditoria de out/2026)
- Os limites ficam no banco (tabela `uso_limites`), então valem para todos os processos e sobrevivem a reinício. A migração `0007` precisa estar aplicada
  (`/pronto` responde 503 enquanto não estiver).
- `PROXIES_CONFIAVEIS`: redes onde está o Caddy (no compose já vem com as faixas privadas do Docker). Sem isso todos os visitantes dividem o IP do proxy.
- `IA_ORCAMENTO_DIA_USD`, `LIMITE_IA_*`: tetos da pesquisa na internet. Configure **também** o teto de gasto no painel da Perplexity.
- Acompanhe em *Relatórios e Dados* (uso da IA e situação das fontes) ou em `GET /ia/uso` e `GET /fontes/status`.
