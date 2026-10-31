"""Mostra o que as duas coletas de malha gravaram no banco (resumo curto) e o histórico de execuções."""
from sqlalchemy import text

from app.db import SessionLocal

db = SessionLocal()
print("== coletas")
for r in db.execute(text("select id, tarefa, status, itens, left(coalesce(erro,''),300) from coletas where fonte='osm' order by id")):
    print(" ", tuple(r))
print("== registros osm")
for r in db.execute(text("select tipo, chave, dados->>'metodo', dados->>'osm_base', dados->>'medido_em', valor from registros where fonte='osm' and tipo in ('malha_capital','malha_parte','relacao_municipio') order by tipo, chave")):
    print(" ", tuple(r))
print("== duplicidade de chaves")
print(" ", db.execute(text("select count(*) from (select tipo, chave from registros where fonte='osm' group by 1,2 having count(*)>1) x")).scalar(), "chaves repetidas")
print("== malha_capital (PBF)")
for r in db.execute(text("select chave, dados->'por_categoria', dados->>'trechos', dados->>'vias_nomeadas', dados->>'extrato', dados->>'md5_confere', dados->'estatisticas_do_passe' from registros where fonte='osm' and tipo='malha_capital' and dados->>'metodo'='pbf'")):
    print(" ", tuple(r))
print("== Overpass x PBF (km por capital)")
for r in db.execute(text("select p.chave, round(sum((c.value->>'km')::numeric),1) from registros p, jsonb_each(p.dados->'por_categoria') c where p.fonte='osm' and p.tipo='malha_parte' group by 1") ) if False else []:
    pass
for uf in [r[0] for r in db.execute(text("select distinct dados->>'uf' from registros where fonte='osm' and tipo='malha_parte'"))]:
    km = db.execute(text("select coalesce(sum((v.value->>'km')::numeric),0) from registros p, jsonb_each(p.dados->'por_categoria') v where p.fonte='osm' and p.tipo='malha_parte' and p.dados->>'uf'=:u"), {"u": uf}).scalar()
    pbf = db.execute(text("select valor from registros where fonte='osm' and tipo='malha_capital' and chave=:u and dados->>'metodo'='pbf'"), {"u": uf}).scalar()
    print(" ", uf, "overpass(partes)=", round(float(km), 1), "km  pbf=", pbf, "km")
