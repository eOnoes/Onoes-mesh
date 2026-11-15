import ast,pathlib,copy,json,unittest,hashlib
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
SOURCE=pathlib.Path('D:/Dev/Onoes-Relay/relay_server.py')
FIELDS={'id','name','backend','device','status','conversation_id','approval','budget'}
class Agent:
 def __init__(self,ident,**extra):self.data={'id':ident,'name':ident.title(),'backend':'fixture','device':'pc','status':'idle','conversation_id':'conversation-'+ident,'approval':None,'budget':None,**extra};self.calls=0
 def snapshot(self):self.calls+=1;return copy.deepcopy(self.data)
def load(path,namespace):
 source=path.read_text(encoding='utf-8-sig');tree=ast.parse(source);node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='list_agents'));node.decorator_list=[]
 exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),namespace)
 return namespace['list_agents']
class DirectoryTests(unittest.TestCase):
 def setUp(self):
  self.agents={x:Agent(x,msgs=[{'t':'synthetic-history'*30000}],feed=['synthetic-feed']) for x in ['echo','cyony','tripp','dsh']}
  self.ns={'AGENTS':self.agents,'JSONResponse':JSONResponse,'_native_openclaw':lambda a:None,'_decorate_native_snapshot':lambda a,s:s}
  self.handler=load(SOURCE,self.ns);app=FastAPI();app.get('/api/agents')(self.handler);self.client=TestClient(app)
 def test_directory_strips_history_without_truncating_agents(self):
  response=self.client.get('/api/agents?view=directory');self.assertEqual(response.status_code,200);rows=response.json();self.assertEqual([x['id'] for x in rows],list(self.agents));self.assertLess(len(response.content),65536)
  self.assertTrue(all(set(x)==FIELDS for x in rows));self.assertNotIn('synthetic-history',response.text)
 def test_full_default_preserves_original_response(self):
  expected=JSONResponse([agent.snapshot() for agent in self.agents.values()])
  self.assertEqual(self.handler().body,expected.body);self.assertEqual(self.client.get('/api/agents?view=full').content,self.client.get('/api/agents').content)
 def test_invalid_view_refuses_before_snapshot(self):
  self.assertEqual(self.client.get('/api/agents?view=unexpected').status_code,400);self.assertTrue(all(a.calls==0 for a in self.agents.values()))
 def test_count_limit_fails_without_partial_list(self):
  self.agents.clear();self.agents.update({str(i):Agent(str(i)) for i in range(129)});self.assertEqual(self.client.get('/api/agents?view=directory').status_code,503)
 def test_metadata_byte_limit_fails_without_silent_clipping(self):
  self.agents['echo'].data['approval']={'question':'x'*70000};self.assertEqual(self.client.get('/api/agents?view=directory').status_code,503)
 def test_approval_and_budget_metadata_preserved(self):
  self.agents['echo'].data.update(approval={'id':'fixture-request'},budget={'remaining':3});row=self.client.get('/api/agents?view=directory').json()[0];self.assertEqual(row['approval'],{'id':'fixture-request'});self.assertEqual(row['budget'],{'remaining':3})
 def test_native_cached_and_connecting_branches(self):
  class Adapter:pass
  cached=Adapter();cached.snapshot=Agent('echo',msgs=['private cached']).snapshot();waiting=Adapter();waiting.snapshot=None
  self.ns['_native_openclaw']=lambda a:cached if a.data['id']=='echo' else waiting if a.data['id']=='tripp' else None
  rows={r['id']:r for r in self.client.get('/api/agents?view=directory').json()};self.assertEqual(rows['tripp']['status'],'waiting');self.assertNotIn('msgs',rows['echo'])
 def test_unlisted_fields_do_not_escape_projection(self):
  self.agents['echo'].data.update(unlisted_secret='synthetic sentinel',connection='details');body=self.client.get('/api/agents?view=directory').text;self.assertNotIn('synthetic sentinel',body);self.assertNotIn('connection',body)
 def test_existing_get_route_remains_declared(self):
  tree=ast.parse(SOURCE.read_text(encoding='utf-8-sig'));node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='list_agents')
  self.assertTrue(any(isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='get' and x.args and isinstance(x.args[0],ast.Constant) and x.args[0].value=='/api/agents' for x in node.decorator_list))
if __name__=='__main__':unittest.main(verbosity=2)
