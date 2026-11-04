"""Ingestão dos dados LIBERADOS pelo coletor do celular (verificados pelo corretor e, se preciso, corrigidos só no formato).

O coletor do celular publica, num repositório de dados, uma pasta por fonte:

    dados/<fonte>/atual.<ext>   o arquivo liberado (ou a cópia só com formato ajustado)
    dados/<fonte>/meta.json     de onde veio, hash, veredito do corretor, se foi corrigido e quais regras

Esta tarefa lê essa pasta e grava em `registros` com a MESMA função dos coletores próprios (ex.: `bcb.gravar_pontos`),
então o formato no banco é um só, venha o dado do robô ou do celular.

Regras de segurança:
- só entra o que o corretor liberou (veredito "ok" ou decisão "aprovado" por você);
- o arquivo é conferido contra o hash do `meta.json` (arquivo pela metade ou trocado não entra);
- o mesmo arquivo (mesmo hash) nunca é ingerido duas vezes;
- fonte sem adaptador é ignorada (não é erro): cada fonte nova ganha o seu adaptador aqui.

A pasta vem do parâmetro `pasta` ou da variável COLETOR_DADOS (um clone do repositório de dados do coletor). Se a pasta for um
repositório git, `git pull --ff-only` roda antes da leitura; sem rede, usa o que já está lá.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from app.collectors import bcb
from app.collectors.base import registrar_coleta
from app.db import SessionLocal
from app.models import Coleta, Registro
from app.utils import para_data, para_float, para_uf, upsert

log = logging.getLogger("brasilplus.coletor_externo")


def _adaptar_bcb(db, n, caminho: Path, meta: dict):
    """Série do SGS (Banco Central): lista de {"data", "valor"}. O código da série vem do endereço da fonte."""
    m = re.search(r"bcdata\.sgs\.(\d+)", meta.get("url", ""))
    if not m:
        raise ValueError("o endereço da fonte não é de uma série do SGS")
    codigo = int(m.group(1))
    nome = next((k for k, v in bcb.SERIES.items() if v[0] == codigo), None)
    if nome is None:
        raise ValueError(f"série {codigo} do SGS não está cadastrada em app/collectors/bcb.py")
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, list) or not dados:
        raise ValueError("série vazia ou fora do formato (esperado: lista de {data, valor})")
    bcb.gravar_pontos(db, n, nome, dados)
    if not n.itens:
        raise ValueError("nenhum ponto válido na série")


def _pega(obj, caminho):
    """Lê um campo por caminho pontilhado ("a.b.c"). Devolve None se não existir."""
    for parte in str(caminho).split("."):
        if isinstance(obj, dict) and parte in obj:
            obj = obj[parte]
        else:
            return None
    return obj


_TIPO_OK = re.compile(r"^[a-z0-9_:\-]{1,60}$")


def _adaptar_linhas(db, n, caminho: Path, meta: dict):
    """Adaptador genérico: lista de objetos JSON -> registros, pelo mapa que o vínculo declara.
    Assim uma fonte nova entra SEM código novo: basta declarar `adaptador = "linhas"` e o `mapa` no vínculo."""
    mapa = meta.get("mapa")
    if not isinstance(mapa, dict):
        raise ValueError("adaptador 'linhas' sem mapa no vínculo")
    tipo = mapa.get("tipo")
    if not isinstance(tipo, str) or not _TIPO_OK.match(tipo):
        raise ValueError("mapa.tipo inválido (use letras minúsculas, números, _ : -)")
    if not mapa.get("chave"):
        raise ValueError("mapa.chave é obrigatório")
    linhas = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(linhas, list) or not linhas:
        raise ValueError("lista vazia ou fora do formato (esperado: lista de objetos)")
    fonte = meta["fonte"]
    for r in linhas:
        if not isinstance(r, dict):
            continue
        chave = _pega(r, mapa["chave"])
        if chave is None or not str(chave).strip():
            continue
        valor = para_float(_pega(r, mapa["valor"])) if mapa.get("valor") else None
        titulo = _pega(r, mapa["titulo"]) if mapa.get("titulo") else None
        uf = para_uf(_pega(r, mapa["uf"])) if mapa.get("uf") else None
        data = para_data(_pega(r, mapa["data"])) if mapa.get("data") else None
        dados = {k: _pega(r, c) for k, c in (mapa.get("dados") or {}).items()}
        upsert(db, Registro, {"fonte": fonte, "tipo": tipo, "chave": str(chave).strip()[:200]},
               {"uf": uf, "ano": data.year if data else None,
                "titulo": str(titulo)[:500] if titulo is not None else None, "valor": valor,
                "dados": {"data": data.isoformat() if data else None, **dados}})
        n += 1
    db.commit()
    if not n.itens:
        raise ValueError("nenhuma linha com chave válida")


_ADAPTADORES_GENERICOS = {"linhas": _adaptar_linhas}
ADAPTADORES = {"bcb": _adaptar_bcb}   # fontes com adaptador próprio (nome da fonte -> função)


def _liberado(meta: dict) -> bool:
    return meta.get("veredito") == "ok" or meta.get("decisao") == "aprovado"


def _ja_ingerida(fonte: str, sha: str) -> bool:
    db = SessionLocal()
    try:
        recentes = (db.query(Coleta).filter(Coleta.fonte == "coletor", Coleta.tarefa == "ingestao", Coleta.status.in_(("ok", "parcial")))
                    .order_by(Coleta.id.desc()).limit(1000).all())
        return any((c.parametros or {}).get("bot") == fonte and (c.parametros or {}).get("sha256") == sha for c in recentes)
    finally:
        db.close()


def _registrar_falha(fonte: str, erro: str):
    """Falha de validação (antes de a coleta abrir): fica em `coletas` para a tela de situação, sem repetir a mesma mensagem a cada rodada."""
    db = SessionLocal()
    try:
        ultimas = db.query(Coleta).filter(Coleta.fonte == "coletor", Coleta.tarefa == "ingestao").order_by(Coleta.id.desc()).limit(50).all()
        ultima = next((c for c in ultimas if (c.parametros or {}).get("bot") == fonte), None)
        if ultima and ultima.status == "erro" and ultima.erro == erro[:4000]:
            return
        db.add(Coleta(fonte="coletor", tarefa="ingestao", parametros={"bot": fonte}, status="erro", erro=erro[:4000], fim=datetime.now()))
        db.commit()
    finally:
        db.close()


def _atualizar_clone(pasta: Path):
    """git pull da pasta de dados. COLETOR_PULL=0 desliga (no Docker a imagem não tem git: quem puxa é o PC, e a pasta entra só para leitura)."""
    if os.environ.get("COLETOR_PULL", "1") == "0" or not shutil.which("git"):
        return
    if (pasta / ".git").exists():
        try:
            subprocess.run(["git", "-C", str(pasta), "pull", "-q", "--ff-only"], check=True, timeout=120, capture_output=True)
        except Exception as e:   # sem rede ou sem acesso: segue com o que já está na pasta
            log.warning("git pull falhou em %s: %s", pasta, type(e).__name__)


def _ler_meta(pasta_fonte: Path) -> dict:
    meta = json.loads((pasta_fonte / "meta.json").read_text(encoding="utf-8"))
    for campo in ("fonte", "sha256", "arquivo", "bytes", "veredito"):
        if campo not in meta:
            raise ValueError(f"meta.json sem o campo {campo}")
    if meta["fonte"] != pasta_fonte.name:
        raise ValueError("meta.json é de outra fonte")
    if Path(meta["arquivo"]).name != meta["arquivo"]:
        raise ValueError("nome de arquivo inválido no meta.json")
    return meta


def coletar_ingestao(pasta: str | None = None):
    """Ingere o que o coletor do celular liberou desde a última vez. Devolve o total de itens gravados."""
    raiz = Path(pasta or os.environ.get("COLETOR_DADOS") or "dados_coletor")
    if not raiz.exists():
        raise FileNotFoundError(f"pasta do coletor não encontrada: {raiz} (use pasta=… ou COLETOR_DADOS)")
    _atualizar_clone(raiz)
    total, erros = 0, []
    for pf in sorted((raiz / "dados").glob("*/meta.json")):
        fonte = pf.parent.name
        dentro = False   # dentro de registrar_coleta, o próprio contexto já grava o erro
        try:
            meta = _ler_meta(pf.parent)
            if not _liberado(meta):
                log.info("%s: não liberado pelo corretor, ignorado", fonte)
                continue
            if meta.get("adaptador"):   # declarado pelo vínculo: se não existir, é erro (não pode ser ignorado em silêncio)
                adaptador = _ADAPTADORES_GENERICOS.get(meta["adaptador"])
                if adaptador is None:
                    raise ValueError(f"adaptador desconhecido: {meta['adaptador']}")
            else:
                adaptador = ADAPTADORES.get(fonte)
            if adaptador is None:
                log.info("%s: sem adaptador no BRASIL+, ignorado", fonte)
                continue
            caminho = pf.parent / meta["arquivo"]
            conteudo = caminho.read_bytes()
            if len(conteudo) != meta["bytes"] or hashlib.sha256(conteudo).hexdigest() != meta["sha256"]:
                raise ValueError("o arquivo não confere com o hash do meta.json (incompleto ou trocado)")
            if _ja_ingerida(fonte, meta["sha256"]):
                continue
            dentro = True
            with registrar_coleta("coletor", "ingestao", bot=fonte, sha256=meta["sha256"], corrigido=meta.get("corrigido", False),
                                  veredito=meta["veredito"], decisao=meta.get("decisao", "")) as (db, n):
                adaptador(db, n, caminho, meta)
            total += n.itens
        except Exception as e:   # uma fonte com problema não impede as outras
            erros.append(f"{fonte}: {type(e).__name__}: {e}")
            log.warning("ingestão de %s falhou: %s", fonte, e)
            if not dentro:
                _registrar_falha(fonte, f"{type(e).__name__}: {e}")
    if erros:
        raise RuntimeError("; ".join(erros))
    return total
