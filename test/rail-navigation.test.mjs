import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../public/rail.mjs',import.meta.url),'utf8');
function navigation(mobile,withPicker=false){
  const node=()=>({dataset:{},hidden:true,attrs:{},events:{},style:{},value:'',children:[],textContent:'',setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},append(...v){this.children.push(...v);},replaceChildren(...v){this.children=v;},querySelectorAll(){return this.buttons||[];},querySelector(){return null;},contains(n){return n===this||this.children.includes(n);},addEventListener(k,f,capture=false){(this.events[k]??=[]).push({f,capture:!!capture});},click(){for(const h of [...(this.events.click||[])].sort((a,b)=>Number(b.capture)-Number(a.capture)))h.f({stopPropagation(){},target:this});}});
  const shell=node(),menu=node(),scrim=node(),draft=node();draft.value='unsaved card draft';
  const elements=new Map([['rail-menu',menu],['sheet-scrim',scrim],['relay-chat-agent',node()],['draft',draft]]);
  const picker=node(),panel=node(),machine=node(),item=node(),control=node();item.textContent="Echo's PC";item.setAttribute('aria-pressed','true');machine.buttons=[item];control.setAttribute('aria-selected','true');
  if(withPicker)for(const [id,value] of [['picker',picker],['picker-panel',panel],['picker-label',node()],['machine-tabs',machine],['tab-control',control]])elements.set(id,value);
  const handlers={},media={matches:mobile,events:[],addEventListener(name,fn){assert.equal(name,'change');this.events.push(fn);}},body={dataset:{}};
  const window={location:{hash:'#workroom'},matchMedia:q=>{assert.equal(q,'(max-width: 759px)');return media;}};
  let network=0;const context=vm.createContext({window,document:{body,getElementById:id=>elements.get(id)||null,querySelector:s=>s==='.shell'?shell:null,createElement:()=>node(),createTextNode:text=>({textContent:text}),addEventListener:(name,fn)=>{(handlers[name]??=[]).push(fn);}},MutationObserver:class{observe(){}},fetch:()=>{network++;throw Error('No network needed for navigation');},setTimeout:fn=>fn()});
  vm.runInContext(source,context);
  return {shell,menu,scrim,draft,body,window,picker,panel,setMobile(value){media.matches=value;for(const fn of media.events)fn({matches:value});},escape(){for(const fn of handlers.keydown||[])fn({key:'Escape'});},checkPreserved(){assert.equal(draft.value,'unsaved card draft');assert.equal(window.location.hash,'#workroom');assert.equal(network,0);}};
}
test('phone menu announcement matches its sheet through open, scrim close and Escape',()=>{
  const n=navigation(true);assert.equal(n.menu.attrs['aria-expanded'],'false');assert.equal(n.scrim.hidden,true);
  n.menu.click();assert.equal(n.body.dataset.sheet,'nav');assert.equal(n.menu.attrs['aria-expanded'],'true');assert.equal(n.scrim.hidden,false);
  n.scrim.click();assert.equal(n.body.dataset.sheet,undefined);assert.equal(n.menu.attrs['aria-expanded'],'false');assert.equal(n.scrim.hidden,true);
  n.menu.click();n.escape();assert.equal(n.menu.attrs['aria-expanded'],'false');assert.equal(n.scrim.hidden,true);n.checkPreserved();
});
test('breakpoint changes clear transient sheets and keep desktop rail behavior without changing drafts or workspace',()=>{
  const n=navigation(false);assert.equal(n.menu.attrs['aria-expanded'],'true');n.menu.click();assert.equal(n.shell.dataset.rail,'none');assert.equal(n.menu.attrs['aria-expanded'],'false');n.menu.click();
  n.setMobile(true);assert.equal(n.menu.attrs['aria-expanded'],'false');assert.equal(n.scrim.hidden,true);
  n.menu.click();assert.equal(n.menu.attrs['aria-expanded'],'true');assert.equal(n.body.dataset.sheet,'nav');
  n.setMobile(false);assert.equal(n.body.dataset.sheet,undefined);assert.equal(n.scrim.hidden,true);assert.equal(n.menu.attrs['aria-expanded'],'true');
  n.setMobile(true);assert.equal(n.menu.attrs['aria-expanded'],'false');n.checkPreserved();
});

test('mobile picker uses one handler and switching sheets never leaves both open',()=>{
  const n=navigation(true,true);n.picker.click();assert.equal(n.body.dataset.sheet,'picker');assert.equal(n.panel.hidden,false);assert.equal(n.picker.attrs['aria-expanded'],'true');assert.equal(n.menu.attrs['aria-expanded'],'false');
  n.menu.click();assert.equal(n.body.dataset.sheet,'nav');assert.equal(n.panel.hidden,true);assert.equal(n.picker.attrs['aria-expanded'],'false');assert.equal(n.menu.attrs['aria-expanded'],'true');
  n.escape();n.picker.click();n.picker.click();assert.equal(n.body.dataset.sheet,undefined);assert.equal(n.panel.hidden,true);assert.equal(n.scrim.hidden,true);
  n.setMobile(false);n.picker.click();assert.equal(n.panel.hidden,false);assert.equal(n.body.dataset.sheet,undefined);n.picker.click();assert.equal(n.panel.hidden,true);n.checkPreserved();
});
