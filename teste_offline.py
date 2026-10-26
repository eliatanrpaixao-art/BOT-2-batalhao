"""Validação local do mapeamento sem acessar tokens, Discord ou Google."""
import ast
from pathlib import Path
import threading
from datetime import datetime,timedelta
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from typing import Callable, Optional

CORE = Path(__file__).with_name('bot_core.py').read_text(encoding='utf-8')
tree = ast.parse(CORE)
keep = {'ErroNegocio', 'normalizar_id', 'valor', 'esc_aba', 'Planilha', 'data_hoje'}
sub = ast.Module(body=[n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in keep], type_ignores=[])
code = compile(ast.fix_missing_locations(sub), '<core-offline>', 'exec')
ns = {'__name__':'__main__', 'threading':threading, 'datetime':datetime,
      'timedelta': timedelta, 'ZoneInfo':ZoneInfo, 'ZONE': ZoneInfo('America/Belem'),
      'UNIDADES': ('BOPE','GRI','SPEED','GRAER','GTM','GRT','PATRULHA'),
      'SITUACOES': ('ATIVO','AFASTADO','FÉRIAS','RESERVA'),
      'CURSO_SITUACOES': ('CONCLUÍDO','EM ANDAMENTO','PENDENTE','REPROVADO'),
      'Config':object, 'gspread': type('gspread',(),{'Worksheet':object}),
      'Callable':Callable, 'Optional':Optional}
exec(code, ns)
Planilha=ns['Planilha']; ErroNegocio=ns['ErroNegocio']

class FakeSheet:
    def __init__(self, name, rows=220):
        self.name=name;self.row_count=rows;self.grid={}
        self.grid[(8,1)]='ID POLICIAL' if name != 'EFETIVO' else 'ID'
    def get(self, a1):
        import re
        m=re.fullmatch(r'([A-Z]+)(\d+):([A-Z]+)(\d+)',a1)
        if not m:raise ValueError(a1)
        c1,r1,c2,r2=m.groups();r1=int(r1);r2=int(r2)
        n1=ord(c1)-64;n2=ord(c2)-64
        return [[self.grid.get((r,c),'') for c in range(n1,n2+1)] for r in range(r1,r2+1)]

class FakeBook:
    def __init__(self):
        self.sheets={name:FakeSheet(name) for name in ['EFETIVO','REGISTROS','CURSOS','ADVERTÊNCIAS','MEDALHAS']}
        sheet=self.sheets['EFETIVO']
        for i,v in enumerate([1,'Policial Existente',3,'CAPITÃO','BOPE','ATIVO'],1):sheet.grid[(9,i)]=v
        self.batches=[]
    def values_batch_update(self,payload):
        self.batches.append(payload)
        for item in payload['data']:
            a,r=item['range'].split('!',1)
            a=a.strip("'")
            import re
            mm=re.match(r'([A-Z]+)(\d+)(?::[A-Z]+\d+)?$',r)
            col,row=ord(mm.group(1))-64,int(mm.group(2))
            for ir,vs in enumerate(item['values']):
                for ic,val in enumerate(vs):self.sheets[a].grid[(row+ir,col+ic)]=val

p=Planilha.__new__(Planilha)
p.cfg=type('Cfg',(),{'batalhao':'1º Batalhão'})()
p.book=FakeBook();p.lock=threading.RLock();p._cache=p.book.sheets
assert p.consultar(1)['nome']=='Policial Existente'
assert p.resumo()['total']==1
assert 'cadastrado' in p.cadastrar(13,'Novo Soldado','13','SOLDADO','BOPE','Admin')
assert p.book.sheets['EFETIVO'].grid[(10,1)]==13
assert p.book.sheets['EFETIVO'].grid[(10,5)]=='BOPE'
assert p.resumo()['total']==2
assert p.situacao(13,'AFASTADO','Admin')
assert p.promover(13,'CABO','Admin')
assert p.unidade(13,'GRT','Admin')
assert p.curso(13,'APH','Admin')
assert p.advertir(13,'Falha','Advertência',30,'Admin')
assert p.medalha(13,'Mérito','Boa atuação','Admin')
# Nunca se sobrescrevem fórmulas calculadas nestas colunas.
for batch in p.book.batches:
 for v in batch['data']:
  rng=v['range']; aba,ref=rng.split('!',1);aba=aba.strip("'")
  col=ref[0]
  if aba=='REGISTROS':assert col not in 'EG',rng
  if aba=='CURSOS':assert col!='B',rng
  if aba=='MEDALHAS':assert col!='B',rng
  if aba=='ADVERTÊNCIAS':assert col not in 'BCDJ',rng
try:
 p.cadastrar(13,'Duplicado','22','CABO','BOPE','Admin')
 raise AssertionError('ID duplicado deveria falhar')
except ErroNegocio:pass
assert p._faixa('REGISTROS','H50',[['=IMPORTXML(...)']])['values'][0][0].startswith("'")
print('OK - leituras, comandos, logs, preservação de fórmulas, validações e proteção contra fórmulas maliciosas')
