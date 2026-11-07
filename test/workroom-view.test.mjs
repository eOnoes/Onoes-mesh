import test from 'node:test';
import assert from 'node:assert/strict';
import {captureBoardView,restoreBoardView} from '../public/workroom-view.mjs';
function fixture(){
  const document={activeElement:null};
  const lane=(key,top)=>({dataset:{workroomStage:key},stack:{scrollTop:top},querySelector(){return this.stack;}});
  const card=id=>({dataset:{taskId:id},focus(options){this.focusOptions=options;document.activeElement=this;}});
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
