"""Gera uma cópia estática da API em JSON, para o site funcionar sem servidor.

Uso:  python -m scripts.exportar_snapshot site/dados

O site (site/index.html), quando não encontra um servidor BRASIL+, procura `dados/manifest.json` ao lado da
página e passa a responder às consultas com esta cópia (link publicado, GitHub Pages, qualquer hospedagem estática).

Como a cópia é organizada:
- cada resposta da API fica guardada pela "chave" da consulta: caminho + parâmetros em ordem alfabética
  (ex.: `/eleicoes/2022/SP?cargo=GOVERNADOR&turno=1`);
- as listas (parlamentares, contratos, projetos...) são guardadas completas, até um teto, e o site aplica os
  filtros e a paginação no navegador (`bases` no manifest diz quais listas existem e com quais parâmetros fixos);
- as chaves são distribuídas em `s<N>.json` pelo hash FNV-1a da chave (o site usa a mesma conta) e cada
  arquivo só é baixado quando uma tela precisa dele.
"""
import json
import logging
import os
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

os.environ["LIMITE_REQ_POR_MINUTO"] = "0"  # as consultas abaixo não passam pelo limite por IP
os.environ["CNPJ_SOB_DEMANDA"] = "false"  # a cópia usa só o que já está no banco

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.busca import ENTIDADES  # noqa: E402
from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Norma, Parlamentar, Proposicao, Votacao  # noqa: E402
from app.utils import UFS  # noqa: E402

log = logging.getLogger("snapshot")
SHARDS = 128
VERSAO = 1

# listas guardadas completas (até o teto): caminho -> (bases com parâmetros fixos, teto de itens)
LISTAS = {
    "/parlamentares": ([{}], 3000),
    "/votacoes": ([{}], 3000),
    "/proposicoes": ([{}], 4000),
    "/legislacao": ([{}], 6000),
    "/contratos": ([{"ordenar": "valor"}, {"ordenar": "data"}], 3000),
    "/obras": ([{}], 3000),
    "/candidatos": ([{"cargo": c, "eleitos": "true"} for c in
                     ("DEPUTADO ESTADUAL,DEPUTADO DISTRITAL", "GOVERNADOR", "PREFEITO", "PRESIDENTE")], 6000),
    "/municipios": ([{}], 6000),  # a ordem por população ou PIB é feita no navegador
    "/empresas": ([{}], 2000),
    "/dividas/devedores": ([{}], 1000),
    "/recuperacao-judicial": ([{"tipo": "recuperacao_judicial"}, {"tipo": "falencia"}], 8000),
    "/noticias": ([{}], 1500),
}
# respostas guardadas exatamente como o site pede
FIXAS = [
    "/saude", "/coletas?limit=30", "/legislacao-resumo", "/fluxo-federativo", "/eleicoes/anos", "/contadores",
    "/mapa/estados", "/agora/eventos", "/partidos/composicao", "/assembleias", "/gastos/entes", "/orgaos",
    "/dividas/estados", "/dividas/municipios", "/dividas/devedores?limit=20", "/indicadores-sociais/nomes", "/indicadores",
    "/empresas-setores", "/fornecedores-cruzados?limit=60", "/economia",
    "/economia?nomes=divida_bruta_pib,divida_liquida_pib,juros_nominais_pib,endividamento_familias,inadimplencia_pf,inadimplencia_pj",
    "/economia?nomes=ipca_12m,selic,desemprego,dolar,pib_12m",
    "/recuperacao-judicial/resumo", "/recuperacao-judicial/resumo?tipo=falencia",
    "/seguranca", "/dividas/familias-estados",
]
# quantos detalhes (popouts) guardar por tipo
TETO_DETALHE = {"votacoes": 1500, "proposicoes": 2500, "legislacao": 2500, "contratos": 1200, "obras": 1500,
                "fornecedores": 400, "municipios": 6000}
TETO_BUSCA = 6000  # itens por tipo no índice de busca
TETO_NOTAS = 50  # notas da cota por parlamentar


def chave(caminho: str, params: dict | None = None) -> str:
    """Mesma regra do site: parâmetros sem valor saem, os demais em ordem alfabética, sem codificação."""
    p = {k: str(v) for k, v in (params or {}).items() if v not in (None, "")}
    return caminho + ("?" + "&".join(f"{k}={p[k]}" for k in sorted(p)) if p else "")


def fnv1a(texto: str) -> int:
    h = 0x811C9DC5
    for c in texto:
        h = ((h ^ ord(c)) * 0x01000193) & 0xFFFFFFFF
    return h


def _json(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(type(o))


class Exportador:
    def __init__(self):
        self.cli = TestClient(app)
        self.dados: dict[str, object] = {}
        self.bases: dict[str, list[dict]] = defaultdict(list)
        self.totais: dict[str, dict] = {}
        self.consultas = 0

    def get(self, caminho, params=None, guardar=True):
        """Consulta a API; guarda a resposta (ou o erro, para o site mostrar a mesma mensagem)."""
        k = chave(caminho, params)
        if k in self.dados:
            return self.dados[k]
        self.consultas += 1
        r = self.cli.get(caminho, params={a: b for a, b in (params or {}).items() if b not in (None, "")})
        if r.status_code == 200:
            valor = r.json()
        else:
            try:
                detalhe = r.json().get("detail")
            except Exception:
                detalhe = None
            valor = {"__status": r.status_code, "detail": detalhe if isinstance(detalhe, str) else f"Erro {r.status_code}"}
        if guardar:
            self.dados[k] = valor
        return valor

    @staticmethod
    def ok(v):
        return isinstance(v, (dict, list)) and not (isinstance(v, dict) and "__status" in v)

    def lista(self, caminho, base, teto, passo=None):
        """Lista completa (até o teto), paginando com o maior `limit` que a rota aceita."""
        passo = passo or {"/parlamentares": 600, "/municipios": 1000, "/empresas": 200, "/dividas/devedores": 200,
                          "/recuperacao-judicial": 500}.get(caminho, 500)
        itens, total, extra, off = [], 0, {}, 0
        while off < teto:
            r = self.get(caminho, {**base, "limit": min(passo, teto - off), "offset": off}, guardar=False)
            if not self.ok(r):
                self.dados[chave(caminho, base)] = r
                self.bases[caminho].append(base)
                return []
            total = r.get("total", 0)
            extra = {a: b for a, b in r.items() if a not in ("itens", "total")}
            novos = r.get("itens", [])
            itens += novos
            off += len(novos)
            if not novos or off >= total:
                break
        self.dados[chave(caminho, base)] = {**extra, "total": len(itens), "itens": itens, "__completa": True}
        self.bases[caminho].append(base)
        self.totais[chave(caminho, base)] = {"na_copia": len(itens), "no_banco": total}
        return itens

    # ---------- plano de exportação ----------
    def exportar(self):
        for k in FIXAS:
            caminho, _, qs = k.partition("?")
            self.get(caminho, dict(p.split("=", 1) for p in qs.split("&")) if qs else None)

        listas = {c: [self.lista(c, b, teto) for b in bases] for c, (bases, teto) in LISTAS.items()}

        # parlamentares: perfil, ligações, atuação e todas as notas da cota
        for p in listas["/parlamentares"][0]:
            pid = p["id"]
            for sufixo in ("", "/ligacoes", "/atuacao"):
                self.get(f"/parlamentares/{pid}{sufixo}")
            if p["casa"] in ("camara", "senado"):
                # só as notas mais recentes (o resumo por tipo, no perfil, soma todas)
                self.lista(f"/parlamentares/{pid}/despesas", {}, TETO_NOTAS, passo=TETO_NOTAS)

        # popouts (detalhes), na ordem em que as listas aparecem no site
        def detalhes(caminho, itens, teto, campo="id"):
            for it in itens[:teto]:
                self.get(f"{caminho}/{it[campo]}")

        detalhes("/votacoes", listas["/votacoes"][0], TETO_DETALHE["votacoes"])
        detalhes("/proposicoes", listas["/proposicoes"][0], TETO_DETALHE["proposicoes"])
        detalhes("/legislacao", listas["/legislacao"][0], TETO_DETALHE["legislacao"])
        detalhes("/obras", listas["/obras"][0], TETO_DETALHE["obras"])
        contratos = _intercalar(*listas["/contratos"])
        detalhes("/contratos", contratos, TETO_DETALHE["contratos"])
        detalhes("/municipios", listas["/municipios"][0], TETO_DETALHE["municipios"], campo="codigo_ibge")

        # fornecedores e empresas: cruzados com a cota, maiores contratados e devedores
        docs = []
        cruz = self.dados.get(chave("/fornecedores-cruzados", {"limit": 60}))
        if self.ok(cruz):
            docs += [f["cnpj"] for f in cruz.get("itens", [])]
        docs += [c["cnpj_fornecedor"] for c in contratos if c.get("cnpj_fornecedor")]
        docs += [e["cnpj"] for e in listas["/empresas"][0]]
        docs += [d["cnpj"] for d in listas["/dividas/devedores"][0]]
        for doc in list(dict.fromkeys(docs))[:TETO_DETALHE["fornecedores"]]:
            self.get(f"/fornecedores/{doc}")
            self.get(f"/empresas/{doc}")

        # estados
        for uf in UFS:
            for c in (f"/estados/{uf}/resumo", f"/estados/{uf}/fluxo", f"/obras-resumo/{uf}", f"/malhas/{uf}"):
                self.get(c)
            self.get("/riscos", {"uf": uf})

        # órgãos federais
        for a in range(date.today().year - 3, date.today().year + 1):  # o site troca de ano na lista
            self.get("/orgaos", {"ano": a})
        orgaos = self.dados.get("/orgaos")
        if self.ok(orgaos):
            for o in orgaos.get("itens", []):
                self.get(f"/orgaos/{o['codigo']}")

        # indicadores sociais por município
        nomes = self.dados.get("/indicadores-sociais/nomes")
        if self.ok(nomes):
            for n in nomes:
                self.get("/indicadores-sociais", {"nome": n["nome"]})

        self._gastos()
        self._eleicoes()
        self._busca()

    def _gastos(self):
        """Despesa por função: as combinações que a tela Gastos públicos pede."""
        entes = self.dados.get("/gastos/entes")
        if not self.ok(entes):
            return
        for e in entes:
            esf, uf = e["esfera"], e.get("uf") or ""
            if esf == "M":
                continue
            base = {"esfera": esf, "uf": "" if esf == "U" else uf}
            self.get("/gastos/evolucao", base)
            for ano in e.get("anos", []):
                self.get("/gastos/funcao", {**base, "ano": ano})
        # prefeituras (esfera M): pelo código IBGE das cidades que têm dados
        with SessionLocal() as db:
            from app.models import Registro
            chaves = db.scalars(select(Registro.chave).where(Registro.tipo == "despesa_funcao",
                                                              Registro.chave.like("M-%"))).all()
        for cod in sorted({c.split("-")[1] for c in chaves}):
            ev = self.get("/gastos/evolucao", {"esfera": "M", "municipio": cod})
            for linha in ev if isinstance(ev, list) else []:
                self.get("/gastos/funcao", {"esfera": "M", "ano": linha["ano"], "municipio": cod})

    def _eleicoes(self):
        anos = self.dados.get("/eleicoes/anos")
        if not self.ok(anos):
            return
        for ano in anos:
            # mapa do país: resumo por estado de cada cargo (vereadores ficam de fora, como abaixo)
            cargos_ano = self.get(f"/eleicoes/{ano}/cargos")
            for cargo in cargos_ano if isinstance(cargos_ano, list) else []:
                if cargo != "VEREADOR":
                    for turno in (1, 2):
                        self.get(f"/eleicoes/{ano}/estados", {"cargo": cargo, "turno": turno})
            for uf in [*UFS, "BR"]:
                cargos = self.get(f"/eleicoes/{ano}/{uf}/cargos")
                if not self.ok(cargos) or not cargos:
                    continue
                # vereadores: dezenas de milhares de eleitos por estado; ficam fora da cópia (o servidor tem tudo)
                cargos = [c for c in cargos if c != "VEREADOR"]
                self.dados[chave(f"/eleicoes/{ano}/{uf}/cargos")] = cargos
                for cargo in cargos:
                    for turno in (1, 2):
                        r = self.get(f"/eleicoes/{ano}/{uf}", {"cargo": cargo, "turno": turno})
                        if turno == 1:  # a página do estado pede sem o turno
                            self.dados[chave(f"/eleicoes/{ano}/{uf}", {"cargo": cargo})] = r
                        self.get(f"/eleicoes/{ano}/{uf}/mapa", {"cargo": cargo, "turno": turno})

    def _busca(self):
        """Índice para a busca do site (o navegador faz a busca nesta lista)."""
        from sqlalchemy import text
        indice = {}
        with SessionLocal() as db:
            for tabela, (expr, _modo, titulo, sub) in ENTIDADES.items():
                linhas = db.execute(text(f"SELECT id, {titulo} AS titulo, {sub} AS subtitulo, {expr} AS texto "
                                         f"FROM {tabela} ORDER BY id DESC LIMIT :lim"), {"lim": TETO_BUSCA}).all()
                if linhas:  # textos encurtados: o índice é baixado inteiro na primeira busca
                    indice[tabela] = [[i, (t or "")[:140], (s or "")[:140], "" if (x or "") == (t or "") else (x or "")[:160]]
                                      for i, t, s, x in linhas]
        self.dados["/busca#indice"] = indice

    # ---------- gravação ----------
    def gravar(self, pasta: Path):
        if pasta.exists():
            shutil.rmtree(pasta)
        pasta.mkdir(parents=True)
        shards = [dict() for _ in range(SHARDS)]
        for k, v in self.dados.items():
            shards[fnv1a(k) % SHARDS][k] = v
        tamanho = 0
        for i, s in enumerate(shards):
            # algumas fontes (ex.: descrições do ObrasGov) já chegam com letras perdidas (U+FFFD); na cópia viram "?"
            texto = json.dumps(s, ensure_ascii=False, separators=(",", ":"), default=_json).replace("\ufffd", "?")
            (pasta / f"s{i}.json").write_text(texto, encoding="utf-8")
            tamanho += len(texto.encode())
        with SessionLocal() as db:
            ultima = db.scalar(select(func.max(Parlamentar.id)))  # noqa: F841 (só garante que o banco responde)
            contagem = {"parlamentares": db.scalar(select(func.count()).select_from(Parlamentar)),
                        "votacoes": db.scalar(select(func.count()).select_from(Votacao)),
                        "proposicoes": db.scalar(select(func.count()).select_from(Proposicao)),
                        "normas": db.scalar(select(func.count()).select_from(Norma))}
        manifest = {"versao": VERSAO, "gerado_em": datetime.now().astimezone().isoformat(timespec="minutes"),
                    "shards": SHARDS, "bases": self.bases, "totais": self.totais, "contagem": contagem,
                    "consultas": len(self.dados), "bytes": tamanho}
        (pasta / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, default=_json), encoding="utf-8")
        return manifest


def _intercalar(*listas):
    vistos, out = set(), []
    for grupo in zip(*listas):
        for it in grupo:
            if it["id"] not in vistos:
                vistos.add(it["id"])
                out.append(it)
    for lst in listas:
        for it in lst:
            if it["id"] not in vistos:
                vistos.add(it["id"])
                out.append(it)
    return out


def main(argv):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pasta = Path(argv[0] if argv else "site/dados")
    criar_tabelas()
    exp = Exportador()
    exp.exportar()
    m = exp.gravar(pasta)
    log.info("Cópia gravada em %s: %d respostas, %.1f MB em %d arquivos", pasta, m["consultas"], m["bytes"] / 1e6, SHARDS)
    por_tipo = defaultdict(int)
    for k, v in exp.dados.items():
        por_tipo["/".join(k.split("?")[0].split("/")[:2])] += len(json.dumps(v, ensure_ascii=False, default=_json).encode())
    for t, b in sorted(por_tipo.items(), key=lambda x: -x[1])[:15]:
        log.info("  %-28s %7.2f MB", t, b / 1e6)


if __name__ == "__main__":
    main(sys.argv[1:])
