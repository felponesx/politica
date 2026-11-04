"""Inventário das coletas do BRASIL+ e de como cada uma se liga ao sistema pelo celular.

  python -m scripts.inventario_vinculos        # grava docs/VINCULOS.md

Para cada tarefa: onde ela grava em `coletas` (a mesma regra da tela de situação das fontes) e em que
etapa do caminho do celular ela está. Não lê o banco: é só o registro do código.
"""
from pathlib import Path

from app.collectors import _TAREFAS_BRUTAS
from app.collectors.registro import registro_das_tarefas

# tarefas que já têm o caminho pelo celular pronto (adaptador próprio ou genérico, testado)
PRONTAS = {"bcb-series": "adaptador próprio (`bcb`), testado"}


def gerar() -> str:
    par = registro_das_tarefas()
    linhas = []
    for nome in sorted(_TAREFAS_BRUTAS):
        p = par.get(nome)
        onde = f"{p[0]} / {p[1]}" if p else "—"
        if nome in PRONTAS:
            etapa = PRONTAS[nome]
        elif p:
            etapa = "pendente: falta o vínculo pelo celular"
        else:
            etapa = "sem registro em `coletas` (não aparece na situação das fontes)"
        linhas.append(f"| `{nome}` | {onde} | {etapa} |")
    cab = ("# Vínculos do BRASIL+ pelo celular\n\n"
           "Gerado por `python -m scripts.inventario_vinculos`. Uma linha por tarefa de coleta do BRASIL+.\n\n"
           "## Como uma fonte se liga\n"
           "1. No vínculo do celular (`vinculos/<produto>.toml`), a fonte declara `adaptador` e `mapa`, ou usa adaptador próprio.\n"
           "2. O coletor do celular baixa, confere, corrige só o formato e publica `dados/<fonte>/atual` + `meta.json` (com o `mapa`).\n"
           "3. O BRASIL+ lê o `meta.json` (`coletor-ingestao`), confere o hash e grava em `registros` pelo mapa.\n"
           "4. Sem adaptador declarado e sem adaptador próprio, a fonte é ignorada. Adaptador declarado e inexistente é erro.\n\n"
           "Mapa genérico (`adaptador = \"linhas\"`): `tipo`, `chave` (obrigatório), `valor`, `titulo`, `uf`, `data`, e `dados` "
           "(campos extras), com caminhos pontilhados como `orgao.nome`.\n\n"
           "## Tarefas\n\n| Tarefa | Grava em `coletas` | Caminho pelo celular |\n|---|---|---|\n")
    return cab + "\n".join(linhas) + "\n"


def main():
    destino = Path("docs/VINCULOS.md")
    destino.write_text(gerar(), encoding="utf-8")
    print(f"gravado: {destino} ({len(_TAREFAS_BRUTAS)} tarefas)")


if __name__ == "__main__":
    main()
