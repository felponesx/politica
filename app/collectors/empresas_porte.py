"""Empresas do Brasil por porte e quantas estão endividadas — cadastro do CNPJ (Receita) × dívida ativa da União (PGFN).

Lê, sem gravar em disco, a base mensal do CNPJ (Estabelecimentos, Simples e Empresas: ver `cnpj_base`) e os três
arquivos trimestrais da PGFN (não previdenciário, previdenciário e FGTS). Conta só as empresas ATIVAS (matriz com
situação cadastral "ativa"), por porte:
  - MEI (optante do SIMEI, no arquivo do Simples), Microempresa (ME, sem MEI), Empresa de pequeno porte (EPP) e
    "Demais" (a Receita não separa média de grande: entram juntas, inclusive as que não informaram o porte);
  - quantas têm dívida inscrita na dívida ativa da União (devedor principal, qualquer valor), quantas estão em
    recuperação judicial e quantas falidas (situação especial do CNPJ).
Também guarda as 300 empresas que mais devem à União e as 300 de maior capital social (com o que devem), para os
rankings. Resultado em `registros` (fonte receita, tipo empresas_porte, chave = mês do CNPJ).

Memória: um byte por CNPJ básico possível (100 milhões = 100 MB) para as marcas, mais a atividade (CNAE) e a UF das
matrizes ativas (500 MB). Cabe com folga na máquina do robô.
"""
import heapq
import os
import time
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app import http
from app.collectors import cnpj_base as cb
from app.collectors.base import log, registrar_coleta
from app.collectors.pgfn import ARQUIVOS, URL as URL_PGFN, ler_inscricoes
from app.collectors.arquivos import baixar_temp
from app.models import Registro
from app.utils import upsert

ATIVA, DEVEDOR, RJ, FALIDA, MEI = 1, 2, 4, 8, 16
PORTES = ("MEI", "Microempresa", "Empresa de pequeno porte", "Demais (médias e grandes)")
UFS = ("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RN RS RO RR SC SP SE TO EX").split()
N = 100_000_000


def ultimo_trimestre_pgfn() -> tuple[int, int]:
    """O trimestre mais recente publicado pela PGFN (testa do atual para trás)."""
    hoje = date.today()
    a, t = hoje.year, (hoje.month - 1) // 3 + 1
    for _ in range(8):
        url = URL_PGFN.format(ano=a, tri=t, nome=ARQUIVOS["nao_previdenciaria"])
        try:
            if http._cliente.head(url, timeout=60, follow_redirects=True).status_code == 200:
                return a, t
        except Exception:
            pass
        a, t = (a, t - 1) if t > 1 else (a - 1, 4)
    raise RuntimeError("Nenhum trimestre da PGFN encontrado")


def marcar_devedores(flags: bytearray, caminho_zip: str, divida: dict, nomes: dict):
    """Marca os CNPJs básicos com dívida (devedor principal, pessoa jurídica) e soma o valor por CNPJ básico."""
    for i in ler_inscricoes(caminho_zip):
        if not i["pj"] or not i["principal"] or len(i["doc"] or "") != 14:
            continue
        b = int(i["doc"][:8])
        flags[b] |= DEVEDOR
        divida[b] = divida.get(b, 0.0) + i["valor"]
        if i["valor"] >= 1_000_000 and b not in nomes:  # nome só das grandes (as do ranking), para poupar memória
            nomes[b] = i["nome"][:120]


def ler_estabelecimentos(linhas, flags, cnae, uf, prazo=None):
    """Matriz ativa → marca ATIVA e guarda CNAE e UF; situação especial → RJ ou FALIDA (qualquer estabelecimento)."""
    for k, bruta in enumerate(linhas):
        if prazo and k % 500000 == 0 and time.monotonic() > prazo:
            raise cb.TempoEsgotado
        c = bruta.rstrip(b"\r\n").split(b'";"')
        if len(c) < 30:
            continue
        try:
            b = int(c[0].lstrip(b'"'))
        except ValueError:
            continue
        if c[3] == b"1" and c[5] == b"02":
            flags[b] |= ATIVA
            try:
                cnae[b] = int(c[11] or 0)
            except ValueError:
                pass
            u = c[19].decode("latin-1")
            uf[b] = UFS.index(u) + 1 if u in UFS else 0
        if not bruta.rstrip(b"\r\n").endswith(cb.SEM_SITUACAO_ESPECIAL):
            t = cb.tipo_situacao(c[28].decode("latin-1"))
            if t == "recuperacao_judicial":
                flags[b] |= RJ
            elif t == "falencia":
                flags[b] |= FALIDA


def ler_simples(linhas, flags, prazo=None):
    for k, bruta in enumerate(linhas):
        c = bruta.rstrip(b"\r\n").split(b'";"')
        if len(c) >= 5 and c[4] == b"S":
            try:
                flags[int(c[0].lstrip(b'"'))] |= MEI
            except ValueError:
                continue


def ler_empresas(linhas, flags, divida, alvo, prazo=None):
    """Conta por porte as empresas ativas; guarda razão social/porte/capital das maiores devedoras e as de maior capital."""
    cont = {p: {"total": 0, "com_divida": 0, "recuperacao_judicial": 0, "falidas": 0, "divida_total": 0.0} for p in PORTES}
    capital_top, info = [], {}
    for k, bruta in enumerate(linhas):
        if prazo and k % 500000 == 0 and time.monotonic() > prazo:
            raise cb.TempoEsgotado
        c = bruta.rstrip(b"\r\n").split(b'";"')
        if len(c) < 6:
            continue
        try:
            b = int(c[0].lstrip(b'"'))
        except ValueError:
            continue
        f = flags[b]
        if not f & ATIVA and b not in alvo:
            continue
        porte_cod = c[5].rstrip(b'"')
        try:
            capital = float(c[4].decode().replace(".", "").replace(",", "."))
        except ValueError:
            capital = 0.0
        if f & ATIVA:
            p = PORTES[0] if f & MEI else PORTES[1] if porte_cod == b"01" else PORTES[2] if porte_cod == b"03" else PORTES[3]
            x = cont[p]
            x["total"] += 1
            if f & DEVEDOR:
                x["com_divida"] += 1
                x["divida_total"] += divida.get(b, 0.0)
            if f & RJ:
                x["recuperacao_judicial"] += 1
            if f & FALIDA:
                x["falidas"] += 1
            grande = p == PORTES[3] and (len(capital_top) < 300 or capital > capital_top[0][0])
            if grande:
                (heapq.heappush if len(capital_top) < 300 else heapq.heapreplace)(capital_top, (capital, b))
        else:
            grande = False
        if b in alvo or grande:
            info[b] = (c[1].decode("latin-1").strip(), cb.PORTE.get(porte_cod.decode(), "Não informado"), capital,
                       c[2].decode("latin-1"))
    return cont, capital_top, info


def coletar_empresas_porte(mes: str | None = None, ano: int | None = None, trimestre: int | None = None,
                           minutos: int = 200, paralelo: int = 10, pasta_local: str | None = None,
                           pgfn_local: str | None = None):
    """Ex.: python -m scripts.coletar receita-empresas-porte   (último mês do CNPJ e último trimestre da PGFN)"""
    with registrar_coleta("receita", "empresas_porte", mes=mes or "último") as (db, n):
        inicio = time.monotonic()
        flags, divida, nomes = bytearray(N), {}, {}
        # 1) dívida ativa da União (três arquivos)
        if pgfn_local:
            caminhos, ref = [pgfn_local], "local"
        else:
            ano, trimestre = (int(ano), int(trimestre)) if ano and trimestre else ultimo_trimestre_pgfn()
            ref = f"{ano}T{trimestre}"
            caminhos = []
            for tipo, nome in ARQUIVOS.items():
                try:
                    caminhos.append(baixar_temp(URL_PGFN.format(ano=ano, tri=trimestre, nome=nome), f"pgfn-{tipo}-{ref}.zip"))
                except Exception as e:
                    n.avisos.append(f"PGFN {tipo}: {type(e).__name__}")
        for cam in caminhos:
            marcar_devedores(flags, cam, divida, nomes)
            if not pgfn_local:
                os.remove(cam)
        log.info("PGFN %s: %s empresas devedoras", ref, len(divida))
        # 2) cadastro do CNPJ
        cli = None if pasta_local else cb._cliente()
        mes = mes or ("local" if pasta_local else cb.ultimo_mes(cli))
        cnae, uf = array("I", bytes(4 * N)), bytearray(N)

        def ler(nome, fn, *args, prazo=None):
            try:
                if pasta_local:
                    caminho = os.path.join(pasta_local, nome)
                    return fn(cb.linhas_do_zip(cb.blocos_arquivo(caminho)), *args, prazo=prazo) if os.path.exists(caminho) else None
                with cli.stream("GET", f"{cb.WEBDAV}{mes}/{nome}") as r:
                    r.raise_for_status()
                    return fn(cb.linhas_do_zip(r.iter_bytes(1 << 20)), *args, prazo=prazo)
            except cb.TempoEsgotado:
                n.avisos.append(f"{nome}: tempo esgotado")
            except Exception as e:
                n.avisos.append(f"{nome}: {type(e).__name__}: {e}"[:200])
            return None

        prazo = inicio + minutos * 60
        with ThreadPoolExecutor(paralelo) as ex:
            list(ex.map(lambda i: ler(f"Estabelecimentos{i}.zip", ler_estabelecimentos, flags, cnae, uf, prazo=prazo), range(10)))
        ler("Simples.zip", ler_simples, flags)
        top_divida = [b for b, _ in heapq.nlargest(300, divida.items(), key=lambda x: x[1])]
        alvo = frozenset(top_divida)
        with ThreadPoolExecutor(paralelo) as ex:
            partes = list(ex.map(lambda i: ler(f"Empresas{i}.zip", ler_empresas, flags, divida, alvo, prazo=prazo), range(10)))
        cnaes = ler("Cnaes.zip", cb.ler_tabela) or {}
        if cli:
            cli.close()
        partes = [p for p in partes if p]
        if not partes:
            raise RuntimeError("Nenhum arquivo de Empresas lido: " + "; ".join(n.avisos)[:500])
        cont = {p: {k: 0 for k in partes[0][0][p]} for p in PORTES}
        capital_top, info = [], {}
        for c_, cap, inf in partes:
            for p in PORTES:
                for k, v in c_[p].items():
                    cont[p][k] += v
            capital_top.extend(cap)
            info.update(inf)
        capital_top = sorted(set(capital_top), reverse=True)[:300]

        def empresa(b):
            nome, porte, capital, nat = info.get(b, (nomes.get(b), None, None, None))
            f = flags[b]
            cn = f"{cnae[b]:07d}" if cnae[b] else None
            return {"cnpj_basico": f"{b:08d}", "nome": nome, "porte": porte, "capital_social": capital,
                    "uf": UFS[uf[b] - 1] if uf[b] else None, "cnae": cn, "atividade": cnaes.get(cn) if cn else None,
                    "divida_uniao": round(divida.get(b, 0.0), 2), "ativa": bool(f & ATIVA),
                    "recuperacao_judicial": bool(f & RJ), "falida": bool(f & FALIDA), "mei": bool(f & MEI)}
        maiores = [empresa(b) for b in top_divida]
        grandes = [empresa(b) for _, b in capital_top]
        for p in PORTES:
            cont[p]["divida_total"] = round(cont[p]["divida_total"], 2)
        dados = {"mes_cnpj": mes, "pgfn_referencia": ref, "por_porte": cont, "maiores_devedoras": maiores,
                 "maiores_empresas": grandes, "devedoras_total": len(divida), "parcial": bool(n.avisos)}
        upsert(db, Registro, {"fonte": "receita", "tipo": "empresas_porte", "chave": mes},
               {"ano": int(mes[:4]) if mes[:4].isdigit() else None, "titulo": f"Empresas por porte {mes}",
                "valor": sum(v["total"] for v in cont.values()), "dados": dados})
        n += 1
    return n.itens
