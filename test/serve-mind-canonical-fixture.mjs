// Actual Mesh + actual canonical Python reader, synthetic in-memory records only.
import {startApp} from '../server.mjs';import {canonicalMindFixture} from './mind-canonical-fixture.mjs';import {randomUUID} from 'node:crypto';
process.env.MESH_STANDALONE='1';const fixture=await canonicalMindFixture(process.env.MESH_MIND_SOURCE);
const app=await startApp({dataDir:'data/mind-view-'+randomUUID(),mindRecallTestOptions:{source:'disposable_fixture',baseUrl:fixture.baseUrl,token:fixture.token}});
console.log(JSON.stringify({url:app.url+'/#mind',meshPid:process.pid,ownedPythonPid:fixture.pid,scope:'SYNTHETIC MEMORY ONLY - no real agents, models or memory'}));
let stopping=false;async function stop(){if(stopping)return;stopping=true;await app.close();await fixture.close();process.stdin.pause();console.log('Owned Mesh and Python fixtures closed.');}
process.stdin.on('data',b=>{if(String(b).trim()==='stop')void stop();});process.on('SIGINT',()=>void stop());process.on('SIGTERM',()=>void stop());
