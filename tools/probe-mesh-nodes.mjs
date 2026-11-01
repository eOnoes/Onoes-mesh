import { createNodeProbeReader } from '../lib/node-probes.mjs';

// Fixed one-shot read. No command arguments, destinations, credentials or daemon.
if (process.argv.length !== 2) {
  console.error('Usage: node tools/probe-mesh-nodes.mjs');
  process.exitCode = 2;
} else {
  const snapshot = await createNodeProbeReader().refresh();
  console.log(JSON.stringify(snapshot, null, 2));
  // Known offline is a successful observation. Unavailable observation is exit 1.
  process.exitCode = snapshot.nodes.some(node => node.observationAvailability === 'unavailable') ? 1 : 0;
}
