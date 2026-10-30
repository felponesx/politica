"""Testa variações de propertyName/sortBy no WFS do TerraBrasilis (erro 'Can handle 5 attributes only'). Saída curta."""
import re

import httpx

cli = httpx.Client(timeout=300, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126.0", "Accept": "*/*"})
WFS = "https://terrabrasilis.dpi.inpe.br/geoserver/ows"
base = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "outputFormat": "csv", "count": 3}
casos = [
    ("prodes-caatinga-nb:yearly_deforestation", {"propertyName": "state,year,area_km,main_class", "sortBy": "fid"}),
    ("prodes-caatinga-nb:yearly_deforestation", {"propertyName": "fid,state,year,area_km,main_class", "sortBy": "fid"}),
    ("prodes-caatinga-nb:yearly_deforestation", {"propertyName": "state,year,area_km,main_class"}),
    ("prodes-caatinga-nb:yearly_deforestation", {"propertyName": "state,year,area_km,main_class", "sortBy": "year"}),
    ("prodes-caatinga-nb:yearly_deforestation", {"propertyName": "state,year,area_km", "sortBy": "fid"}),
    ("deter-amz:deter_amz", {"propertyName": "uf,areamunkm,classname,view_date", "sortBy": "fid"}),
    ("deter-amz:deter_amz", {"propertyName": "gid,uf,areamunkm,classname,view_date", "sortBy": "gid"}),
    ("deter-amz:deter_amz", {"propertyName": "uf,areamunkm,classname,view_date"}),
]
for camada, extra in casos:
    r = cli.get(WFS, params={**base, "typeNames": camada, **extra})
    corpo = re.sub(r"\s+", " ", r.text)[:170]
    print(camada.split(":")[0], extra, "->", r.status_code, corpo, flush=True)
print("fim", flush=True)
