"""Coletor `gemini-verificar`: o Gemini lê a cópia dos dados e grava SUGESTÕES no banco (registros, fonte "gemini").

- Não altera dado nenhum. Cada suspeita entra como `status: pendente` até uma pessoa marcar como aprovada ou descartada.
- Sem GEMINI_API_KEY no ambiente, a tarefa falha com mensagem e não grava nada.
- Refazer é seguro: a chave da sugestão é o arquivo + caminho + problema. Sugestão que já foi aprovada ou descartada por uma
  pessoa não volta a ser marcada como pendente.
"""
import hashlib
import os
from pathlib import Path

import httpx

from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import upsert

AVISO = ("Sugestão de um modelo de linguagem (Gemini). Pode estar errada: confira na fonte oficial antes de qualquer correção. Nenhum dado foi alterado.")


def coletar_gemini_verificar(pasta: str = "site/dados", limite: int = 0, modelo: str = ""):
    from scripts import verificar_gemini as vg

    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        raise RuntimeError("GEMINI_API_KEY não definida no ambiente; o verificador não rodou e nada foi gravado")
    modelo = modelo or os.environ.get("GEMINI_MODEL", vg.MODELO_PADRAO)
    if not Path(pasta).is_dir():
        raise RuntimeError(f"pasta da cópia não encontrada: {pasta}")
    pedacos = list(vg.pedacos(Path(pasta)))
    if int(limite or 0):
        pedacos = pedacos[: int(limite)]
    with registrar_coleta("gemini", "verificar", modelo=modelo, pedacos=len(pedacos)) as (db, n):
        with httpx.Client() as cli:
            for arq, texto in pedacos:
                for achado in vg.perguntar(cli, chave, modelo, arq, texto):
                    problema = str(achado.get("problema") or "")[:500]
                    chave_sug = hashlib.blake2b(f"{arq}|{achado.get('caminho')}|{problema}".encode(), digest_size=12).hexdigest()
                    atual = db.query(Registro).filter_by(fonte="gemini", tipo="sugestao", chave=chave_sug).first()
                    if atual and (atual.dados or {}).get("status") in ("aprovada", "descartada"):
                        continue  # decisão humana não é apagada por uma nova rodada
                    dados = {"arquivo": arq, "caminho": str(achado.get("caminho") or "")[:300], "problema": problema,
                             "valor_atual": str(achado.get("valor_atual") or "")[:300], "sugestao": str(achado.get("sugestao") or "")[:300],
                             "fonte_citada": str(achado.get("fonte") or "")[:300], "confianca": str(achado.get("confianca") or "")[:20],
                             "modelo": modelo, "status": "pendente", "aviso": AVISO}
                    upsert(db, Registro, {"fonte": "gemini", "tipo": "sugestao", "chave": chave_sug},
                           {"titulo": problema[:200] or "Sugestão", "dados": dados})
                    n += 1
        db.commit()
    return n.itens
