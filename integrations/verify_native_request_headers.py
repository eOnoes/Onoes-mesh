"""Read-only installed-header regression checks; synthetic tokens, no provider calls."""
import json
from pathlib import Path
import sys
import tempfile

NATIVE = Path('C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent')
sys.path.insert(0, str(NATIVE))
from hermes_cli import version_info as version
from agent.codex_headers import codex_cloudflare_headers


def verify():
    saved = version._run_git, version._resolve_stamp_file, version._cached_version_info
    def refuse_git(*args, **kwargs):
        raise AssertionError('Request-header construction launched Git')
    try:
        version._cached_version_info = None
        version._run_git = refuse_git
        assert version.get_request_version() == '0.23.0'
        official = codex_cloudflare_headers('synthetic-not-a-credential')
        assert official['User-Agent'] == 'HermesAgent/0.23.0'
        assert official['originator'] == 'hermes-agent'
        custom = codex_cloudflare_headers('synthetic-not-a-credential', base_url='http://127.0.0.1:9999')
        assert custom == {'User-Agent': 'codex_cli_rs/0.0.0 (Hermes Agent)', 'originator': 'codex_cli_rs'}
        with tempfile.TemporaryDirectory() as folder:
            stamp = Path(folder) / 'install-stamp.json'
            (Path(folder) / '.git').mkdir()
            stamp.write_text(json.dumps({'commit': 'a' * 40, 'source': 'git',
                'baseVersion': '9.8.7', 'updateMechanism': next(iter(version.UPDATE_MECHANISMS))}))
            version._resolve_stamp_file = lambda: stamp
            assert version.get_request_version() == '9.8.7'
            try:
                version._stamp_version_info()
            except AssertionError:
                pass
            else:
                raise AssertionError('Canonical Git freshness check was removed')
            stamp.write_text('{}')
            assert version.get_request_version() == 'unknown'
            version._cached_version_info = version.VersionInfo('7.6.5', '7.6.5', None, None, None, 'unknown')
            assert version.get_request_version() == '7.6.5'
        return {'checksPassed': 8, 'providerCalls': 0, 'credentialsRead': False,
                'requestHeadersSpawnGit': False, 'canonicalFreshnessCheckRetained': True}
    finally:
        version._run_git, version._resolve_stamp_file, version._cached_version_info = saved


if __name__ == '__main__':
    print(json.dumps(verify()))
