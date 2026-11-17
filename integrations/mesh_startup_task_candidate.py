"""Render an inactive hidden launch and exact task-action draft; never install."""
import copy
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

import mesh_startup_candidate as startup

ROOT=Path(__file__).resolve().parents[1]
NS='http://schemas.microsoft.com/windows/2004/02/mit/task'
TASK_URI='\\ONOes Mesh Workroom Recovery'
WRAPPER_NAME='mesh-capture-first-hidden.vbs'


def require(ok):
    if not ok:raise RuntimeError('Hidden startup draft refused; existing task unchanged.')


def sha(body):return hashlib.sha256(body).hexdigest()


def ordinary_path(value):
    path=Path(value)
    # WScript.Shell expands percent-delimited environment names in Run strings.
    require(not any(ch=='%' or ch=='"' or ord(ch)<32 for ch in str(path)))
    require(path.is_absolute() and path.resolve()==path)
    return path


def hidden_wrapper(python,entry,approval,approval_sha,workspace):
    paths=[ordinary_path(p) for p in (python,entry,approval,workspace)]
    require(re.fullmatch('[a-f0-9]{64}',approval_sha or ''))
    command=subprocess.list2cmdline([str(paths[0]),'-I',str(paths[1]),
        '--approval',str(paths[2]),'--sha256',approval_sha])
    literal=lambda value:'"'+str(value).replace('"','""')+'"'
    body=('Option Explicit\r\nDim shell, result\r\n'
        'Set shell = CreateObject("WScript.Shell")\r\n'
        'shell.CurrentDirectory = '+literal(paths[3])+'\r\n'
        'result = shell.Run('+literal(command)+', 0, True)\r\n'
        'WScript.Quit result\r\n')
    return body.encode('utf-16')


def tree_value(node):
    return (node.tag,tuple(sorted(node.attrib.items())),(node.text or '').strip(),
        tuple(tree_value(child) for child in node))


def prepare_hidden_task(*,approval_path,approval_sha,task_xml,task_sha,wrapper_path):
    """Return bytes for review. No filesystem write, task API or process start."""
    require(os.name=='nt' and startup.ROOT==ROOT and type(task_xml) is bytes
        and len(task_xml)<=65536 and sha(task_xml)==task_sha)
    task_text=task_xml.decode('utf-16' if task_xml.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig')
    require('<!DOCTYPE' not in task_text.upper() and '<!ENTITY' not in task_text.upper())
    approval_path=ordinary_path(approval_path);wrapper=ordinary_path(wrapper_path)
    approved,_,_,_=startup.checked_startup(str(approval_path),approval_sha)
    require(approved['workspace']==str(ROOT) and approved['pythonSha256']==startup.digest(sys.executable)
        and wrapper.name==WRAPPER_NAME and wrapper.parent==approval_path.parent
        and wrapper.parent.is_dir() and not os.path.lexists(wrapper)
        and not wrapper.parent.is_relative_to(ROOT) and not ROOT.is_relative_to(wrapper.parent))
    original=ET.fromstring(task_text);tag=lambda name:'{'+NS+'}'+name
    find=lambda path:original.find('/'.join(tag(name) for name in path.split('/')))
    require(original.tag==tag('Task'))
    for name in ('RegistrationInfo','Settings','Principals','Triggers','Actions'):
        require(len(original.findall(tag(name)))==1)
    uri=find('RegistrationInfo/URI');settings=find('Settings');principals=find('Principals')
    require(uri is not None and uri.text==TASK_URI and settings is not None
        and principals is not None and len(principals)==1)
    user=principals[0].find(tag('UserId'));policy=settings.find(tag('MultipleInstancesPolicy'))
    enabled=settings.find(tag('Enabled'));triggers=find('Triggers');actions=find('Actions')
    # Task Scheduler settingsType.Enabled is optional and defaults to true.
    # Preserve an omitted default rather than adding a new task setting.
    require(len(settings.findall(tag('Enabled')))<=1)
    require(user is not None and user.text==approved['ownerSid'] and policy is not None
        and policy.text=='IgnoreNew' and (enabled is None or enabled.text=='true')
        and triggers is not None and len(triggers)==2
        and {child.tag for child in triggers}=={tag('LogonTrigger'),tag('TimeTrigger')}
        and actions is not None and len(actions)==1 and actions[0].tag==tag('Exec'))
    execution=actions[0];command=execution.find(tag('Command'));arguments=execution.find(tag('Arguments'))
    wscript=ordinary_path(Path(os.environ['WINDIR'])/'System32/wscript.exe')
    require(command is not None and ordinary_path(command.text)==wscript and wscript.is_file()
        and arguments is not None and arguments.text=='//B //Nologo "'+str(ROOT/'integrations/ensure-workroom-hidden.vbs')+'"')
    entry=ordinary_path(ROOT/'integrations/mesh_startup_candidate.py')
    require(approved['sourceHashes'].get(str(entry))==startup.digest(entry))
    body=hidden_wrapper(sys.executable,entry,approval_path,approval_sha,ROOT)
    changed=copy.deepcopy(original);new_args=changed.find('.//'+tag('Actions')+'/'+tag('Exec')+'/'+tag('Arguments'))
    new_args.text='//B //Nologo "'+str(wrapper)+'"'
    ET.register_namespace('',NS)
    changed_bytes=ET.tostring(changed,encoding='utf-8',xml_declaration=True)
    readback=ET.fromstring(changed_bytes);readback.find('.//'+tag('Actions')+'/'+tag('Exec')+'/'+tag('Arguments')).text=arguments.text
    require(tree_value(readback)==tree_value(original))
    return dict(schema='onoes-mesh-hidden-startup-draft/v1',createsNothing=True,
        activationAuthorized=False,memoryAuthorization='not_revalidated',
        originalTaskSha256=task_sha,taskSha256=sha(changed_bytes),
        wrapperPath=str(wrapper),wrapperSha256=sha(body),
        approvalPath=str(approval_path),approvalSha256=approval_sha,
        generatorSha256=startup.digest(__file__),wrapperBytes=body,taskBytes=changed_bytes)
