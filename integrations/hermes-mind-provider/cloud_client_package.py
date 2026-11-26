"""Prepare and materialize an inactive Cyony client; never enroll or select it.

Only public SDK/plugin/dependency files and credential-free profiles belong in
this package. Credentials, the intent key and the Hermes config are separate
owner-approved steps. Native MCP and system packages are left unchanged.
"""
from dataclasses import dataclass,field
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import subprocess
import sys
import sysconfig
from types import MappingProxyType
from urllib.parse import urlsplit
import venv
import zipfile

TOOL='mcp__onoes_mind_mesh__read_project_context'
ROOT='onoes-mind'
SDK=ROOT+'/sdk-4a7c3e3'
CLIENT=ROOT+'/cyony'
PLUGIN='plugins/onoes_mind'
NATIVE_SUFFIXES={'.pyc','.pyo','.pyd','.so','.dll','.dylib','.exe'}


class PackageConflict(ValueError):pass


def require(ok):
    if not ok:raise PackageConflict('Inactive client package, interpreter or destination changed')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def relative(name):
    require(type(name) is str and name and name.isascii() and '\\' not in name)
    path=PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and str(path)==name
        and '__pycache__' not in path.parts and path.suffix not in NATIVE_SUFFIXES)
    return path


def absolute(name):
    require(type(name) is str and re.fullmatch(r'/[A-Za-z0-9_./+-]+',name))
    path=PurePosixPath(name)
    require(path.is_absolute() and '..' not in path.parts and str(path)==name and str(path)!='/')
    return path


def endpoint(value):
    require(type(value) is str and value.isascii())
    parsed=urlsplit(value)
    require(parsed.scheme=='https' and parsed.hostname
        and re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net',parsed.hostname)
        and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        and (parsed.port is None or 1<=parsed.port<=65535)
        and (parsed.path in ('','/') or re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+/?',parsed.path)))
    authority=parsed.hostname+(':'+str(parsed.port) if parsed.port is not None else '')
    require(value=='https://'+authority+parsed.path)
    return value.rstrip('/')


@dataclass(frozen=True)
class ClientPackage:
    home:str
    python_resolved:str
    python_sha256:str
    native_purelib:str
    files:object=field(repr=False)
    manifest_sha256:str
    metadata:object=field(repr=False)

    def descriptor(self):
        return {**self.metadata,'manifestSha256':self.manifest_sha256,'files':len(self.files),
            'payloadBytes':sum(len(v) for v in self.files.values()),'activated':False,
            'credentialsCreated':False,'configChanged':False}


def build_package(*,home,base_url,home_binding_sha256,context_binding_sha256,principal_id,project_id,
                  python_resolved,python_sha256,native_purelib,sdk_files,plugin_files,mcp_files,settings_files):
    home_path=absolute(home);python=absolute(python_resolved);purelib=absolute(native_purelib)
    base_url=endpoint(base_url)
    require(all(type(v) is str and re.fullmatch('[0-9a-f]{64}',v)
        for v in (home_binding_sha256,context_binding_sha256,python_sha256)))
    require(type(principal_id) is str and re.fullmatch(r'context-cyony(?:-[a-z0-9_-]{1,40})?',principal_id)
        and type(project_id) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',project_id))
    require(not python.is_relative_to(home_path) and not purelib.is_relative_to(home_path))
    payload={}
    for prefix,source in [(SDK,sdk_files),(PLUGIN,plugin_files),
            (CLIENT+'/vendor/mcp-1.26.0',mcp_files),(CLIENT+'/vendor/pydantic-settings-2.13.1',settings_files)]:
        require(type(source) is dict and source)
        for name,raw in source.items():
            path=relative(name);require(type(raw) is bytes and len(raw)<=2*1024*1024)
            if prefix==SDK:
                require(name.startswith('onoes_mind/') or name=='scripts/remote_project_stdio.py')
                require(path.suffix in ('.py','.ps1','.mjs','.sql'))
            if prefix==PLUGIN:require(len(path.parts)==1 and path.suffix=='.py')
            target=prefix+'/'+name;require(target not in payload);payload[target]=raw
    require('onoes_mind/__init__.py' in sdk_files and 'scripts/remote_project_stdio.py' in sdk_files
        and all(name in plugin_files for name in ('__init__.py','portable.py','config.py','portable_profile.py','journal.py')))
    require(b'Version: 1.26.0' in mcp_files.get('mcp-1.26.0.dist-info/METADATA',b'').splitlines()
        and 'mcp/__init__.py' in mcp_files)
    require(b'Version: 2.13.1' in settings_files.get('pydantic_settings-2.13.1.dist-info/METADATA',b'').splitlines()
        and 'pydantic_settings/__init__.py' in settings_files)
    sdk=home_path/SDK;client=home_path/CLIENT
    core={name:sha(raw) for name,raw in sdk_files.items() if name.startswith('onoes_mind/')}
    home_profile={'schema':'onoes-mind-hermes-provider/posix-v1','hermes_home':home,'agent_id':'cyony',
        'mind_source':str(sdk),'source_hashes':core,'home_binding_sha256':home_binding_sha256,
        'credential_file':str(client/'custody/home.json'),'intent_key_file':str(client/'custody/intent.key'),
        'journal_directory':str(client/'intents'),'home_endpoint':base_url,'review_ref':'owner-cyony-private-home-20261126',
        'max_context_bytes':8192,'shared_project_tool':TOOL}
    source_pins={str(sdk/name):sha(raw) for name,raw in sdk_files.items()}
    source_pins[str(python)]=python_sha256
    reader_profile={'schema':'onoes-mind/remote-project-mcp/v1','mind_source':str(sdk),
        'source_hashes':source_pins,'endpoint':base_url,'principal_id':principal_id,'project_id':project_id,
        'scope_id':'project/onoes-mind/shared','binding_sha256':context_binding_sha256,
        'credential_file':str(client/'custody/context.json'),'review_ref':'owner-cyony-shared-mesh-20261126'}
    payload[CLIENT+'/review/home-profile.json']=encoded(home_profile)
    payload[CLIENT+'/review/shared-reader.json']=encoded(reader_profile)
    require(len(payload)<=2000 and sum(map(len,payload.values()))<=32*1024*1024)
    manifest={name:{'sha256':sha(raw),'bytes':len(raw)} for name,raw in sorted(payload.items())}
    metadata={'schema':'onoes-inactive-cloud-client-package/v1','home':home,'agentId':'cyony',
        'sdkRoot':str(sdk),
        'readerPrincipal':principal_id,'sharedProject':project_id,'endpoint':base_url,
        'homeProfile':str(client/'review/home-profile.json'),'homeProfileSha256':sha(encoded(home_profile)),
        'readerProfile':str(client/'review/shared-reader.json'),'readerProfileSha256':sha(encoded(reader_profile)),
        'readerPython':str(client/'reader-runtime/bin/python'),'readerEntry':str(sdk/'scripts/remote_project_stdio.py'),
        'nativeMcpChanged':False,'readerMcp':'1.26.0','intentKeyCreated':False}
    return ClientPackage(home,str(python),python_sha256,str(purelib),MappingProxyType(payload),sha(encoded(manifest)),MappingProxyType(metadata))


def verify_package(package):
    require(isinstance(package,ClientPackage))
    require(package.metadata['home']==package.home)
    for name,raw in package.files.items():
        relative(name)
        allowed=(SDK+'/',PLUGIN+'/',CLIENT+'/vendor/mcp-1.26.0/',CLIENT+'/vendor/pydantic-settings-2.13.1/')
        require(type(raw) is bytes and (name.startswith(allowed)
            or name in (CLIENT+'/review/home-profile.json',CLIENT+'/review/shared-reader.json')))
    manifest={name:{'sha256':sha(raw),'bytes':len(raw)} for name,raw in sorted(package.files.items())}
    require(sha(encoded(manifest))==package.manifest_sha256)


def write_bundle(package,path):
    """Create a self-contained public-code bundle; never includes custody files."""
    verify_package(package);path=Path(path);require(not path.exists())
    code=Path(__file__).read_bytes()
    record={'schema':'onoes-offline-cloud-client-bundle/v1','home':package.home,
        'pythonResolved':package.python_resolved,'pythonSha256':package.python_sha256,
        'nativePurelib':package.native_purelib,'packageMetadata':dict(package.metadata),
        'manifestSha256':package.manifest_sha256,
        'payload':{n:{'sha256':sha(raw),'bytes':len(raw)} for n,raw in package.files.items()},
        'operatorCodeSha256':sha(code)}
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in package.files.items():archive.writestr('payload/'+name,raw)
        archive.writestr('operator/cloud_client_package.py',code)
        archive.writestr('MANIFEST.json',encoded(record))
    verified=load_bundle(path,sha(path.read_bytes()))
    require(verified.descriptor()==package.descriptor())
    return {'path':str(path),'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size,
        'payloadFiles':len(package.files),'credentialsIncluded':False,'activated':False}


def load_bundle(path,expected_sha256):
    """Verify the independently reviewed outer fingerprint before parsing bytes."""
    path=Path(path);require(path.is_file() and path.stat().st_size<=64*1024*1024)
    raw=path.read_bytes();require(sha(raw)==expected_sha256)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        require(len(names)<=2002 and len(names)==len(set(names)) and sum(i.file_size for i in infos)<=40*1024*1024)
        record=json.loads(archive.read('MANIFEST.json'))
        require(record['schema']=='onoes-offline-cloud-client-bundle/v1')
        require(set(names)=={'payload/'+n for n in record['payload']}|{'MANIFEST.json','operator/cloud_client_package.py'})
        require(sha(archive.read('operator/cloud_client_package.py'))==record['operatorCodeSha256'])
        files={}
        for name,pin in record['payload'].items():
            relative(name);value=archive.read('payload/'+name)
            require(len(value)==pin['bytes'] and sha(value)==pin['sha256']);files[name]=value
    package=ClientPackage(record['home'],record['pythonResolved'],record['pythonSha256'],record['nativePurelib'],
        MappingProxyType(files),record['manifestSha256'],MappingProxyType(record['packageMetadata']))
    verify_package(package);return package


def materialize(package):
    """Owner installer primitive: new private code only, before credentials/config."""
    verify_package(package);require(os.name=='posix')
    home=Path(package.home);binary=Path(sys.executable).resolve(strict=True)
    require(home.is_dir() and home.resolve(strict=True)==home and home.stat().st_uid==os.getuid()
        and str(binary)==package.python_resolved and sha(binary.read_bytes())==package.python_sha256
        and sysconfig.get_path('purelib')==package.native_purelib)
    require(not (home/ROOT).exists() and not (home/PLUGIN).exists())
    parent=home/'plugins'
    require(not parent.exists() or (parent.is_dir() and not parent.is_symlink() and parent.stat().st_uid==os.getuid()))
    def directory(path):
        require(path.is_relative_to(home) and path.resolve()==path)
        if path.exists():
            require(path.is_dir() and not path.is_symlink() and path.stat().st_uid==os.getuid());return
        directory(path.parent);path.mkdir(mode=0o700)
    for name in (ROOT,PLUGIN,CLIENT+'/custody',CLIENT+'/intents',CLIENT+'/review'):
        directory(home/name)
    for name,raw in package.files.items():
        path=home/name;directory(path.parent)
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
        require(path.read_bytes()==raw)
    runtime=home/CLIENT/'reader-runtime'
    venv.EnvBuilder(with_pip=False,symlinks=True).create(runtime)
    site=runtime/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    pth=site/'onoes-reader-dependencies.pth'
    paths=[str(home/CLIENT/'vendor/mcp-1.26.0'),str(home/CLIENT/'vendor/pydantic-settings-2.13.1'),package.native_purelib]
    raw=('import sys; sys.path[0:0]='+repr(paths)+'\n').encode()
    fd=os.open(pth,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw)
    child=subprocess.run([str(runtime/'bin/python'),'-I','-B','-c',
        "import importlib.metadata as m,json,mcp;print(json.dumps({'mcp':m.version('mcp'),'source':mcp.__file__}))"],
        capture_output=True,text=True,timeout=15)
    require(child.returncode==0);observed=json.loads(child.stdout)
    require(observed['mcp']=='1.26.0' and Path(observed['source']).is_relative_to(home/CLIENT/'vendor/mcp-1.26.0'))
    return {**package.descriptor(),'codeInstalled':True,'readerVersion':observed['mcp'],
        'bootstrapPthSha256':sha(raw),'nativeMcpChanged':False,'credentialsCreated':False,'configChanged':False}
