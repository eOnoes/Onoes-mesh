import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../public/app.js', import.meta.url), 'utf8');
const agentSource = await readFile(new URL('../public/agent-workspace.mjs', import.meta.url), 'utf8');
const mindSource = await readFile(new URL('../public/mind-workspace.mjs', import.meta.url), 'utf8');
const relayCoreSource = await readFile(new URL('../public/relay-conversation.mjs', import.meta.url), 'utf8');
const relayChatSource = await readFile(new URL('../public/chat.mjs', import.meta.url), 'utf8');
const html = await readFile(new URL('../public/index.html', import.meta.url), 'utf8');
class Element {
  constructor() { this.children = []; this.attrs = {}; this.events = {}; this.textContent = ''; this.value = ''; this.disabled = false; this.style = {}; this.dataset={};this.scrollHeight=0;this.clientHeight=0;this.scrollTop=0;this.classList={add(){},remove(){},contains(){return false;}}; }
  get firstChild() { return this.children[0]; }
  setAttribute(k, v) { this.attrs[k] = v; } getAttribute(k) { return this.attrs[k]; }
  addEventListener(k, f) { this.events[k] = f; } append(...els) { this.children.push(...els); }
  replaceChildren(...els) { this.children = els; } reset() {} focus() {}
  querySelectorAll() { return []; }
  getBoundingClientRect() {return {height:0,width:0,top:0,right:0,left:0,bottom:0};}
}
function mockUI({ stored, responder, locked=false, hash='', DateImpl=Date } = {}) {
  const ids = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(m => [m[1], new Element()]));
  const forms = ['create-title','create-description','create-label','edit-title','edit-description','edit-label','toggle-status','reload-task','refresh'].map(id => ids.get(id));
  const tabs = [...html.matchAll(/<button role="tab" id="([^"]+)" aria-controls="([^"]+)"/g)].map(m => { const el = ids.get(m[1]); el.attrs['aria-controls'] = m[2]; return el; });
  const groups = new Map(['.activity-workers','.activity-state, .activity-source','.service-connections','.service-status','.inference-state','.inference-errors','.activity-source','.activity-state'].map(s => [s, [new Element()]]));
  const storage = new Map(stored ? [['mesh.synthetic-demo.proof.v1', JSON.stringify(stored)]] : []);
  if(locked)storage.set('mesh.workspace.locked.v1','1');
  const requests = []; const events = {}; const intervals = [];
  const context = vm.createContext({requestAnimationFrame:()=>{},MutationObserver:class{observe(){}},crypto:globalThis.crypto,TextEncoder,document: { getElementById: id => ['chat-grip','chat-seek','chat-jump'].includes(id)?null:ids.get(id), createElement: () => new Element(),createDocumentFragment:()=>new Element(), querySelectorAll: s => s === '[role=tab]' ? tabs : s.startsWith('form ') ? forms : groups.get(s) ?? [] }, navigator: { onLine: true }, window: { location:{hash}, addEventListener: (e, f) => { events[e] = f; } }, sessionStorage: { getItem: k => storage.get(k)??null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) }, AbortController, setTimeout, clearTimeout, setInterval: f => { intervals.push(f); }, Date:DateImpl, fetch: async (route, options) => { requests.push({ route, options }); return responder ? responder(route, options) : response(200, {}); } });
  const modules=[agentSource,mindSource,relayCoreSource,relayChatSource,source].map(s=>s.replace(/^import .*;\r?$/gm,'').replace(/^export /gm,''));
  vm.runInContext(modules.join('\n'), context);
  return { ids, forms, tabs, storage, requests, events, intervals, context };
}
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, text: async () => JSON.stringify(body) });
const flush = async () => { for (let i = 0; i < 10; i++) await new Promise(r => setImmediate(r)); };
function bodyFor(route) {
  if (route === '/api/tasks') return { tasks: [] };
  if (route === '/api/health') return { state: 'ok', persistence: 'sqlite', activity: { source: 'none' } };
  if (route === '/api/worker-activity') return {state:'not_configured',workers:[]};
  if (route === '/api/commands') return {commands:[]};
  return {};
}

export {source,html,mockUI,response,flush,bodyFor};
