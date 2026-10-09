"""Smoke público sem login: endpoint deve responder e negar acesso aos XMLs."""
import requests
import db

base=f"{db.supabase_url().rstrip('/')}/functions/v1/nf-xml-library-api"
key=db.supabase_key()
headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json"}
cases=[
    ("login",{},400,"LOGIN_E_SENHA_OBRIGATORIOS"),
    ("list",{},401,"SESSAO_NAO_IDENTIFICADA"),
    ("download",{"id":"00000000-0000-0000-0000-000000000000"},401,"SESSAO_NAO_IDENTIFICADA"),
]
for action,payload,code,error in cases:
    r=requests.post(base,json={"action":action,"payload":payload},headers=headers,timeout=40)
    try:actual=r.json()
    except ValueError:raise AssertionError(f"API XML sem resposta JSON: {r.status_code}")
    assert r.status_code==code,(action,r.status_code,actual)
    assert actual.get("error")==error,(action,actual)
print("NF_XML_EDGE_AUTH_SMOKE_OK")
