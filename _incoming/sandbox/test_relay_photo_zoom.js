const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');

const start = source.indexOf('let photoScale = 1;');
const end = source.indexOf('function closePhoto()', start);
assert.ok(start >= 0 && end > start, 'photo block located');
const code = source.slice(start, end);
assert.equal(code.includes('function closePhoto'), false);

const stage = {style:{}, replaceChildren(node){this.child = node;}};
const view = {clientWidth:368, clientHeight:430};
const nodes = {'photo-stage':stage, photo:{hidden:true}};
const image = {
  tagName:'IMG', naturalWidth:2340, naturalHeight:1080,
  style:{width:'112px', height:'84px', objectFit:'cover'},
  cloneNode(){ return {...this, style:{...this.style}}; },
};
const handlers = {};
const photoView = {
  clientWidth:368, clientHeight:430,
  addEventListener(name, fn){ handlers[name] = fn; },
  setPointerCapture(){},
};
const context = vm.createContext({
  $: id => id === 'photo-view' ? photoView : nodes[id],
  photoView,
  closeReader(){}, placeSlot(){}, Map, Math,
});
const tailStart = source.indexOf('const photoView', end);
const tailEnd = source.indexOf('async function copyDoc()', tailStart);
assert.ok(tailStart > start && tailEnd > tailStart, 'photo handlers located');
vm.runInContext(code + '\n' + source.slice(tailStart, tailEnd), context);
context.image = image;
vm.runInContext('openPhoto(image)', context);

const fit = vm.runInContext('photoFitScale', context);
const fitted = vm.runInContext('photoScale', context);

const started = vm.runInContext('photoScale', context);
handlers.wheel({preventDefault(){}, deltaY: -100});
handlers.wheel({preventDefault(){}, deltaY: -100});
const zoomed = vm.runInContext('photoScale', context);
assert.ok(zoomed > fitted + 0.01, 'a pinch-style zoom-in must move well past the fitted image');
assert.ok(zoomed <= fit * 8 + 0.0001, 'zoom-in remains bounded to eight fitted widths');

let taps = [];
for (let i = 0; i < 4; i++) {
  handlers.pointerdown({pointerId: i + 1, clientX: 100, clientY: 100});
  handlers.pointerup({pointerId: i + 1});
  taps.push(vm.runInContext('photoScale', context));
}
const afterDoubleTaps = vm.runInContext('photoScale', context);
assert.ok(afterDoubleTaps > 1.01, 'double-tap reset must restore a non-floor scale');
const scaleBeforePan = vm.runInContext('photoScale', context);
vm.runInContext("photoPointers.clear(); photoPointers.set(7, {x:0,y:0,sx:0,sy:0});", context);
handlers.pointermove({pointerId: 7, clientX: 4, clientY: 0});
assert.equal(vm.runInContext('photoScale', context), scaleBeforePan, 'a single-pointer move must not change scale');
assert.equal(vm.runInContext('photoX', context), 4, 'a single-pointer move pans the stage');

// One finger must retain its original touch distance so slow moves do not
// become an accidental zoom and repeated moves keep the same gesture start.
const other = {x: 100, y: 100, sx: 100, sy: 100};
vm.runInContext(`photoPointers.clear(); photoPointers.set(1, ${JSON.stringify(other)});`, context);
handlers.pointerdown({pointerId: 2, clientX: 140, clientY: 100});
handlers.pointermove({pointerId: 2, clientX: 144, clientY: 100});
const fittedScale = vm.runInContext('photoScale', context);
const otherAfter = vm.runInContext("photoPointers.get(2)", context);
vm.runInContext(`photoPointers.set(1, ${JSON.stringify({x:otherAfter.x, y:otherAfter.y + 4, sx:100, sy:100})});`, context);
handlers.pointermove({pointerId: 1, clientX: otherAfter.x, clientY: otherAfter.y + 4});
assert.equal(vm.runInContext('photoScale', context), fittedScale, 'a single-pointer move must not change scale');
assert.equal(vm.runInContext('photoPointers.get(1).sx', context), 100, 'the stationary pointer keeps its start coordinates');
assert.equal(vm.runInContext('photoPointers.get(1).sy', context), 100, 'the stationary pointer keeps its start coordinates');
assert.equal(vm.runInContext('photoPointers.size', context), 2, 'the fixture exercises a two-pointer gesture');
console.log('PASS photo zoom is relative to the fitted baseline, bounded to 8x fit, and single-pointer moves preserve pointer start');