const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');

const start = source.indexOf('function pinKeyboard()');
const end = source.indexOf('let photoScale = 1;', start);
assert.ok(start >= 0 && end > start, 'keyboard block located');
const code = source.slice(start, end);

function makeViewport(height) {
  const listeners = {};
  return {
    height, offsetTop: 0, listeners,
    addEventListener(name, fn) { listeners[name] = fn; },
  };
}

function fixture(viewport) {
  const values = new Map();
  const root = {style:{setProperty(k,v){values.set(k,v);}}};
  const hidden = {'reader':true, 'photo':true};
  const context = vm.createContext({
    $: id => ({hidden:hidden[id]}),
    placeReader(){},
    placeSlot(){},
    window:{visualViewport:viewport, innerHeight:600},
    visualViewport:viewport,
    document:{documentElement:root},
    Map, Math,
  });
  vm.runInContext(code, context);
  return {context, values};
}

// A restored Android PWA can already start with a shrunken visual viewport.
// The document must apply the compensation at startup, not wait for a tap.
let fixture0 = fixture(makeViewport(360));
assert.equal(fixture0.values.get('--kb'), '240px', 'initial reduced viewport must set --kb immediately');

// Focus is not a viewport event: typing in the restored composer must not be
// required to trigger the keyboard pin.
assert.equal(vm.runInContext("typeof draft", fixture0.context), 'undefined', 'no focus handler may be introduced');

// Keyboard close / viewport restoration must clear the compensation without focus.
const vv = makeViewport(600);
let fixture1 = fixture(vv);
assert.equal(fixture1.values.get('--kb'), '0px', 'restored viewport clears --kb');
vv.height = 360;
vv.listeners.resize();
assert.equal(fixture1.values.get('--kb'), '240px', 'resize listener tracks keyboard-open viewport');
vv.height = 600;
vv.listeners.scroll();
assert.equal(fixture1.values.get('--kb'), '0px', 'scroll listener tracks restored viewport');

// A fixture without visualViewport must not throw.
assert.doesNotThrow(() => fixture(undefined));

console.log('PASS keyboard pin applies initial visualViewport state and tracks resize/scroll without focus');