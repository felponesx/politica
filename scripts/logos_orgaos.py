"""Logos dos órgãos e ofertantes de Concursos e cursos (grupo `orgaos` da mídia do site).

Cada nome que aparece nas telas (órgão do concurso, ofertante do curso, "Onde mais procurar") tem um verbete curado
na Wikipédia. A logo vem do campo de logo ou brasão da infobox do verbete (ex.: `| logo =`, `| brasão =`), nunca da
foto principal (que costuma ser fachada ou retrato). Sem campo de logo, o nome fica sem logo própria; o site então
usa o brasão do estado (órgãos estaduais) ou a inicial do nome.

Uso: python -m scripts.logos_orgaos [site/midia]    (grava logos_orgaos.json e aponta o grupo `orgaos` no logos.json)
A chave é o nome normalizado (`chave_orgao`, igual ao do site: sem acento, minúsculas, pontuação viram espaço).
"""
from __future__ import annotations

import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

from scripts.midia_site import WIKI, cli, miniatura

log = logging.getLogger("brasilplus.logos_orgaos")

# nome como aparece nos dados (concursos: órgão; cursos: ofertante; "Onde mais procurar": nome) -> verbete da Wikipédia
VERBETES = {
    # universidades e institutos
    "Universidade Estadual Paulista": "Universidade Estadual Paulista",
    "Universidade Estadual de Campinas": "Universidade Estadual de Campinas",
    "Universidade de São Paulo": "Universidade de São Paulo",
    "Universidade Estadual De Goiás": "Universidade Estadual de Goiás",
    "Universidade Federal Fluminense": "Universidade Federal Fluminense",
    "Universidade Federal de Alfenas": "Universidade Federal de Alfenas",
    "Universidade Federal de Itajubá": "Universidade Federal de Itajubá",
    "Universidade Federal de Jataí": "Universidade Federal de Jataí",
    "Universidade Federal de Santa Maria": "Universidade Federal de Santa Maria",
    "Universidade Federal de Uberlândia": "Universidade Federal de Uberlândia",
    "Universidade Federal do Estado do Rio de Janeiro": "Universidade Federal do Estado do Rio de Janeiro",
    "Universidade Federal do Rio Grande do Sul": "Universidade Federal do Rio Grande do Sul",
    "Fundação Universidade Federal de Ciências da Saúde de Porto Alegre": "Universidade Federal de Ciências da Saúde de Porto Alegre",
    "Fundação Universidade Federal de Pelotas": "Universidade Federal de Pelotas",
    "Fundação Universidade Federal de Viçosa": "Universidade Federal de Viçosa",
    "Hospital de Clínicas de Porto Alegre": "Hospital de Clínicas de Porto Alegre",
    "Centro Federal de Educação Tecnológica de Minas Gerais": "Centro Federal de Educação Tecnológica de Minas Gerais",
    "Instituto Federal de Educação, Ciência e Tecnologia Fluminense": "Instituto Federal Fluminense",
    "Instituto Federal de Educação, Ciência e Tecnologia Sul-Rio-Grandense": "Instituto Federal Sul-rio-grandense",
    "Instituto Federal de Educação, Ciência e Tecnologia de Goiás": "Instituto Federal de Goiás",
    "Instituto Federal de Educação, Ciência e Tecnologia de São Paulo": "Instituto Federal de São Paulo",
    "Instituto Federal de Educação, Ciência e Tecnologia do Ceará": "Instituto Federal do Ceará",
    "Instituto Federal de Educação, Ciência e Tecnologia do Espírito Santo": "Instituto Federal do Espírito Santo",
    "Instituto Federal de Educação, Ciência e Tecnologia do Rio Grande do Norte": "Instituto Federal do Rio Grande do Norte",
    "Instituto Federal de Educação, Ciência e Tecnologia do Rio Grande do Sul": "Instituto Federal do Rio Grande do Sul",
    "IMED - INSTITUTO DE MEDICINA ESTUDOS E DESENVOLVIMENTO": "Instituto de Medicina, Estudos e Desenvolvimento",
    # União, conselhos e órgãos nacionais (logo do próprio órgão ou da pasta)
    "Ministério de Minas e Energia": "Ministério de Minas e Energia",
    "Secretaria Nacional de Promoção e Defesa dos Direitos Humanos": "Ministério dos Direitos Humanos e da Cidadania",
    "Ouvidoria Nacional de Direitos Humanos": "Ministério dos Direitos Humanos e da Cidadania",
    "Secretaria de Gestão e Governo Digital": "Ministério da Gestão e da Inovação em Serviços Públicos",
    "Tribunal Regional do Trabalho da 4ª Região": "Tribunal Regional do Trabalho da 4ª Região",
    "Tribunal Regional do Trabalho da 9ª Região": "Tribunal Regional do Trabalho da 9ª Região",
    "Agência Brasileira de Desenvolvimento Indústrial": "Agência Brasileira de Desenvolvimento Industrial",
    "CONSELHO REGIONAL DE EDUCAÇÃO FÍSICA 16ª REGIÃO": "Conselho Federal de Educação Física",
    "CONSELHO REGIONAL DE ODONTOLOGIA DO CEARÁ": "Conselho Federal de Odontologia",
    "Conselho Regional de Psicologia da 5ª Região": "Conselho Federal de Psicologia",
    "Conselho de Arquitetura e Urbanismo de Santa Catarina": "Conselho de Arquitetura e Urbanismo do Brasil",
    "Conselho Regional de Corretores de Imóveis da 13ª Região": "Conselho Federal de Corretores de Imóveis",
    # órgãos estaduais com marca própria
    "Companhia de Processamento de Dados do Estado de São Paulo - PRODESP": "Prodesp",
    "Agência Paulista de Promoção de Investimentos e Competitividade - Investe São Paulo": "Investe São Paulo",
    # cursos e ofertantes
    "Escola Virtual.Gov (Enap)": "Escola Nacional de Administração Pública",
    "Sebrae": "Sebrae",
    "Senai — cursos gratuitos": "Serviço Nacional de Aprendizagem Industrial",
    "Senac — Programa Senac de Gratuidade (PSG)": "Serviço Nacional de Aprendizagem Comercial",
    "Sesi": "Serviço Social da Indústria",
    "CRAS da sua cidade": "Ministério do Desenvolvimento e Assistência Social, Família e Combate à Fome",
    "Pronatec / Novos Caminhos (MEC)": "Ministério da Educação",
    # prefeituras e cidades: brasão do município
    "Cravinhos": "Cravinhos",
    "Cruzeiro": "Cruzeiro (São Paulo)",
    "Divinolândia": "Divinolândia",
    "Guararema": "Guararema",
    "Jandira": "Jandira",
    "Juquitiba": "Juquitiba",
    "Lorena": "Lorena (São Paulo)",
    "Peruíbe": "Peruíbe",
    "Santana de Parnaíba": "Santana de Parnaíba",
    "Santo André": "Santo André",
    "Prefeitura Municipal De Aloândia": "Aloândia",
    "Prefeitura Municipal De Amorinópolis": "Amorinópolis",
    "Prefeitura Municipal De Ceres": "Ceres (Goiás)",
    "Prefeitura Municipal De Itiquira": "Itiquira",
    "Prefeitura Municipal De Planaltina": "Planaltina (Goiás)",
    "Prefeitura Municipal De Rio Verde": "Rio Verde (Goiás)",
    "Prefeitura Municipal De Santa Tereza De Goias": "Santa Teresa de Goiás",
    "Prefeitura Municipal De São Francisco De Goiás": "São Francisco de Goiás",
}

# campos da infobox que trazem a logo ou o brasão, na ordem de preferência
_CAMPO = re.compile(r"\|\s*(logo|logotipo|logomarca|brasão|brasao|emblema|imagem_brasao|brasao_imagem)\s*=\s*([^\n|}]+)", re.I)


def chave_orgao(s: str) -> str:
    """Nome normalizado para casar com o site (sem acento, minúsculas, pontuação vira espaço)."""
    t = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _arquivo_da_infobox(titulo: str) -> tuple[str, str] | None:
    """(nome do arquivo, página) do campo de logo/brasão da infobox do verbete, ou None."""
    try:
        d = cli.get(WIKI, params={"action": "parse", "page": titulo, "prop": "wikitext", "section": 0,
                                  "redirects": 1, "format": "json", "formatversion": 2}).json()
    except Exception as e:  # noqa: BLE001
        log.warning("verbete %s: %s", titulo, e)
        return None
    txt = (d.get("parse") or {}).get("wikitext") or ""
    pagina = (d.get("parse") or {}).get("title") or titulo
    for m in _CAMPO.finditer(txt):
        nome = re.sub(r"\[\[(?:Arquivo|File|Imagem|Ficheiro):", "", m.group(2)).split("|")[0].split("]]")[0].strip()
        nome = re.sub(r"^(?:Arquivo|File|Imagem|Ficheiro):", "", nome).strip()
        if nome:
            return nome, "https://pt.wikipedia.org/wiki/" + pagina.replace(" ", "_")
    return None


def _baixa_logo(nome_arquivo: str) -> str | None:
    try:
        d = cli.get(WIKI, params={"action": "query", "format": "json", "titles": "File:" + nome_arquivo,
                                  "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 240}).json()
        pg = next(iter(d.get("query", {}).get("pages", {}).values()), {})
        thumb = ((pg.get("imageinfo") or [{}])[0]).get("thumburl")
        if not thumb:
            return None
        r = cli.get(thumb)
        return miniatura(r.content, 64, "PNG") if r.status_code == 200 else None
    except Exception as e:  # noqa: BLE001
        log.warning("arquivo %s: %s", nome_arquivo, e)
        return None


def logos(antes: dict | None = None) -> dict:
    """{chave_orgao: {img, pagina, titulo, arquivo}}. Nome já com logo na cópia anterior não é procurado de novo."""
    antes = antes or {}
    out = {}
    for nome, verbete in VERBETES.items():
        k = chave_orgao(nome)
        if k in antes and antes[k].get("img"):
            out[k] = antes[k]
            continue
        achado = _arquivo_da_infobox(verbete)
        if not achado:
            log.info("sem logo no verbete: %s -> %s", nome, verbete)
            continue
        img = _baixa_logo(achado[0])
        if img:
            out[k] = {"img": img, "pagina": achado[1], "titulo": verbete, "arquivo": achado[0]}
        else:
            log.info("logo não baixou: %s -> %s", nome, achado[0])
    log.info("órgãos com logo: %d de %d", len(out), len(VERBETES))
    return out


def gravar(midia: str = "site/midia") -> dict:
    pasta = Path(midia)
    antes = {}
    arq = pasta / "logos_orgaos.json"
    if arq.exists():
        try:
            antes = json.loads(arq.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            antes = {}
    dados = logos(antes)
    arq.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    idx = pasta / "logos.json"
    if idx.exists():
        ind = json.loads(idx.read_text(encoding="utf-8"))
        ind.setdefault("grupos", {})["orgaos"] = "logos_orgaos.json"
        idx.write_text(json.dumps(ind, ensure_ascii=False, indent=1), encoding="utf-8")
    return dados


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    d = gravar(sys.argv[1] if len(sys.argv) > 1 else "site/midia")
    print(len(d), "logos gravadas")
