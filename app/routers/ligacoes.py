from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (Candidato, CandidatoFinancas, Contrato, Despesa, Norma, Parlamentar, Proposicao, Registro,
                        ResultadoEleicao, Votacao)
from app.utils import formatar_documento, so_digitos

router = APIRouter(tags=["Ligações"])

AVISO = ("Cruzamento automático de dados públicos. Aparecer em mais de uma base não indica, por si só, "
         "qualquer irregularidade.")


def resumo_fornecedor(db, cnpj: str) -> dict:
    contratos = db.execute(select(Contrato.esfera, func.count(), func.sum(Contrato.valor))
                           .where(Contrato.cnpj_fornecedor == cnpj).group_by(Contrato.esfera)).all()
    cota = db.execute(select(Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.uf,
                             func.count(), func.sum(Despesa.valor))
                      .join(Parlamentar, Parlamentar.id == Despesa.parlamentar_id)
                      .where(Despesa.cnpj_cpf == cnpj)
                      .group_by(Parlamentar.id, Parlamentar.nome, Parlamentar.partido, Parlamentar.uf)
                      .order_by(func.sum(Despesa.valor).desc())).all()
    return {
        "contratos_publicos": {
            "quantidade": sum(q for _, q, _ in contratos),
            "total": round(sum(v or 0 for _, _, v in contratos), 2),
            "por_esfera": {(e or "?"): {"quantidade": q, "total": round(v or 0, 2)} for e, q, v in contratos},
        },
        "cota_parlamentar": {
            "quantidade": sum(r[4] for r in cota),
            "total": round(sum(r[5] or 0 for r in cota), 2),
            "parlamentares": [{"id": i, "nome": n, "partido": p, "uf": u, "notas": q, "total": round(v or 0, 2)}
                              for i, n, p, u, q, v in cota[:20]],
        },
    }


@router.get("/fornecedores/{documento:path}")
def fornecedor(documento: str, db: Session = Depends(get_db)):
    """Popout de fornecedor: tudo que um CNPJ recebeu de contratos públicos e da cota parlamentar."""
    cnpj = so_digitos(documento)
    nome = db.scalar(select(Contrato.fornecedor).where(Contrato.cnpj_fornecedor == cnpj).limit(1)) or \
        db.scalar(select(Despesa.fornecedor).where(Despesa.cnpj_cpf == cnpj).limit(1))
    if not nome:
        raise HTTPException(404, "Fornecedor não encontrado nas bases coletadas")
    r = resumo_fornecedor(db, cnpj)
    maiores = db.scalars(select(Contrato).where(Contrato.cnpj_fornecedor == cnpj)
                         .order_by(Contrato.valor.desc().nullslast()).limit(10)).all()
    r["contratos_publicos"]["maiores"] = [{"id": c.id, "objeto": c.objeto, "orgao": c.orgao, "uf": c.uf,
                                           "valor": c.valor, "data_assinatura": c.data_assinatura} for c in maiores]
    return {"documento": formatar_documento(cnpj), "nome": nome, **r,
            "aparece_nas_duas_bases": bool(r["contratos_publicos"]["quantidade"] and r["cota_parlamentar"]["quantidade"]),
            "aviso": AVISO}


@router.get("/fornecedores-cruzados")
def fornecedores_cruzados(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """Fornecedores que aparecem ao mesmo tempo em contratos públicos e na cota parlamentar."""
    contratos = (select(Contrato.cnpj_fornecedor.label("cnpj"), func.sum(Contrato.valor).label("total_contratos"),
                        func.max(Contrato.fornecedor).label("nome"))
                 .where(Contrato.cnpj_fornecedor.isnot(None)).group_by(Contrato.cnpj_fornecedor).subquery())
    cota = (select(Despesa.cnpj_cpf.label("cnpj"), func.sum(Despesa.valor).label("total_cota"),
                   func.count(func.distinct(Despesa.parlamentar_id)).label("parlamentares"))
            .where(Despesa.cnpj_cpf.isnot(None)).group_by(Despesa.cnpj_cpf).subquery())
    linhas = db.execute(select(contratos.c.cnpj, contratos.c.nome, contratos.c.total_contratos,
                               cota.c.total_cota, cota.c.parlamentares)
                        .join(cota, cota.c.cnpj == contratos.c.cnpj)
                        .where(func.length(contratos.c.cnpj) == 14)  # só empresas (CPF fica de fora)
                        .order_by(cota.c.total_cota.desc()).limit(limit)).all()
    return {"aviso": AVISO, "itens": [{"documento": formatar_documento(c), "cnpj": c, "nome": n,
                                       "total_contratos_publicos": round(tc or 0, 2), "total_cota_parlamentar": round(tq or 0, 2),
                                       "parlamentares": p} for c, n, tc, tq, p in linhas]}


@router.get("/proposicoes/{pid}")
def proposicao(pid: int, db: Session = Depends(get_db)):
    """Popout de projeto: dados, votações ligadas e a lei que ele virou (se virou)."""
    p = db.get(Proposicao, pid)
    if not p:
        raise HTTPException(404, "Proposição não encontrada")
    votacoes = db.scalars(select(Votacao).where(Votacao.proposicao_id == pid).order_by(Votacao.data)).all()
    norma = db.scalar(select(Norma).where(Norma.proposicao_id == pid))
    tram = db.scalar(select(Registro).where(Registro.tipo == "tramitacao", Registro.chave == str(pid)))
    autores = []
    for a in ((tram.dados or {}).get("autores") or []) if tram else []:
        par = db.scalar(select(Parlamentar).where(Parlamentar.casa == (a.get("casa") or "camara"),
                                                  Parlamentar.id_externo == str(a.get("id_externo")))) if a.get("id_externo") else None
        autores.append({"nome": a.get("nome"), "tipo": a.get("tipo"), "parlamentar_id": par.id if par else None,
                        "partido": par.partido if par else None, "uf": par.uf if par else None})
    return {
        "proposicao": {"id": p.id, "casa": p.casa, "sigla_tipo": p.sigla_tipo, "numero": p.numero, "ano": p.ano,
                       "ementa": p.ementa, "situacao": p.situacao, "data_apresentacao": p.data_apresentacao},
        "votacoes": [{"id": v.id, "casa": v.casa, "data": v.data, "descricao": v.descricao, "resultado": v.resultado,
                      "placar_oficial": v.placar_oficial, "secreta": v.secreta} for v in votacoes],
        "norma_gerada": {"id": norma.id, "tipo": norma.tipo, "numero": norma.numero, "ano": norma.ano,
                         "ementa": norma.ementa, "url_texto": norma.url_texto} if norma else None,
        "autores": autores,
        "tramitacao": ((tram.dados or {}).get("passos") or []) if tram else [],
    }


@router.get("/parlamentares/{pid}/processos", tags=["Ligações"])
def processos_parlamentar(pid: int, db: Session = Depends(get_db)):
    """Casos curados, representações por quebra de decoro (Câmara) e situação do registro de candidatura (TSE); sempre com aviso de presunção de inocência."""
    from app import processos
    p = db.get(Parlamentar, pid)
    if not p:
        raise HTTPException(404, "Parlamentar não encontrado")
    return processos.do_parlamentar(db, p)


@router.get("/parlamentares/{pid}/ligacoes")
def ligacoes_parlamentar(pid: int, db: Session = Depends(get_db)):
    """Complemento do popout de pessoa: candidaturas no TSE e fornecedores da cota que também têm contratos públicos."""
    p = db.get(Parlamentar, pid)
    if not p:
        raise HTTPException(404, "Parlamentar não encontrado")
    candidaturas = []
    for c in db.scalars(select(Candidato).where(Candidato.parlamentar_id == pid).order_by(Candidato.ano.desc())):
        res = db.scalars(select(ResultadoEleicao).where(ResultadoEleicao.sq_candidato == c.sq_candidato)
                         .order_by(ResultadoEleicao.turno)).all()
        fin = db.scalar(select(CandidatoFinancas).where(CandidatoFinancas.ano == c.ano,
                                                        CandidatoFinancas.sq_candidato == c.sq_candidato))
        candidaturas.append({"ano": c.ano, "cargo": c.cargo, "partido": c.partido, "numero": c.numero,
                             "sq_candidato": c.sq_candidato, "ocupacao": c.ocupacao,
                             "resultado": c.resultado, "votos": sum(r.votos for r in res) if res else None,
                             "patrimonio": fin.patrimonio if fin else None, "bens_por_tipo": fin.bens_por_tipo if fin else None,
                             "receitas_campanha": fin.receitas if fin else None,
                             "despesas_campanha": fin.despesas if fin else None,
                             "receitas_por_fonte": fin.receitas_por_fonte if fin else None,
                             "despesas_por_tipo": fin.despesas_por_tipo if fin else None,
                             "despesas_fornecedores": fin.despesas_fornecedores if fin else None})
    forn = db.execute(select(Despesa.cnpj_cpf, func.max(Despesa.fornecedor), func.sum(Despesa.valor))
                      .where(Despesa.parlamentar_id == pid, Despesa.cnpj_cpf.isnot(None))
                      .group_by(Despesa.cnpj_cpf).order_by(func.sum(Despesa.valor).desc()).limit(30)).all()
    com_contrato = []
    for cnpj, nome, total in forn:
        q, v = db.execute(select(func.count(), func.sum(Contrato.valor)).where(Contrato.cnpj_fornecedor == cnpj)).one()
        if q:
            com_contrato.append({"documento": formatar_documento(cnpj), "cnpj": cnpj, "nome": nome,
                                 "pago_pela_cota": round(total or 0, 2), "contratos_publicos": q,
                                 "valor_contratos_publicos": round(v or 0, 2)})
    return {"candidaturas": candidaturas, "fornecedores_com_contratos_publicos": com_contrato, "aviso": AVISO}
