import test from 'node:test';import assert from 'node:assert/strict';import http from 'node:http';
import {verifyBrowserAssets} from './browser-assets.mjs';
for(const mode of ['missing','wrong-mime','external'])test('served browser gate rejects '+mode+' module before release',async()=>{
 const requests=[];const server=http.createServer((req,res)=>{
  requests.push(req.url);
  if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html'});return res.end('<script type="module" src="/app.js"></script>');}
  if(req.url==='/app.js'){res.writeHead(200,{'Content-Type':'text/javascript'});return res.end(mode==='external'?"import 'https://example.invalid/private.js';":"import './missing.mjs';");}
  res.writeHead(mode==='missing'?404:200,{'Content-Type':'text/html'});res.end('not a module');
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{await assert.rejects(verifyBrowserAssets('http://127.0.0.1:'+server.address().port),mode==='missing'?/asset unavailable/:mode==='wrong-mime'?/Wrong browser asset MIME/:/explicit local path|External browser/);assert.ok(requests.every(route=>route==='/'||route==='/app.js'||route==='/missing.mjs'));}
 finally{await new Promise(resolve=>server.close(resolve));}
});
