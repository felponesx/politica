"""Mantém o sistema do seu PC em dia com o que você aprova pelo celular (docs/PC_LOCAL.md).

  python -m scripts.atualizar_local            # confere o GitHub a cada 5 minutos, para sempre
  python -m scripts.atualizar_local --uma-vez  # uma conferência e sai (para agendador do sistema)
  python -m scripts.atualizar_local --ramo X   # ramo a seguir (padrão: o que está aberto na pasta do PC)

A cada conferência: busca o ramo principal (`main`/o ramo informado); se houver novidade, traz para a pasta, reconstrói, roda
os testes dentro do Docker e só então reinicia o sistema. Se os testes reprovarem ou o sistema não responder, volta para a
versão que estava boa, avisa (Telegram/webhook de app/alertas.py) e não tenta de novo a mesma versão. Só segue o ramo principal
(o que a pasta do PC tem aberto): nada em ramo de trabalho, nada que você não tenha aprovado.

A pasta tem que ser uma cópia só para rodar (não edite arquivos nela): a volta usa `git reset --hard`. Se houver arquivo
alterado à mão, o atualizador se recusa a mexer e avisa.
"""
import argparse
import logging
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("brasilplus.atualizador")
RAIZ = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "docker-compose.local.yml", "--env-file", ".env.local"]
TESTE = [*COMPOSE, "run", "--rm", "--no-deps", "-e", "DATABASE_URL=sqlite:////tmp/teste.db", "-e", "SOMENTE_LEITURA=false",
         "api", "python", "-m", "pytest", "-q", "-x"]
SUBIR = [*COMPOSE, "up", "-d", "--build", "--remove-orphans"]


def executar(cmd: list[str], pasta: Path, timeout: int = 1800) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=pasta, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def responde(url: str = "http://127.0.0.1:8000/pronto", espera: int = 120) -> bool:
    fim = time.time() + espera
    while time.time() < fim:
        try:
            if urllib.request.urlopen(url, timeout=5).status == 200:
                return True
        except Exception:  # noqa: BLE001 - ainda subindo
            time.sleep(3)
    return False


class Atualizador:
    def __init__(self, pasta: Path = RAIZ, ramo: str | None = None, rodar=executar, avisar=None, saudavel=responde):
        self.pasta, self.rodar, self.saudavel = Path(pasta), rodar, saudavel
        self.ramo = ramo or rodar(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.pasta, 30)[1] or "main"
        self.avisar = avisar or self._avisar
        self.estado = self.pasta / ".atualizador"
        self.estado.mkdir(exist_ok=True)

    def _avisar(self, texto: str):
        log.warning(texto)
        try:
            sys.path.insert(0, str(self.pasta))
            from app.alertas import enviar
            enviar("BRASIL+ (PC): " + texto)
        except Exception:  # noqa: BLE001 - o aviso nunca derruba o atualizador
            pass

    def git(self, *args: str) -> str:
        cod, saida = self.rodar(["git", *args], self.pasta, 300)
        if cod:
            raise RuntimeError(f"git {' '.join(args)}: {saida[-300:]}")
        return saida

    def _ler(self, nome: str) -> str:
        arq = self.estado / nome
        return arq.read_text().strip() if arq.exists() else ""

    def _gravar(self, nome: str, valor: str):
        (self.estado / nome).write_text(valor + "\n")

    def conferir(self) -> str:
        """Uma volta. Devolve o que aconteceu: 'em dia', 'atualizado', 'reprovado' ou 'recusado'."""
        self.git("fetch", "origin", self.ramo)
        novo, atual = self.git("rev-parse", f"origin/{self.ramo}"), self.git("rev-parse", "HEAD")
        if novo == atual:
            return "em dia"
        if novo == self._ler("rejeitado"):
            return "reprovado"  # já testamos esta versão e ela não passou: espera o ramo andar
        if self.git("status", "--porcelain", "--untracked-files=no"):
            self.avisar("há arquivos alterados à mão na pasta do sistema; não atualizei. Deixe a pasta só para rodar.")
            return "recusado"
        bom = self._ler("ultimo_bom") or atual
        resumo = self.git("log", "--format=%h %s", "-1", novo)[:120]
        try:
            self.git("merge", "--ff-only", f"origin/{self.ramo}")
        except RuntimeError:
            self.avisar("o ramo local se afastou do GitHub (não dá para só avançar); não atualizei.")
            return "recusado"
        cod, saida = self.rodar([*COMPOSE, "build"], self.pasta, 3600)
        if cod == 0:
            cod, saida = self.rodar(TESTE, self.pasta, 3600)
        if cod:
            return self._voltar(bom, novo, f"testes reprovaram a versão {resumo}", saida)
        cod, saida = self.rodar(SUBIR, self.pasta, 3600)
        if cod or not self.saudavel():
            return self._voltar(bom, novo, f"o sistema não subiu direito com {resumo}", saida)
        self._gravar("ultimo_bom", novo)
        self.avisar(f"atualizado para {resumo}")
        return "atualizado"

    def _voltar(self, bom: str, ruim: str, motivo: str, saida: str) -> str:
        self._gravar("rejeitado", ruim)
        self.git("reset", "--hard", bom)
        self.rodar(SUBIR, self.pasta, 3600)  # sobe de novo a versão boa
        self.avisar(f"{motivo}. Voltei para a versão anterior e não tento de novo até chegar uma nova. Fim do log: {saida[-300:]}")
        return "reprovado"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--intervalo", type=int, default=300, help="segundos entre conferências")
    ap.add_argument("--ramo", default=None, help="padrão: o ramo aberto na pasta")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    at = Atualizador(ramo=a.ramo)
    while True:
        try:
            log.info("conferência: %s", at.conferir())
        except Exception as e:  # noqa: BLE001 - rede fora do ar etc.: tenta de novo na próxima volta
            log.error("conferência falhou: %s", e)
        if a.uma_vez:
            return
        time.sleep(a.intervalo)


if __name__ == "__main__":
    main()
