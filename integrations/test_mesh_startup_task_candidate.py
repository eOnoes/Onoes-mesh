"""Hidden launch transport and task draft; no live task registration."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import mesh_startup_task_candidate as task


@unittest.skipUnless(os.name=='nt','Windows WScript transport')
class HiddenTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='mesh-hidden-task-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.root=self.base/'workspace';self.root.mkdir()
        (self.root/'integrations').mkdir();self.private=self.base/'private';self.private.mkdir()
        self.approval=self.private/'startup.json';self.approval.write_bytes(b'{}')
        self.entry=self.root/'integrations/mesh_startup_candidate.py';self.entry.write_text('# synthetic transport only\n')
        self.wrapper=self.private/task.WRAPPER_NAME
        self.approved=dict(workspace=str(self.root),ownerSid='S-1-test',pythonSha256=task.startup.digest(sys.executable),
            sourceHashes={str(self.entry):task.startup.digest(self.entry)})
        self.addCleanup(patch.stopall)
        patch.object(task,'ROOT',self.root).start();patch.object(task.startup,'ROOT',self.root).start()
        self.check=patch.object(task.startup,'checked_startup',return_value=(self.approved,None,None,None)).start()
        self.xml=('''<Task xmlns="'''+task.NS+'''" version="1.2"><RegistrationInfo><URI>'''+task.TASK_URI+'''</URI></RegistrationInfo>
<Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger><TimeTrigger><StartBoundary>2026-11-16T07:00:00</StartBoundary><Repetition><Interval>PT1M</Interval></Repetition></TimeTrigger></Triggers>
<Principals><Principal id="Author"><UserId>S-1-test</UserId><LogonType>InteractiveToken</LogonType></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><Enabled>true</Enabled><ExecutionTimeLimit>PT72H</ExecutionTimeLimit></Settings>
<Actions Context="Author"><Exec><Command>'''+str(Path(os.environ['WINDIR'])/'System32/wscript.exe')+'''</Command><Arguments>//B //Nologo "'''+str(self.root/'integrations/ensure-workroom-hidden.vbs')+'''"</Arguments></Exec></Actions></Task>''').encode()

    def prepare(self,xml=None,**overrides):
        body=self.xml if xml is None else xml
        args=dict(approval_path=str(self.approval),approval_sha=task.sha(b'{}'),task_xml=body,task_sha=task.sha(body),wrapper_path=str(self.wrapper))
        return task.prepare_hidden_task(**{**args,**overrides})

    def test_read_only_draft_changes_only_arguments_and_preserves_all_task_properties(self):
        before=set(self.base.rglob('*'));result=self.prepare()
        self.assertEqual(set(self.base.rglob('*')),before);self.assertTrue(result['createsNothing']);self.assertFalse(result['activationAuthorized'])
        original=ET.fromstring(self.xml);new=ET.fromstring(result['taskBytes']);tag='{'+task.NS+'}'
        args=new.find('.//'+tag+'Arguments');self.assertEqual(args.text,'//B //Nologo "'+str(self.wrapper)+'"')
        args.text=original.find('.//'+tag+'Arguments').text
        self.assertEqual(task.tree_value(new),task.tree_value(original))
        self.assertEqual(task.sha(result['wrapperBytes']),result['wrapperSha256'])
        wrapper=result['wrapperBytes'].decode('utf-16')
        self.assertIn(', 0, True)',wrapper);self.assertIn(' -I ',wrapper)
        self.assertNotIn('cmd.exe',wrapper);self.assertNotIn('powershell',wrapper)
        # Export-ScheduledTask can retain its UTF-16 declaration in a UTF-8 file.
        self.assertTrue(self.prepare(b'<?xml version="1.0" encoding="UTF-16"?>'+self.xml)['createsNothing'])

    def test_task_hash_owner_route_overlap_and_policy_drift_are_refused(self):
        for old,new in [(b'S-1-test',b'S-1-other'),(b'IgnoreNew',b'StopExisting'),
            (b'ensure-workroom-hidden.vbs',b'other.vbs'),(b'<Enabled>true</Enabled>',b'<Enabled>false</Enabled>'),
            (b'LogonTrigger',b'BootTrigger'),(task.TASK_URI.encode(),b'\\Other task')]:
            with self.subTest(new=new):
                self.assertRaises(RuntimeError,self.prepare,self.xml.replace(old,new))
        self.assertRaises(RuntimeError,self.prepare,task_sha='0'*64)
        self.assertRaises(RuntimeError,self.prepare,wrapper_path=str(self.root/task.WRAPPER_NAME))
        self.wrapper.write_bytes(b'Existing private work');self.assertRaises(RuntimeError,self.prepare)
        self.assertEqual(self.wrapper.read_bytes(),b'Existing private work')

    def test_omitted_windows_enabled_default_is_preserved_but_duplicate_is_refused(self):
        tag='{'+task.NS+'}';tree=ET.fromstring(self.xml);settings=tree.find(tag+'Settings')
        settings.remove(settings.find(tag+'Enabled'));body=ET.tostring(tree,encoding='utf-8')
        result=self.prepare(body);readback=ET.fromstring(result['taskBytes'])
        self.assertIsNone(readback.find(tag+'Settings/'+tag+'Enabled'))
        settings.append(ET.Element(tag+'Enabled'));settings[-1].text='true'
        settings.append(ET.Element(tag+'Enabled'));settings[-1].text='false'
        self.assertRaises(RuntimeError,self.prepare,ET.tostring(tree,encoding='utf-8'))

    def test_duplicate_actions_principals_and_xml_entities_are_refused(self):
        for old,new in [(b'</Actions>',b'<Exec><Command>other</Command></Exec></Actions>'),
            (b'</Principals>',b'<Principal id="Other"/></Principals>'),
            (b'</Task>',b'<Actions/></Task>')]:
            self.assertRaises(RuntimeError,self.prepare,self.xml.replace(old,new))
        self.assertRaises(RuntimeError,self.prepare,b'<!DOCTYPE Task [<!ENTITY x "unsafe">]>'+self.xml)
        self.assertRaises(RuntimeError,self.prepare,b' '*(65537))

    def test_source_approval_failure_is_not_replaced_by_a_legacy_route(self):
        self.check.side_effect=RuntimeError('Synthetic refusal')
        self.assertRaises(RuntimeError,self.prepare);self.assertFalse(self.wrapper.exists())
        self.check.side_effect=None;self.approved['sourceHashes'][str(self.entry)]='0'*64
        self.assertRaises(RuntimeError,self.prepare)

    def test_expansion_quotes_and_control_characters_cannot_enter_run_command(self):
        for value in ('C:/temp/%USERPROFILE%/file','C:/temp/"quoted"','C:/temp/line\nnext'):
            self.assertRaises(RuntimeError,task.ordinary_path,value)

    def run_hidden_transport(self,code):
        marker=self.private/('worker-'+str(code)+'.json')
        self.entry.write_text('import ctypes,json,os,sys\nfrom pathlib import Path\n'
            +'ctypes.windll.kernel32.GetConsoleWindow.restype=ctypes.c_void_p\n'
            +'ctypes.windll.user32.IsWindowVisible.argtypes=[ctypes.c_void_p]\n'
            +'window=ctypes.windll.kernel32.GetConsoleWindow()\n'
            +'Path('+repr(str(marker))+').write_text(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd(),consoleVisible=bool(window and ctypes.windll.user32.IsWindowVisible(window)))))\n'
            +'raise SystemExit('+str(code)+')\n',encoding='utf-8')
        self.approved['sourceHashes'][str(self.entry)]=task.startup.digest(self.entry)
        result=self.prepare();self.wrapper.write_bytes(result['wrapperBytes'])
        child=subprocess.Popen([str(Path(os.environ['WINDIR'])/'System32/wscript.exe'),'//B','//Nologo',str(self.wrapper)],
            creationflags=subprocess.CREATE_NO_WINDOW)
        while True:
            try:exit_code=child.wait(timeout=30);break
            except subprocess.TimeoutExpired:print('Observing original hidden test process '+str(child.pid),flush=True)
        self.assertEqual(exit_code,code)
        value=json.loads(marker.read_text());self.assertEqual(value['cwd'],str(self.root))
        self.assertEqual(value['argv'],['--approval',str(self.approval),'--sha256',task.sha(b'{}')])
        self.assertFalse(value['consoleVisible'])

    def test_real_hidden_wscript_transports_exact_argv_workdir_and_success(self):
        self.run_hidden_transport(0)

    def test_real_hidden_wscript_preserves_worker_failure_exit(self):
        self.run_hidden_transport(7)

    def test_real_hidden_wscript_supports_unicode_and_ampersand_paths(self):
        self.private=self.base/'private & caf\u00e9';self.private.mkdir()
        self.approval=self.private/'startup.json';self.approval.write_bytes(b'{}')
        self.wrapper=self.private/task.WRAPPER_NAME
        self.run_hidden_transport(0)


if __name__=='__main__':unittest.main()
