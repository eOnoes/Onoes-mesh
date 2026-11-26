# Existing Hermes API: private route candidate

This package prepares two additions to an existing Docker Compose service and
one subpath on its existing private Tailscale HTTPS listener, plus the matching
three-field change to Relay's existing Cyony peer. It has no live
installer and never enrolls an agent, reads credentials or starts a model.

The route reuses the native Hermes Runs API and Relay's existing Hermes client.
It adds `API_SERVER_HOST: 0.0.0.0` **inside the container** and publishes that
container port only on the Docker host's `127.0.0.1`. The proposed Serve mount
is `/relay-native/`; the existing `/` Keep route stays intact. This package
does not enable Funnel, add another gateway or create a second Mind store.

## Guards and rollback

`prepare_compose` requires the reviewed original hash, immutable image and
existing private network/home. It preserves the original bytes and changes only
the two declared fields. The existing legacy `API_SERVER_ENABLED` value is
matched explicitly and retained, even when it is `false`; a running current
gateway can already serve its native API while retaining that flag. No attempt
is made here to reinterpret or change it.

Duplicate keys, aliases, existing publication, network overrides, mismatched
image/source and unexpected API overrides hold preparation. Block and inline
maps retain their original representation. Compose rollback is byte-exact and
holds if somebody edited the proposal afterward.

The Serve proposal requires the reviewed HTTPS listener and Keep handler. It
rejects Funnel and an already-owned Relay mount. Its inverse removes only the
unchanged mount it added, preserving other newly added routes. Actual apply
must recheck the current handler before using the generated path-specific
command; never use `tailscale serve reset` or replace a whole stale config.

`relay_config_candidate` prepares only Cyony's backend, HTTPS URL and new
credential-file reference. It preserves the other agents, budgets and settings,
rejects reuse of the old A2A credential, refuses inline/environment credentials
and requires the new file reference to stay inside the reviewed local `.private`
directory. It neither reads nor creates that key. Relay rollback requires the
exact proposed bytes; a concurrent config edit is retained for review.

## Verification

With PyYAML installed, from this directory:

```text
python -B -m unittest test_route_candidate test_relay_config_candidate -v
```

The optional Docker rehearsal uses an **already present** `node:22-alpine`
image pinned to its local digest. It never pulls an image or runs Hermes. The
synthetic fixture exercises loopback publication, unauthenticated rejection,
authenticated reads, ordered SSE, state preservation across recreation, exact
rollback and cleanup of only its named project. Choose a new disposable output
directory on the development drive:

```text
python -B docker_rehearsal.py --output-directory D:\Scratch\mesh-route-check --flow-style
```

The output records which fixture checks passed. It is not proof of live
Tailscale TLS, real Hermes chat, production backup restoration or Mind access.
The initial source-image probe found that the local custom gateway image has
no Node runtime; the rehearsal therefore uses the existing standard Node image,
with no package/global runtime change.

## Before live use

The operator still needs a reviewed backup/install/rollback package, current
image/Compose/Serve/listener checks, confirmation that this bind setting reaches
the actual gateway, a safe idle window for the single service recreation and a
separately authorized Relay service-credential/configuration handoff. Creating
the route or changing API access is not authorized by a passing preparation
test. Mind enrollment and model chat checks remain separate approvals.

The proposed localhost publication assumes Docker Engine 28 or later and a
normal NAT bridge, not host networking or a routed/unprotected bridge. Confirm
the actual network before activation. Relevant primary references:

- [Docker port publication](https://docs.docker.com/engine/network/port-publishing)
- [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)
- [Installed-version proxy prefix handling](https://github.com/tailscale/tailscale/blob/v1.104.6/ipn/ipnlocal/serve.go)

Live identities, addresses, configuration bytes, credentials and evidence belong
in private deployment records, outside this source package.
