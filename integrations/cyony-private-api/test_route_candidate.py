from copy import deepcopy
from hashlib import sha256
import unittest
import yaml

from route_candidate import (MOUNT, RouteHold, document, prepare_compose, prepare_serve,
                             restore_compose, restore_serve, serve_commands)

IMAGE = 'example/hermes@sha256:' + 'a' * 64
BASE = ('''# Preserve this operator comment.
services:
  hermes:
    image: %s
    restart: unless-stopped
    environment:
      HERMES_HOME: /opt/data
      API_SERVER_ENABLED: 'true'
      HERMES_UID: '1000'
    volumes:
      - /srv/cyony/data:/opt/data
      - /srv/cyony/workspaces:/workspace
    networks:
      - cyony_private
  unrelated:
    image: sample/keep
    command: ['leave', 'alone']
networks:
  cyony_private:
    driver: bridge
''' % IMAGE).encode()
HOST = 'cloud.example.ts.net'
SERVE = {'TCP': {'443': {'HTTPS': True}}, 'Web': {HOST + ':443': {
    'Handlers': {'/': {'Proxy': 'http://127.0.0.1:3000'}, '/other/': {'Proxy': 'http://127.0.0.1:9100'}}}},
    'AllowFunnel': {}}


def prepare(raw=BASE, **kwargs):
    return prepare_compose(raw, expected_sha256=sha256(raw).hexdigest(), expected_image=IMAGE, **kwargs)


class RouteTests(unittest.TestCase):
    def test_exact_addition_retains_original_and_unrelated_service(self):
        result = prepare()
        self.assertIn(b'# Preserve this operator comment.', result)
        before, after = document(BASE)[1], document(result)[1]
        self.assertEqual(before['services']['unrelated'], after['services']['unrelated'])
        self.assertEqual(after['services']['hermes']['ports'], ['127.0.0.1:8642:8642'])
        self.assertEqual(after['services']['hermes']['environment']['API_SERVER_HOST'], '0.0.0.0')
        self.assertEqual(restore_compose(result, original=BASE, proposed=result), BASE)

    def test_stale_source_rejected(self):
        with self.assertRaises(RouteHold):
            prepare_compose(BASE + b'# concurrent\n', expected_sha256=sha256(BASE).hexdigest(), expected_image=IMAGE)

    def test_preexisting_port_not_repurposed(self):
        with self.assertRaises(RouteHold):
            prepare(BASE.replace(b'    restart:', b'    ports: ["0.0.0.0:8642:8642"]\n    restart:'))

    def test_image_change_rejected(self):
        with self.assertRaises(RouteHold):
            prepare(BASE.replace(IMAGE.encode(), IMAGE.replace('a' * 64, 'b' * 64).encode()))

    def test_secret_or_binding_override_rejected(self):
        for field in (b'API_SERVER_KEY: other', b'API_SERVER_HOST: 127.0.0.1'):
            with self.subTest(field=field), self.assertRaises(RouteHold):
                prepare(BASE.replace(b'      HERMES_UID:', b'      ' + field + b'\n      HERMES_UID:'))

    def test_duplicate_or_alias_rejected(self):
        for raw in (BASE.replace(b'    restart:', b'    image: second\n    restart:'),
                    BASE.replace(b'  unrelated:\n', b'  alias: &alias {value: 1}\n  reused: *alias\n  unrelated:\n')):
            with self.subTest(raw=raw), self.assertRaises(RouteHold):
                prepare(raw)

    def test_network_override_rejected(self):
        with self.assertRaises(RouteHold):
            prepare(BASE.replace(b'    restart:', b'    network_mode: host\n    restart:'))

    def test_reviewed_false_legacy_flag_preserved(self):
        raw = BASE.replace(b"API_SERVER_ENABLED: 'true'", b"API_SERVER_ENABLED: 'false'")
        proposed = prepare(raw, expected_api_enabled='false')
        self.assertEqual(document(proposed)[1]['services']['hermes']['environment']['API_SERVER_ENABLED'], 'false')
        with self.assertRaises(RouteHold):
            prepare(raw)

    def test_actual_flow_style_and_false_flag_preserved(self):
        old = b"    environment:\n      HERMES_HOME: /opt/data\n      API_SERVER_ENABLED: 'true'\n      HERMES_UID: '1000'\n"
        for trailing in (b'', b','):
            flow = b"    environment: {HERMES_HOME: /opt/data, API_SERVER_ENABLED: 'false', HERMES_UID: '1000'" + trailing + b"}\n"
            raw = BASE.replace(old, flow)
            proposed = prepare(raw, expected_api_enabled='false')
            before, after = document(raw)[1], document(proposed)[1]
            expected = dict(before['services']['hermes']['environment'], API_SERVER_HOST='0.0.0.0')
            self.assertEqual(after['services']['hermes']['environment'], expected)
            self.assertEqual(restore_compose(proposed, original=raw, proposed=proposed), raw)

    def test_flow_service_and_whole_flow_document(self):
        data = document(BASE)[1]
        data['services']['hermes']['environment']['API_SERVER_ENABLED'] = 'false'
        raw = yaml.safe_dump(data, default_flow_style=True, sort_keys=False).encode()
        proposed = prepare(raw, expected_api_enabled='false')
        after = document(proposed)[1]
        self.assertEqual(after['services']['hermes']['ports'], ['127.0.0.1:8642:8642'])
        self.assertEqual(after['services']['unrelated'], data['services']['unrelated'])
        self.assertEqual(restore_compose(proposed, original=raw, proposed=proposed), raw)

    def test_compose_rollback_preserves_concurrent_edits(self):
        proposed = prepare()
        with self.assertRaises(RouteHold):
            restore_compose(proposed + b'# newer operator edit\n', original=BASE, proposed=proposed)

    def test_serve_preserves_keep_other_paths_and_input(self):
        before = deepcopy(SERVE)
        after = prepare_serve(before, hostname=HOST)
        self.assertEqual(before, SERVE)
        restored = restore_serve(after, original=before, proposed=after, hostname=HOST)
        self.assertEqual(restored, before)
        self.assertEqual(after['Web'][HOST + ':443']['Handlers']['/'], before['Web'][HOST + ':443']['Handlers']['/'])

    def test_funnel_and_existing_mount_rejected(self):
        public = deepcopy(SERVE); public['AllowFunnel'][HOST + ':443'] = True
        occupied = deepcopy(SERVE); occupied['Web'][HOST + ':443']['Handlers'][MOUNT.rstrip('/')] = {'Text': 'owned'}
        for value in (public, occupied):
            with self.subTest(value=value), self.assertRaises(RouteHold):
                prepare_serve(value, hostname=HOST)

    def test_serve_rollback_removes_only_our_unchanged_mount(self):
        proposed = prepare_serve(SERVE, hostname=HOST)
        current = deepcopy(proposed)
        current['Web'][HOST + ':443']['Handlers']['/new/'] = {'Text': 'newer operator path'}
        restored = restore_serve(current, original=SERVE, proposed=proposed, hostname=HOST)
        self.assertNotIn(MOUNT, restored['Web'][HOST + ':443']['Handlers'])
        self.assertEqual(restored['Web'][HOST + ':443']['Handlers']['/new/'], {'Text': 'newer operator path'})
        current['Web'][HOST + ':443']['Handlers'][MOUNT] = {'Proxy': 'http://127.0.0.1:9999'}
        with self.assertRaises(RouteHold):
            restore_serve(current, original=SERVE, proposed=proposed, hostname=HOST)

    def test_no_global_serve_reset_or_arbitrary_target(self):
        commands = serve_commands()
        self.assertNotIn('reset', commands['remove'])
        self.assertIn('--set-path=' + MOUNT, commands['remove'])
        self.assertEqual(commands['add'][-1], 'http://127.0.0.1:8642')


if __name__ == '__main__':
    unittest.main(verbosity=2)
