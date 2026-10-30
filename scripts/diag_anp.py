"""ANP: colunas e uma amostra do zip semestral de preços de combustíveis (saída curta)."""
from scripts.diagnostico_ci import zip_remoto

zip_remoto("ANP ca-2026-01", "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-2026-01.zip", mostrar=("",), linhas=4)
print("fim", flush=True)
