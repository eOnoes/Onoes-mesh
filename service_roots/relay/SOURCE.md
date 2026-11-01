# Isolated current Relay inputs

Source root: D:/Dev/Onoes-Relay (read-only; no Git operations). SHA-256 below is of original bytes before minimal Mesh adapter changes. Only runtime imports and existing HTML assets copied; no live config/stores/history or gateway executors.

| Source path | SHA-256 |
| --- | --- |
| D:/Dev/Onoes-Relay/relay_server.py | 82c85562ea6b49e12f8f7dd6edcd67aebff35693b000f81e59a4d21018a57e1b |
| D:/Dev/Onoes-Relay/relay_sessions.py | f045f367735755e3741aa3354c90bb44b91efa0f861bd0c28e4513ddae237dae |
| D:/Dev/Onoes-Relay/relay_db.py | a63e6e7d802a9ee064164eac672b1815e16915365d9f70e0b211c33faaf56d34 |
| D:/Dev/Onoes-Relay/relay_auth.py | b8c221aa67f1253fda9d0586fd5cc48ed32cabe7623017cee1c248b089835361 |
| D:/Dev/Onoes-Relay/relay_channels.py | 80aabdcb0daa73f4cfc4b3f124768e905cadcc2e8dacfb4c0f3c86c05ea21c3c |
| D:/Dev/Onoes-Relay/relay_config.py | 3a605db1c6f45bec13997382b643761c91f5cf718999e5c1807f564c7dd5e150 |
| D:/Dev/Onoes-Relay/relay_hermes.py | 0fd1452a68cf9a7e937b4a4a1636fc5fa46ab196e5b06496720a4f11de5f6dcc |
| D:/Dev/Onoes-Relay/relay_openclaw.py | 71cc0583ff8edc7d4112532385f12d993134f7abccee950e2427776d9c4c5f3f |
| D:/Dev/Onoes-Relay/relay_a2a.py | d3b8ee0ad593a92dc09e8f6721328a42a8fba3f2e262fe5db0ec62ebd1a9a8c2 |
| D:/Dev/Onoes-Relay/relay_notify.py | 434d9f1903167f7338a7997ec1a8d1a2c979ff3fa464ee26afc8f670c59b8800 |
| D:/Dev/Onoes-Relay/relay_webpush.py | 03b8dc63828d580eab21b0ebe524ed3bdedec9b43245346a1b04ad0fbf584003 |
| D:/Dev/Onoes-Relay/relay_mcp.py | fcbea1d9bbd18f667eb7b5b77f064080c48e9b6061fd3d9556798c45b90acaba |
| D:/Dev/Onoes-Relay/requirements.txt | bc4af4615e09e1a7cb0b2430047af1b714600bfcb509cb1f3901b2ee5deeab03 |
| D:/Dev/Onoes-Relay/static/index.html | 3bb0b405a22c2f25e9a83bce9466cef336c9f9cd0e165fea0548695fe96858bd |
| D:/Dev/Onoes-Relay/static/menu.svg | 9e95fef116c3a480d3abc716e0e8e5608c2aa87138a163a3908fbc2f94fc21e2 |
| D:/Dev/Onoes-Relay/static/gear.svg | 135335dc92adb10632c31e2562d3608f8c065d8eb9ce96a1470ebeca5e9ff160 |
| D:/Dev/Onoes-Relay/static/slash-commands.json | 762abbe60522d8159d985aa0cf3d7999e77a9a1377bdad2f7eb25649135eb13f |
| D:/Dev/Onoes-Relay/static/slash-commands-openclaw.json | 0f12190447557c1abf1492433b96031fc537e62552fbeb4980e1d1a749fcb3f5 |

Minimal changes: relay_server.py adds only the Mesh message branch, reference snapshot, and Mesh-only startup guard. mesh_link.py and mesh_runtime.py provide the confined reference bridge/runtime. Existing static/index.html uses the Mesh guard, text-only explicit create intent and volatile browser queue; existing CSS is unchanged. No gateway.mjs or relay-adapter.mjs copied: Mesh-only mode never starts OpenClaw/agent executors. The unused service worker is excluded.
The two original 16px SVG button icons are embedded unchanged in the admitted native HTML; no public image route or styling change is needed. Unused native PWA manifest/icon/service-worker copies are excluded; Mesh retains its existing PWA shell.
