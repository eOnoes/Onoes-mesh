// Synthetic transport fixture: no agent, provider, credentials or model calls.
const http = require('node:http');
const fs = require('node:fs');
const marker = '/opt/data/marker.txt';
if (!fs.existsSync(marker)) fs.writeFileSync(marker, 'fixture-state-must-survive');
const server = http.createServer((req, res) => {
  if (req.headers.authorization !== 'Bearer fixture-key-only') {
    res.writeHead(401, {'content-type': 'application/json'});
    return res.end('{"error":"unauthorized"}');
  }
  if (req.url === '/v1/capabilities') {
    res.writeHead(200, {'content-type': 'application/json'});
    return res.end(JSON.stringify({object: 'hermes.api_server.capabilities',
      platform: 'hermes-agent', features: {run_submission: true, run_status: true,
        run_events_sse: true}, marker: fs.readFileSync(marker, 'utf8')}));
  }
  if (req.url === '/v1/runs/fixture/events') {
    res.writeHead(200, {'content-type': 'text/event-stream', 'cache-control': 'no-store'});
    res.flushHeaders();
    res.write('event: message.delta\ndata: {"delta":"first"}\n\n');
    return setTimeout(() => res.end('event: run.completed\ndata: {"status":"completed"}\n\n'), 60);
  }
  res.writeHead(404); res.end();
});
server.listen(8642, process.env.API_SERVER_HOST || '127.0.0.1', () => console.log('FIXTURE_READY'));
process.on('SIGTERM', () => server.close(() => process.exit(0)));
