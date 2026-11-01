// Real source functions under a small DOM event-bubbling fixture.
// Complements actual private-route desktop/mobile click acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
const start = source.indexOf('function appendPhoto(card, fileId, room) {');
const end = source.indexOf('\nconst photoInput', start);
const outsideStart = source.indexOf("document.addEventListener('click', e => {");
const outsideEnd = source.indexOf('\n});', outsideStart) + 4;
assert(start >= 0 && end > start && outsideStart >= 0 && outsideEnd > outsideStart);
const pane = {hidden: true};
let outsideClick;
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.handlers = {}; }
  setAttribute() {}
  append(...nodes) { this.children.push(...nodes); }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  click() {
    const event = {target: {closest: () => null}, stopped: false, stopPropagation() { this.stopped = true; }};
    this.handlers.click(event);
    if (!event.stopped) outsideClick(event);
  }
}
const context = {
  document: {createElement: tag => new Element(tag), addEventListener: (name, handler) => { outsideClick = handler; }},
  $: id => id === 'photo' ? pane : {hidden: true},
  openPhoto: () => { pane.hidden = false; },
  closePhoto: () => { pane.hidden = true; },
  closeReader: () => {}, encodeURIComponent,
};
vm.createContext(context);
vm.runInContext(source.slice(start,end) + '\n' + source.slice(outsideStart,outsideEnd), context);
const card = new Element('article');
context.appendPhoto(card,'synthetic-file','relay-eddie-echo-test');
card.children[0].click();
assert.equal(pane.hidden,false,'thumbnail must not close its own viewer through click bubbling');
assert.match(card.children[0].children[0].src,/\/api\/relay\/media\/file\?id=/);
outsideClick({target:{closest:()=>null}});
assert.equal(pane.hidden,true,'a separate outside click must still dismiss the viewer');
console.log('PASS photo click stays open; separate outside click closes; byte-serving URL preserved');
