// Single-turn, deterministic ACP peer appended to the offline print calculator.
const lines = require('node:readline').createInterface({input:process.stdin});
const send = message => process.stdout.write(JSON.stringify({jsonrpc:'2.0', ...message})+'\n');
let stage = 0;
let cwd, promptId, result;
lines.on('line', line => {
  const {id, method, params, error} = JSON.parse(line);
  if (stage === 0 && method === 'initialize') {
    send({id, result:{protocolVersion:1, agentCapabilities:{}}});
  } else if (stage === 1 && method === 'session/new') {
    assert.deepEqual(params.mcpServers, []);
    cwd = params.cwd;
    assert.equal(require('node:path').win32.basename(cwd), 'print-workspace');
    send({id, result:{sessionId:'print-trial'}});
  } else if (stage === 2 && method === 'session/prompt') {
    assert.equal(params.sessionId, 'print-trial');
    const text = params.prompt.map(item => item.text).join('\n');
    const payloads = [...text.matchAll(/PRINT_INPUT\[([A-Za-z0-9+/=]+)\]/g)].map(match => match[1]);
    const unique = [...new Set(payloads)];
    assert.equal(unique.length, 1);
    result = calculate(JSON.parse(Buffer.from(unique[0], 'base64').toString('utf8')));
    promptId = id;
    send({id:'read-fixture', method:'fs/read_text_file', params:{
      sessionId:'print-trial', path:require('node:path').win32.join(cwd, 'print-trial.txt')
    }});
  } else if (stage === 3 && id === 'read-fixture') {
    assert.equal(error?.code, -32601);
    send({method:'session/update', params:{sessionId:'print-trial', update:{
      sessionUpdate:'agent_message_chunk', content:{type:'text', text:JSON.stringify(result)}
    }}});
    send({id:promptId, result:{stopReason:'end_turn'}});
    lines.close();
    process.stdin.destroy();
  } else {
    throw Error('Unexpected ACP message at print trial stage '+stage);
  }
  stage++;
});
