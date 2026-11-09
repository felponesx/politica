"""Diagnóstico da RAIS 2025 (só leitura): lista a pasta Layouts e lê o cabeçalho do arquivo regional pequeno (NI).
Não grava no banco. Serve para descobrir o nome e a ordem das colunas (CBO, remuneração, horas contratadas)."""
import ftplib
import io
import sys

HOST = "ftp.mtps.gov.br"


def conectar():
    ftp = ftplib.FTP(HOST, timeout=180, encoding="latin-1")
    ftp.login()
    return ftp


def baixar(ftp, nome, limite=None):
    buf = io.BytesIO()

    def cb(b):
        buf.write(b)
        if limite and buf.tell() >= limite:
            raise StopIteration

    try:
        ftp.retrbinary(f"RETR {nome}", cb, blocksize=1 << 20)
    except StopIteration:
        pass
    return buf.getvalue()


def main():
    ftp = conectar()
    ftp.cwd("/pdet/microdados/RAIS/Layouts")
    nomes = sorted(ftp.nlst())
    print("Layouts:", nomes)
    for nome in nomes:
        if nome.lower().endswith((".txt", ".csv", ".htm", ".html", ".md")):
            dados = baixar(ftp, nome, limite=20000)
            print(f"\n----- {nome} (primeiros {len(dados)} bytes) -----")
            print(dados.decode("latin-1", errors="replace")[:4000])
    ftp.cwd("/pdet/microdados/RAIS/2025")
    print("\n2025:", sorted(ftp.nlst()))
    dados = baixar(ftp, "RAIS_VINC_PUB_NI.7z")
    print("\nNI.7z bytes:", len(dados))
    import py7zr
    with py7zr.SevenZipFile(io.BytesIO(dados)) as z:
        print("membros:", z.getnames())
        for nome, bio in z.readall().items():
            conteudo = bio.read(4000)
            print(f"\n----- {nome}: primeiras linhas -----")
            print(conteudo.decode("latin-1", errors="replace")[:2500])
    ftp.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
