// Fetch the actual served browser entry points and their literal module imports.
// No evaluation, credentials, model calls or third-party asset requests.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
export async function verifyBrowserAssets(origin,{fetchImpl=fetch}={}){
  const base=new URL(origin);assert.equal(base.hostname,'127.0.0.1');
  const pending=[{url:new URL('/',base),kind:'html'}],seen=new Set(),assets=[];
  const add=(specifier,parent,kind)=>{
    assert.ok(specifier.startsWith('/')||specifier.startsWith('./')||specifier.startsWith('../'),'Browser asset must use an explicit local path: '+specifier);
    const url=new URL(specifier,parent);assert.equal(url.origin,base.origin,'External browser assets are outside this release gate');
    assert.ok(!url.username&&!url.password,'Asset credentials forbidden');url.hash='';pending.push({url,kind});
  };
  while(pending.length){
    const {url,kind}=pending.shift();if(seen.has(url.href))continue;seen.add(url.href);assert.ok(seen.size<=128,'Browser asset graph exceeded bound');
    const response=await fetchImpl(url.href,{redirect:'manual',signal:AbortSignal.timeout(3000)});
    assert.equal(response.status,200,'Browser asset unavailable: '+url.pathname);
    const mime=response.headers.get('content-type')?.split(';')[0].trim();
    assert.ok((kind==='js'?['text/javascript','application/javascript']:kind==='css'?['text/css']:['text/html']).includes(mime),'Wrong browser asset MIME: '+url.pathname);
    const text=await response.text();assert.ok(Buffer.byteLength(text)<=1024*1024,'Oversized browser asset: '+url.pathname);assets.push(url.pathname);
    if(kind==='html'){
      for(const match of text.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi))add(match[1],url,'js');
      for(const match of text.matchAll(/<link\b[^>]*>/gi)){
        if(!/\brel=["']stylesheet["']/i.test(match[0]))continue;
        const href=match[0].match(/\bhref=["']([^"']+)["']/i);assert.ok(href,'Stylesheet href missing');add(href[1],url,'css');
      }
    }else if(kind==='js'){
      const syntax=spawnSync(process.execPath,['--input-type=module','--check'],{input:text,encoding:'utf8',windowsHide:true,timeout:2000,maxBuffer:65536});
      assert.equal(syntax.status,0,'Invalid served JavaScript: '+url.pathname+' '+(syntax.stderr||''));
      for(const match of text.matchAll(/\b(?:import|export)\s+(?:[^;'"`]*?\bfrom\s*)?(["'])([^"'\r\n]+)\1/g))add(match[2],url,'js');
      const dynamic=[...text.matchAll(/\bimport\s*\(\s*(["'])([^"'\r\n]+)\1\s*\)/g)];
      assert.equal([...text.matchAll(/\bimport\s*\(/g)].length,dynamic.length,'Computed imports need explicit served-asset coverage: '+url.pathname);
      for(const match of dynamic)add(match[2],url,'js');
    }
  }
  return assets;
}
