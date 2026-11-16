"""Compose explicitly approved sharing input; never provision or start a service."""
import json
import importlib.util
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import subprocess


class ProjectMeshInputError(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise ProjectMeshInputError('Approved project input unavailable; preserve state.')


def node_source_identity(profile, database):
    """Compare Node's representation, not Python's distinct Windows volume ID."""
    executable = Path(profile['nodeExecutable'])
    require(executable.is_absolute() and executable.resolve(strict=True) == executable
        and hashlib.sha256(executable.read_bytes()).hexdigest() == profile['nodeSha256'])
    script = """import {statSync,realpathSync} from 'node:fs';
const p=process.argv[1],s=statSync(p,{bigint:true});
if(!s.isFile()||realpathSync(p)!==p)process.exit(1);
console.log(JSON.stringify({fileDevice:String(s.dev),fileInode:String(s.ino)}));"""
    env = {k:v for k,v in os.environ.items() if k.upper() not in ('NODE_OPTIONS','NODE_PATH')}
    result = subprocess.run([str(executable),'--input-type=module','-e',script,str(database)],
        cwd=profile['workspace'],env=env,capture_output=True,text=True,timeout=10,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    require(result.returncode == 0 and len(result.stdout.encode('utf-8')) <= 256)
    value = json.loads(result.stdout)
    require(type(value) is dict and set(value) == {'fileDevice','fileInode'}
        and all(type(v) is str and re.fullmatch(r'(0|[1-9][0-9]{0,19})',v) for v in value.values()))
    return value


def project_native_options(profile, profile_sha):
    selected = profile['projectSync']
    require(type(selected) is dict and set(selected) == {
        'serviceProfile', 'serviceProfileSha256', 'approvalPath', 'source', 'links'})
    for name in ('project_service_process_candidate', 'recall_process_candidate'):
        spec = importlib.util.find_spec(name)
        require(spec is not None and spec.origin is not None and Path(spec.origin).resolve() ==
            Path(__file__).resolve().parent/(name+'.py'))
    import project_service_process_candidate as service
    import recall_process_candidate as roles
    p, base, binding = service.checked_profile(selected['serviceProfile'],
        selected['serviceProfileSha256'], selected['approvalPath'])
    approval = roles.plain_json(selected['approvalPath'])
    require(profile_sha in approval['profiles'] and 'run_mesh_sync' in approval['actions'])
    require(Path(selected['serviceProfile']).parent == Path(selected['approvalPath']).parent)
    source = selected['source']
    require(type(source) is dict and set(source) == {'databasePath', 'fileDevice', 'fileInode'})
    database = Path(source['databasePath'])
    expected = Path(profile['workspace']) / profile['settings']['MESH_DATA_DIR'] / 'tasks.sqlite'
    require(database.is_absolute() and database.resolve(strict=True) == database
        and expected == database and expected.resolve(strict=True) == database and database.is_file())
    before = database.stat()
    require(all(type(source[n]) is str and re.fullmatch(r'(0|[1-9][0-9]{0,19})', source[n])
        for n in ('fileDevice', 'fileInode')))
    require(node_source_identity(profile,database) == {n:source[n] for n in ('fileDevice','fileInode')})
    links = selected['links']
    require(type(links) is list and 1 <= len(links) <= 32)
    allowed_projects = {project[0] for project in base['projects']}
    seen = set()
    for link in links:
        require(type(link) is dict and set(link) == {'cardId', 'projectId', 'approvalRef', 'fields'})
        require(all(type(link[n]) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', link[n])
            for n in ('cardId', 'projectId')) and link['cardId'] not in seen
            and link['projectId'] in allowed_projects)
        seen.add(link['cardId'])
        ref = link['approvalRef']
        require(type(ref) is str and ref.strip() == ref and 1 <= len(ref) <= 300
            and not re.search(r'[\x00-\x1f\x7f]', ref))
        fields = link['fields']
        require(type(fields) is list and all(type(f) is str for f in fields)
            and len(fields) == len(set(fields)) and {'title', 'stage'}.issubset(fields)
            and set(fields).issubset({'title', 'goal', 'owner', 'stage', 'result', 'blocker'}))
    # The read-only preflight must refuse policy drift before the owner launcher
    # stops Mesh. The Node constructor repeats these checks against its own DB.
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        rows = db.execute('SELECT cardId,projectId,storeId,approvalRef FROM mind_project_links ORDER BY cardId').fetchall()
        policies = db.execute('SELECT cardId,fields FROM mind_project_capture_policy').fetchall()
        require(len(rows) == len(links) == len(policies))
        selected_by_card = {link['cardId']: link for link in links}
        policy_by_card = dict(policies)
        for card, project, store, ref in rows:
            link = selected_by_card.get(card)
            require(link is not None and project == link['projectId'] and store == binding.store_id
                and ref == link['approvalRef'] and card in policy_by_card)
            actual = json.loads(policy_by_card[card])
            require(type(actual) is list and all(type(f) is str for f in actual)
                and len(actual) == len(set(actual)) == len(link['fields']) and set(actual) == set(link['fields']))
        db.execute('COMMIT'); require(db.total_changes == 0)
    finally:
        db.close()
    after = database.stat()
    require(database.resolve(strict=True) == database and (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino))
    exported = service.native_options(selected['serviceProfile'], selected['serviceProfileSha256'], selected['approvalPath'])
    require(exported['schema'] == 'onoes-mind-project-client-input/v1')
    value = dict(schema='onoes-mesh-native-project-sync/v2', source=source, links=links,
        destination={**exported['destination'], 'peer': exported['peer']})
    require(len(json.dumps(value).encode('utf-8')) <= 12288)
    return value
