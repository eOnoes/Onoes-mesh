import test from 'node:test';
import assert from 'node:assert/strict';
import {captureBoardView,restoreBoardView} from '../public/workroom-view.mjs';
function fixture(){
  const document={activeElement:null};
  const lane=(key,top)=>({dataset:{workroomStage:key},stack:{scrollTop:top,clientTop:0,clientHeight:200,getBoundingClientRect(){return {top:100,bottom:300};}},querySelector(){return this.stack;}});
  const card=(id,key='ready',bounds={top:110,bottom:190})=>({dataset:{taskId:id},closest(){return board.lanes.find(lane=>lane.dataset.workroomStage===key);},getBoundingClientRect(){return {...bounds,height:bounds.bottom-bounds.top};},focus(options){this.focusOptions=options;document.activeElement=this;}});
  const board={scrollLeft:42,lanes:[lane('ready',230),lane('working',170),lane('done',0)],cards:[card('task-one'),card('task-two')],
    contains(node){return this.cards.includes(node);},querySelectorAll(selector){return selector==='[data-workroom-stage]'?this.lanes:this.cards;}};
  return {document,board,lane,card};
}
test('board redraw preserves each lane position and focuses the replacement card without scrolling',()=>{
  const {document,board,lane,card}=fixture();document.activeElement=board.cards[0];
  const saved=captureBoardView(board,document);
  board.cards=[card('task-two'),card('task-one')];board.lanes=[lane('working',0),lane('done',0),lane('ready',0)];board.scrollLeft=0;
  restoreBoardView(board,saved);
  assert.equal(document.activeElement,board.cards[1]);assert.deepEqual(board.cards[1].focusOptions,{preventScroll:true});
  assert.deepEqual(board.lanes.map(item=>item.stack.scrollTop),[170,0,230]);assert.equal(board.scrollLeft,42);
});
test('filter or other outside controls keep focus through board refresh',()=>{
  const {document,board,card}=fixture();const outside={};document.activeElement=outside;
  const saved=captureBoardView(board,document);board.cards=[card('task-one')];restoreBoardView(board,saved);
  assert.equal(document.activeElement,outside);
});
test('removed task or lane is harmless and new lanes keep their own default position',()=>{
  const {document,board,lane}=fixture();document.activeElement=board.cards[0];const saved=captureBoardView(board,document);
  board.cards=[];board.lanes=[lane('new',9)];document.activeElement=null;
  assert.doesNotThrow(()=>restoreBoardView(board,saved));assert.equal(document.activeElement,null);assert.equal(board.lanes[0].stack.scrollTop,9);
});

for(const [name,bounds,expected] of [
  ['above the viewport',{top:50,bottom:130},120],
  ['below the viewport',{top:350,bottom:430},300],
  ['already visible',{top:110,bottom:190},170],
  ['taller than the viewport',{top:80,bottom:380},150]
])test('moved focused card '+name+' is revealed by adjusting only its destination column',()=>{
  const {document,board,card}=fixture();document.activeElement=board.cards[0];
  const saved=captureBoardView(board,document);board.cards=[card('task-one','working',bounds)];
  restoreBoardView(board,saved);
  assert.equal(board.lanes.find(l=>l.dataset.workroomStage==='working').stack.scrollTop,expected);
  assert.equal(board.lanes.find(l=>l.dataset.workroomStage==='ready').stack.scrollTop,230);
  assert.equal(board.lanes.find(l=>l.dataset.workroomStage==='done').stack.scrollTop,0);
  assert.equal(board.scrollLeft,42);assert.equal(document.activeElement,board.cards[0]);
});
test('refresh keeps a focused but scrolled-away card out of view when it did not move lanes',()=>{
  const {document,board,card}=fixture();document.activeElement=board.cards[0];
  const saved=captureBoardView(board,document);board.cards=[card('task-one','ready',{top:-200,bottom:-120})];
  restoreBoardView(board,saved);
  assert.equal(board.lanes.find(l=>l.dataset.workroomStage==='ready').stack.scrollTop,230);
});
