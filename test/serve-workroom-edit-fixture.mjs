// Actual task UI/API on a disposable store; no agents or model services.
import {startApp} from '../server.mjs';
import {randomUUID} from 'node:crypto';
process.env.MESH_STANDALONE='1';
const app=await startApp({dataDir:'data/edit-recovery-fixture-'+randomUUID(),relayEnabled:false});
console.log(JSON.stringify({url:app.url+'/#workroom',pid:process.pid,scope:'DISPOSABLE TASK EDIT ACCEPTANCE ONLY; no agent or model service'}));
let stopping=false;
async function stop(){if(stopping)return;stopping=true;clearTimeout(deadline);await app.close();process.stdin.pause();console.log('Owned edit-recovery fixture closed.');}
const deadline=setTimeout(()=>void stop(),10*60*1000);
process.stdin.on('data',b=>{if(String(b).trim()==='stop')void stop();});
process.on('SIGINT',()=>void stop());process.on('SIGTERM',()=>void stop());
