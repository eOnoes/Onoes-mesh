"""Propose one Mind subpath on Mesh's existing private Tailscale listener.

Pure configuration planning only: no credential, network or service operations.
"""
from copy import deepcopy
import hashlib
import json
import re

MOUNT='/mind-agents/'
LISTEN_PORT='8453'
MESH_PROXY='http://127.0.0.1:4320'
MIND_PROXY='http://127.0.0.1:19124'


class RouteConflict(ValueError):
    pass


def require(ok):
    if not ok:raise RouteConflict('The reviewed private Mind route changed or is already owned')


def fingerprint(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def target(hostname):
    require(type(hostname) is str and re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net',hostname))
    return hostname+':'+LISTEN_PORT


def prepare(before,*,hostname,expected_sha256):
    require(type(before) is dict and fingerprint(before)==expected_sha256)
    key=target(hostname)
    require(before.get('TCP',{}).get(LISTEN_PORT)=={'HTTPS':True}
        and before.get('AllowFunnel',{}).get(key,False) is False)
    handlers=before.get('Web',{}).get(key,{}).get('Handlers')
    require(type(handlers) is dict and handlers.get('/')=={'Proxy':MESH_PROXY})
    for path in handlers:
        require(type(path) is str)
        if path=='/':continue
        stem=path.rstrip('/')
        require(stem!=MOUNT.rstrip('/') and not path.startswith(MOUNT)
            and not MOUNT.startswith(stem+'/'))
    proposed=deepcopy(before)
    proposed['Web'][key]['Handlers'][MOUNT]={'Proxy':MIND_PROXY}
    return proposed


def rollback(current,*,original,proposed,hostname):
    expected=prepare(original,hostname=hostname,expected_sha256=fingerprint(original))
    require(proposed==expected)
    key=target(hostname)
    require(type(current) is dict)
    handlers=current.get('Web',{}).get(key,{}).get('Handlers',{})
    require(handlers.get(MOUNT)=={'Proxy':MIND_PROXY})
    restored=deepcopy(current)
    del restored['Web'][key]['Handlers'][MOUNT]
    return restored


def commands():
    return {
        'add':['tailscale','serve','--bg','--https='+LISTEN_PORT,'--set-path='+MOUNT,MIND_PROXY],
        'remove':['tailscale','serve','--https='+LISTEN_PORT,'--set-path='+MOUNT,'off'],
    }
