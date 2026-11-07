import ast, asyncio, types, unittest
from pathlib import Path

class SessionBinding(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, expected, *, existing=None):
        source=(Path(__file__).parents[1]/'integrations/relay_server_candidate.py').read_text(encoding='utf-8')
        function=next(node for node in ast.parse(source).body if isinstance(node,ast.AsyncFunctionDef) and node.name=='message')
        function.decorator_list=[]
        response=lambda body,status_code=200: (status_code,body)
        store=types.SimpleNamespace(outbox_get=lambda ident:existing)
        agent=types.SimpleNamespace(conversation_id='current',backend='hermes')
        namespace={'AGENTS':{'echo':agent},'SESSIONS':store,'MESSAGE_LOCKS':{'echo':asyncio.Lock()},
                   'Request':object,'JSONResponse':response,'_parse_attachments':lambda value:[]}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),'candidate-message','exec'),namespace)
        class Request:
            async def json(self): return {'id':'message-id','text':'bounded task','expectedConversationId':expected}
        return await namespace['message']('echo',Request())

    async def test_changed_conversation_is_rejected_before_dispatch(self):
        status,_=await self.invoke('old');self.assertEqual(status,409)

    async def test_accepted_retry_reconciles_even_after_active_session_changes(self):
        status,body=await self.invoke('old',existing={'agent_id':'echo','session_id':'old','content':'bounded task'})
        self.assertEqual(status,200);self.assertTrue(body['duplicate'])

    async def test_reused_id_with_different_task_payload_is_rejected(self):
        status,_=await self.invoke('old',existing={'agent_id':'echo','session_id':'old','content':'different work'})
        self.assertEqual(status,409)

if __name__=='__main__':unittest.main()
