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
    for sub in sorted(ftp.nlst()):
        ftp.cwd("/pdet/microdados/RAIS/Layouts")
        try:
            ftp.cwd(sub)
        except ftplib.Error:
            continue
        nomes = sorted(ftp.nlst())
        print(f"\nLayouts/{sub}:", nomes)
        for nome in nomes:
            if nome.lower().endswith((".txt", ".csv", ".htm", ".html", ".md")):
                dados = baixar(ftp, nome, limite=20000)
                print(f"\n----- {sub}/{nome} (primeiros {len(dados)} bytes) -----")
                print(dados.decode("latin-1", errors="replace")[:4000])
    ftp.cwd("/pdet/microdados/RAIS/2025")
    print("\n2025:", sorted(ftp.nlst()))
    dados = baixar(ftp, "RAIS_VINC_PUB_NI.7z")
    print("\nNI.7z bytes:", len(dados))
    import os
    import py7zr
    import tempfile
    pasta = tempfile.mkdtemp()
    with py7zr.SevenZipFile(io.BytesIO(dados)) as z:
        print("membros:", z.getnames())
        z.extractall(path=pasta)
    for raiz, _, nomes_ext in os.walk(pasta):
        for nome in nomes_ext:
            with open(os.path.join(raiz, nome), "rb") as fh:
                conteudo = fh.read()
            linhas = conteudo.decode("latin-1", errors="replace").splitlines()
            print(f"\n----- {nome}: {len(linhas)} linhas; cabeçalho com {len(linhas[0]) if linhas else 0} caracteres -----")
            print("CABECALHO_COLUNAS:", linhas[0].count(";") + 1 if linhas and ";" in linhas[0] else (linhas[0].count(",") + 1 if linhas else 0))
            for amostra in linhas[1:8]:
                print("AMOSTRA:", amostra[:600])
    ftp.cwd("/pdet/microdados/RAIS/Layouts/vínculos")
    xls = "RAIS_vinculos_layout2020.xls"
    bruto = baixar(ftp, xls)
    print(f"\n----- {xls}: {len(bruto)} bytes -----")
    try:
        import xlrd
        livro = xlrd.open_workbook(file_contents=bruto)
        for planilha in livro.sheets():
            print(f"\n== aba {planilha.name} ({planilha.nrows} linhas)")
            for r in range(min(planilha.nrows, 90)):
                print(" | ".join(str(c) for c in planilha.row_values(r)))
    except ImportError:
        print("xlrd indisponível")
    ftp.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
