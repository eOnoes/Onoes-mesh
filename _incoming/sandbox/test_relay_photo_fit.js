const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app.js', 'utf8');
const code = source.slice(source.indexOf('let photoScale = 1;'), source.indexOf('function closePhoto()'));
for (const [name,w,h] of [['portrait',1080,2340],['landscape',2400,900],['square',1000,1000]]) {
  for (const [vw,vh] of [[368,430],[800,400]]) {
    const stage = {style:{},replaceChildren(node){this.child=node;}};
    const nodes = {'photo-stage':stage,'photo-view':{clientWidth:vw,clientHeight:vh},photo:{hidden:true}};
    const image = {tagName:'IMG',naturalWidth:w,naturalHeight:h,style:{width:'112px',height:'84px',objectFit:'cover'},cloneNode(){return {...this,style:{...this.style}};}};
    const context = vm.createContext({$:id=>nodes[id],closeReader(){},placeSlot(){},Map,Math});
    vm.runInContext(code,context);
    context.image=image;
    vm.runInContext('openPhoto(image)',context);
    assert.equal(stage.child.style.objectFit,'contain', name+' must not crop');
    const sw=parseFloat(stage.style.width), sh=parseFloat(stage.style.height);
    assert.ok(Math.abs(sw/sh-w/h)<0.0001,name+' must retain original ratio');
    const scale=vm.runInContext('photoScale',context);
    assert.ok(sw*scale<=vw+0.01 && sh*scale<=vh+0.01,name+' must fit in viewport');
    vm.runInContext('photoX=30;photoY=40;fitPhoto()',context);
    assert.equal(vm.runInContext('photoX + photoY',context),0);
    console.log(`PASS ${name} fits ${vw}x${vh}, original aspect preserved, reset centers`);
  }
}
