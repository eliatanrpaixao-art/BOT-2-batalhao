"""Testes do fluxo de dados sem conexão ao Discord/Google (python teste_painel_offline.py)."""
import sys, types, threading, unittest
from types import SimpleNamespace
from pathlib import Path

# Dependências externas simuladas APENAS durante testes: não são arquivos do bot.
if 'discord' not in sys.modules:
    mod = types.ModuleType('discord')
    mod.Client = object
    mod.Interaction = object
    mod.Member = object
    mod.app_commands = types.ModuleType('discord.app_commands')
    sys.modules['discord'] = mod
    sys.modules['discord.app_commands'] = mod.app_commands
if 'gspread' not in sys.modules:
    mod = types.ModuleType('gspread')
    mod.WorksheetNotFound = type('WorksheetNotFound', (Exception,), {})
    mod.Worksheet = object
    sys.modules['gspread'] = mod
if 'dotenv' not in sys.modules:
    mod = types.ModuleType('dotenv')
    mod.load_dotenv = lambda *a, **kw: False
    sys.modules['dotenv'] = mod

from bot_core import Planilha, ErroNegocio


class FakeSheet:
    def __init__(self, sheet_id=121, rows=209, parent=None, name='EFETIVO'):
        self.id=sheet_id
        self.row_count=rows
        self.parent=parent
        self.name=name
        self.data={}

    def row_values(self, n):
        if self.name=='EFETIVO':
            if n == 8: return ['ID','NOME NO RP','BADGE','PATENTE','GUARNIÇÃO','SITUAÇÃO','ENTRADA','DISCORD',
                               'ÚLT. PROMOÇÃO','OBSERVAÇÕES','BOPE','GRI','SPEED','GRAER','GTM','GRT','APH','PQD','BC','NIÓBIO','JOALHERIA']
            if n>=9 and n-9<len(self.parent.rows): return self.parent.rows[n-9]
        return []

    def get(self, rg):
        if self.name=='DENÚNCIAS':
            return [self.data.get(i,[]) for i in range(2,max(self.data.keys(),default=1)+1)]
        return []

    def update(self, rg, data, **kwargs):
        if self.name=='DENÚNCIAS':
            import re
            match=re.search(r'A(\d+)',rg)
            self.data[int(match.group(1))]=data[0]

    def freeze(self, **kwargs): pass
    def update_acell(self, ref, value):
        import re
        n=int(re.search(r'\d+',ref).group())
        self.data[n][7]=value


class FakeBook:
    def __init__(self, parent):
        self.parent = parent
        self.requests=[]

    def add_worksheet(self, title, rows, cols):
        sh=FakeSheet(150,rows,self.parent,title)
        self.parent.sheets[title]=sh
        return sh

    def batch_update(self, body):
        self.requests.extend(body['requests'])
        for req in body['requests']:
            if 'updateCells' not in req:
                continue
            u=req['updateCells']
            i=u['range']['startRowIndex']+1
            values=u['rows'][0]['values']
            while len(self.parent.rows)<i-8:
                self.parent.rows.append([])
            row=self.parent.rows[i-9]
            row.extend(['']*max(0,10-len(row)))
            for k,cell in enumerate(values):
                v=cell['userEnteredValue']
                row[k]=str(v.get('stringValue',v.get('numberValue','')))


class FakePlanilha(Planilha):
    def __init__(self, legacy_blank=False, histórico=None):
        self.cfg=SimpleNamespace(unidade_inicial='BOPE',patente_inicial='RECRUTA')
        self.lock=threading.RLock()
        self.rows=[
            ['1','Derick','1','CORONEL','GRT','','','','',''],
            ['2','Rudeus Cliford','2','CORONEL','GRT','','','','',''],
            ['3','Luka','3','CORONEL','GRT','','','','',''],
        ]
        if legacy_blank:
            self.rows.append(['','Legado sem ID','','','','','','','',''])
        self.historico=histórico or []
        self.book=FakeBook(self)
        self.logged=[]
        self.denuncias=[]
        self.sheets={'EFETIVO':FakeSheet(121,209,self,'EFETIVO'),
                     'REGISTROS':FakeSheet(122,259,self,'REGISTROS')}
        self._cache={}

    def aba(self,nome):
        import gspread
        if nome not in self.sheets:
            raise gspread.WorksheetNotFound(nome)
        return self.sheets[nome]

    def _bloco(self,aba,start,end,columns):
        if aba=='EFETIVO': return [list(r) for r in self.rows]
        if aba=='REGISTROS': return [list(r) for r in self.historico]
        raise AssertionError(aba)

    def _registrar(self, *args):
        self.logged.append(args)
        return [{'values':'log'}]

    def _gravar(self, ranges):
        self.logged.append(ranges)


class TestesAutoRegistro(unittest.TestCase):
    def test_badge_crescente_e_textual(self):
        p=FakePlanilha()
        a=p.cadastrar_auto('186','Rodrigo Caveira','123456789012345678','Teste')
        self.assertEqual(a['badge'],'004')
        self.assertEqual(p.rows[3][2],'004')
        self.assertEqual(p.rows[3][0],'186')
        self.assertEqual(p.rows[3][3],'RECRUTA')
        self.assertEqual(p.rows[3][4],'BOPE')
        self.assertEqual(p.rows[3][5],'ATIVO')
        self.assertEqual(p.rows[3][7],'123456789012345678')
        self.assertTrue(p.book.requests)

    def test_mesmo_usuario_bloqueado(self):
        p=FakePlanilha()
        p.cadastrar_auto('186','Rodrigo Caveira','123456789012345678','Teste')
        with self.assertRaisesRegex(ErroNegocio,'já possui cadastro'):
            p.cadastrar_auto('187','Novo Nome','123456789012345678','Teste')

    def test_mesmo_id_bloqueado(self):
        p=FakePlanilha()
        with self.assertRaisesRegex(ErroNegocio,'já está cadastrado'):
            p.cadastrar_auto('001','Novo Nome','555555555555555555','Teste')
        p.cadastrar_auto('186','Rodrigo Caveira','123456789012345678','Teste')
        with self.assertRaisesRegex(ErroNegocio,'já está cadastrado'):
            p.cadastrar_auto('186','Outra Pessoa','987654321987654321','Teste')

    def test_nao_sobrescreve_nome_sem_id(self):
        p=FakePlanilha(legacy_blank=True)
        p.cadastrar_auto('186','Rodrigo Caveira','123456789012345678','Teste')
        self.assertEqual(p.rows[3][1],'Legado sem ID')
        self.assertEqual(p.rows[4][0],'186')

    def test_badges_do_historico_nao_reutilizados(self):
        p=FakePlanilha(histórico=[['','','','','','','','Cadastro: Badge 042']])
        a=p.cadastrar_auto('186','Rodrigo Caveira','123456789012345678','Teste')
        self.assertEqual(a['badge'],'043')

    def test_duas_interacoes_concorrentes(self):
        p=FakePlanilha()
        resultados=[]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as executor:
            futs=[executor.submit(p.cadastrar_auto,str(200+i),f'Jogador {i}',str(20000000000000+i),'Teste') for i in range(5)]
            for f in futs: resultados.append(f.result())
        self.assertEqual(len({v['badge'] for v in resultados}),5)
        self.assertEqual(sorted(int(v['badge']) for v in resultados),[4,5,6,7,8])

    def test_nome_maior_32_caracteres_bloqueado(self):
        p=FakePlanilha()
        with self.assertRaisesRegex(ErroNegocio,'Nome muito longo'):
            p.cadastrar_auto('186','Personagem com Nome Super Comprido','123456789012345678','Teste')

    def test_pesquisa_retorna_campos_e_badge_formatado(self):
        p=FakePlanilha()
        ficha=p.consultar_completo('2')
        self.assertEqual(ficha['NOME NO RP'],'Rudeus Cliford')
        self.assertEqual(ficha['BADGE'],'002')
        self.assertEqual(ficha['GUARNIÇÃO'],'GRT')
        self.assertEqual(len(ficha),21)

    def test_denuncia_pendente_e_envio_marcado(self):
        p=FakePlanilha()
        ficha=p.consultar_completo('2')
        perfil={'id':'123456789012345678','username':'tester', 'display_name':'Teste','avatar_url':'https://example.com/p.png'}
        lin=p.salvar_denuncia(ficha,perfil,'Patente incorreta na ficha')
        self.assertEqual(lin,2)
        self.assertEqual(p.aba('DENÚNCIAS').data[2][7],'PENDENTE')
        self.assertIn('Patente incorreta',p.aba('DENÚNCIAS').data[2][6])
        p.marcar_denuncia_enviada(lin)
        self.assertEqual(p.aba('DENÚNCIAS').data[2][7],'ENVIADA')

    def test_limite_badge(self):
        p=FakePlanilha(histórico=[['','','','','','','','Badge 999']])
        with self.assertRaisesRegex(ErroNegocio,'limite de 999'):
            p.cadastrar_auto('186','Rodrigo Caveira','123456789012345678','Teste')


if __name__=='__main__':
    unittest.main(verbosity=2)
