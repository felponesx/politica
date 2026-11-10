"""Acrescenta a uma cópia estática pronta os dados novos da Saúde (leitos por município, cobertura vacinal e mínimo constitucional)
e os votos dos tribunais, sem refazer a cópia inteira: lê do banco (DATABASE_URL) e junta em /saude/painel e
/saude/municipios?…&uf=XX, e grava /saude/vacinacao, /saude/minimo e /votos-tribunais. Nada do que já está na cópia é apagado:
só entram os campos novos.

    python -m scripts.copia_saude_tribunais [site/dados]
Os pacotes (dados/p/*.json) que já trazem essas chaves são atualizados no lugar; as chaves novas entram no pacote do assunto
(NOVAS_NO_PACOTE) e no manifest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app import saude, votos_tribunais
from app.db import SessionLocal
from app.utils import UFS
from scripts.exportar_snapshot import GRANDE, fnv1a

NOVAS_NO_PACOTE = {"/saude/vacinacao": "p/ambiente.json", "/saude/minimo": "p/ambiente.json", "/votos-tribunais": "p/escandalos.json"}
CAMPOS_MUN = ("leitos", "leitos_sus", "leitos_uti", "leitos_uti_sus", "hospitais", "leitos_por_mil", "leitos_competencia", "vacinacao_ano", "vacinacao",
              "saude_minimo_pct", "saude_minimo_exigido", "saude_minimo_cumpriu", "saude_minimo_valor")


def _texto(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)


class Copia:
    def __init__(self, pasta: Path):
        self.pasta = pasta
        self.manifest = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
        self.n = self.manifest["shards"]
        self.valores: dict = {}
        self.shards: dict[int, dict] = {}
        self.mudou: set[str] = set()

    def _shard(self, k: str) -> dict:
        i = fnv1a(k) % self.n
        if i not in self.shards:
            self.shards[i] = json.loads((self.pasta / f"s{i}.json").read_text(encoding="utf-8"))
        return self.shards[i]

    def ler(self, k: str):
        v = self._shard(k).get(k)
        if isinstance(v, dict) and set(v) == {"__arquivo"}:
            v = json.loads((self.pasta / v["__arquivo"]).read_text(encoding="utf-8"))
        return v

    def gravar(self, k: str, v):
        self.valores[k] = v
        texto = _texto(v)
        sh = self._shard(k)
        if len(texto.encode()) > GRANDE:
            nome = f"g/{fnv1a(k):08x}.json"
            (self.pasta / "g").mkdir(exist_ok=True)
            (self.pasta / nome).write_text(texto, encoding="utf-8")
            self.mudou.add(nome)
            v = {"__arquivo": nome}
        sh[k] = v
        self.mudou.add(f"s{fnv1a(k) % self.n}.json")

    def _pacotes(self):
        pac = self.manifest.get("pacotes") or {}
        for k, v in self.valores.items():
            alvo = [a for a, x in pac.items() if k in x["chaves"]] or ([NOVAS_NO_PACOTE[k]] if NOVAS_NO_PACOTE.get(k) in pac else [])
            for a in alvo:
                arq = self.pasta / a
                dados = json.loads(arq.read_text(encoding="utf-8"))
                dados[k] = v if len(_texto(v).encode()) <= GRANDE else {"__arquivo": f"g/{fnv1a(k):08x}.json"}
                arq.write_text(_texto(dados), encoding="utf-8")
                if k not in pac[a]["chaves"]:
                    pac[a]["chaves"] = sorted(pac[a]["chaves"] + [k])
                    self.mudou.add("manifest.json")
                self.mudou.add(a)
        if "manifest.json" in self.mudou:
            (self.pasta / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    def salvar(self):
        self._pacotes()
        for i, sh in self.shards.items():
            if f"s{i}.json" in self.mudou:
                (self.pasta / f"s{i}.json").write_text(_texto(sh), encoding="utf-8")
        return sorted(self.mudou)


def juntar(pasta: Path) -> list[str]:
    c = Copia(pasta)
    with SessionLocal() as db:
        fontes = saude.fontes_municipais(db)
        p = c.ler("/saude/painel")
        if p:
            ext_uf, ext_br = saude.extras_painel(db)
            for uf, x in ext_uf.items():
                p.setdefault("estados", {}).setdefault(uf, {}).update(x)
            p.setdefault("brasil", {}).update(ext_br)
            p["notas"] = [n for n in p.get("notas") or [] if n not in saude.NOTAS_MUN.values()] + list(saude.NOTAS_MUN.values())
            p["fontes_novas"] = fontes
            c.gravar("/saude/painel", p)
        for uf in UFS:
            k = f"/saude/municipios?limit=500&uf={uf}"
            atual = c.ler(k)
            if not atual:
                continue
            novos = {x["codigo_ibge"]: x for x in saude.municipios(db, uf, 100_000)}
            for it in atual.get("itens") or []:
                x = novos.get(it.get("codigo_ibge")) or {}
                for campo in CAMPOS_MUN:
                    it.pop(campo, None)
                    if campo in x:
                        it[campo] = x[campo]
            if p and "ubs" not in (p.get("brasil") or {}):  # UBS não coletadas na cópia: 0 viraria dado falso
                for it in atual.get("itens") or []:
                    it["ubs"] = it["ubs_por_10mil"] = None
            atual["fontes"] = fontes
            c.gravar(k, atual)
        for k, fn in (("/saude/vacinacao", saude.vacinacao), ("/saude/minimo", saude.minimo)):
            v = fn(db)
            if v:
                c.gravar(k, v)
        v = votos_tribunais.dados(db)
        if v:
            c.gravar("/votos-tribunais", v)
    return c.salvar()


if __name__ == "__main__":
    for arq in juntar(Path(sys.argv[1] if len(sys.argv) > 1 else "site/dados")):
        print(arq)
