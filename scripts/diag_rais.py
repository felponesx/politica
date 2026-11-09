"""Diagnóstico da RAIS (só leitura): lista o FTP do Ministério do Trabalho e mostra o conteúdo dos arquivos
de vínculos do ano mais novo, SEM baixar o arquivo inteiro. Serve para escolher o ano e conferir o layout antes
de gravar o coletor. Não grava nada no banco."""
import ftplib
import io
import re
import sys

HOST = "ftp.mtps.gov.br"
BASE = "/pdet/microdados/RAIS"


def conectar():
    ftp = ftplib.FTP(HOST, timeout=120, encoding="latin-1")
    ftp.login()
    return ftp


def listar(ftp, caminho):
    ftp.cwd(caminho)
    return sorted(ftp.nlst())


def anos(nomes):
    return sorted({int(m.group(0)) for n in nomes for m in [re.search(r"(19|20)\d{2}", n)] if m}, reverse=True)


def main():
    ftp = conectar()
    print("raiz:", listar(ftp, BASE)[:80])
    nomes = listar(ftp, BASE)
    ano_list = anos(nomes)
    print("anos encontrados:", ano_list[:10])
    for ano in ano_list[:3]:
        pastas = [n for n in nomes if str(ano) in n]
        for p in pastas[:1]:
            try:
                arquivos = listar(ftp, f"{BASE}/{p}")
            except ftplib.Error as e:
                print(p, "-> erro:", e)
                continue
            print(f"\n== {p}: {len(arquivos)} arquivos")
            for a in arquivos[:60]:
                try:
                    tam = ftp.size(a)
                except ftplib.Error:
                    tam = "?"
                print("  ", a, tam)
            ftp.cwd(f"{BASE}/{p}")
            alvo = next((a for a in arquivos if "vinc" in a.lower() and a.lower().endswith((".7z", ".zip", ".txt", ".comt"))), None)
            if alvo:
                try:
                    import py7zr
                    buf = io.BytesIO()
                    ftp.retrbinary(f"RETR {alvo}", buf.write, blocksize=1 << 20) if False else None
                    print("  vínculos de exemplo:", alvo, "(leitura de cabeçalho em etapa seguinte)")
                except ImportError:
                    print("  py7zr indisponível")
    ftp.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
