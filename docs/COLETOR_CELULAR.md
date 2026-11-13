# Coletor no celular (Android, Termux)

Tudo fica neste repositório. Não precisa de um segundo repositório.

- **Código:** pasta `coletor/` (ramo principal).
- **Dados captados:** ramo `dados-coletor` (só dados, sem histórico de código).

## Instalação no celular (uma vez)
1. Instale Termux e Termux:Boot pelo F-Droid ou GitHub (não pela Play Store).
2. No Termux:
   ```bash
   git clone --depth 1 --branch <ramo-principal> https://github.com/felponesx/politica coletor-src
   git clone --branch dados-coletor https://github.com/felponesx/politica coletor-dados
   cp -r coletor-src/coletor/* coletor-dados/   # só para o Termux; os dados ficam no ramo dados-coletor
   ```
   Na prática, rode o coletor de dentro de `coletor-src/coletor` e aponte `destinos.toml` para `../coletor-dados`.
3. `bash instalar-termux.sh 5` (verificação a cada 5 minutos, sem aprovação).
4. Acesso de escrita ao ramo `dados-coletor`: uma *deploy key* com permissão de escrita, criada no repositório `politica`.
   Atenção: essa chave pode escrever em qualquer ramo. Quando possível, prefira um token de acesso restrito.

## No PC (quando for ligar o BRASIL+)
`COLETOR_DADOS=<pasta do clone do ramo dados-coletor>` no `.env.local`, e `COLETOR_PULL` como já está em `docs/PC_LOCAL.md`.
