import ast,hashlib,json,re,subprocess
from pathlib import Path
root=Path.cwd()
source=root/'service_roots/relay'
manifest=(source/'SOURCE.md').read_text(encoding='utf-8')
originals=[]
for p,h in re.findall(r'\| (D:/Dev/Onoes-Relay/[^|]+) \| ([0-9a-f]{64}) \|',manifest):
    actual=hashlib.sha256(Path(p).read_bytes()).hexdigest()
    assert actual==h,p
    originals.append({'path':p,'sha256':actual,'unchanged':True})
assert len(originals)==18
native=(source/'static/index.html').read_text(encoding='utf-8')
original=Path('D:/Dev/Onoes-Relay/static/index.html').read_text(encoding='utf-8')
assert re.findall(r'<style>(.*?)</style>',native,re.S)==re.findall(r'<style>(.*?)</style>',original,re.S)
(root/'test/app03-m4-link-checks/native-script.js').write_text('\n'.join(re.findall(r'<script>(.*?)</script>',native,re.S)),encoding='utf-8')
pyfiles=list(source.glob('*.py'))+[root/'test/m4-link-process-observer.py']
for p in pyfiles:ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
jsfiles=['server.mjs','public/app.js','lib/task-store.mjs','lib/relay-link.mjs','lib/service-connections.mjs','test/m4-link-fixture.mjs','test/m4-link-http.test.mjs','test/m4-link-store.test.mjs','test/m4-link-ui.test.mjs','test/app03-m4-link-checks/native-script.js']
for p in jsfiles:subprocess.run(['node','--check',p],check=True)
tracked=['server.mjs','public/app.js','public/index.html','lib/task-store.mjs','lib/relay-link.mjs','lib/service-connections.mjs']+['test/'+p.name for p in root.glob('test/m4-link*')]+['service_roots/relay/'+str(p.relative_to(source)).replace('\\','/') for p in source.rglob('*') if p.is_file()]
record={'originals':originals,'sourceCssUnchanged':True,'pythonAstCount':len(pyfiles),'javascriptSyntaxCount':len(jsfiles),'currentSha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in tracked},'tests':{'npm':'PASS 30 + 1','focusedM2M3Privacy':'PASS 47','M4':'PASS 5 / FAIL 1 actual dependency gate; no skips'},'actualRelaySuccess':False}
(root/'test/app03-m4-link-checks/current-bytes.json').write_text(json.dumps(record,indent=2))
print('PASS: 18 original input hashes unchanged; native CSS unchanged; Python AST15 and JavaScript syntax10; current bytes recorded')


