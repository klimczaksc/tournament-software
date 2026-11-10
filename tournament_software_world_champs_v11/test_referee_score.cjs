const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const code=fs.readFileSync(__dirname+'/static/referee-score.js','utf8');
const tick=()=>new Promise(r=>setImmediate(r));
async function setup(t){
 const dom=new JSDOM(`<div id="referee-app" data-state-url="/state" data-action-url="/action"><span id="ref-connection"></span><div id="ref-rules"></div><div id="ref-sets"></div><button class="point-tile" data-side="0"><span class="ref-name"></span><span id="ref-p0"></span></button><button class="point-tile" data-side="1"><span class="ref-name"></span><span id="ref-p1"></span></button><button id="ref-undo"></button><button id="ref-finish"></button></div>`,{url:'https://tournament.test/referee/1',runScripts:'outside-only',pretendToBeVisual:true});
 t.after(()=>dom.window.close());const w=dom.window;
 let server={revision:0,current:[0,0],sets:[],players:['A','B'],best_of:3,points_to:15,started:false,finalized:false,awaiting_confirmation:false,winner_id:null};
 const writes=[];let mode='ok',poll;
 w.setInterval=fn=>{poll=fn;};w.confirm=()=>true;
 w.fetch=async(url,opts)=>{
  if(url==='/state')return {ok:true,json:async()=>structuredClone(server)};
  const payload=JSON.parse(opts.body);writes.push(payload);
  if(mode==='conflict'){server.revision++;server.current=[2,1];return {ok:false,status:409};}
  server.revision++;server.current[payload.side||0]++;
  if(payload.action==='finish'){server.finalized=true;server.winner_id=1;}
  if(mode==='lost')throw new Error('Connection lost after saving');
  return {ok:true,json:async()=>structuredClone(server)};
 };
 w.eval(code);await tick();
 return {w,writes,poll:()=>poll(),mode:x=>mode=x,server};
}
test('Only one request is sent for two rapid tile clicks',async t=>{
 const {w,writes}=await setup(t);const tile=w.document.querySelector('[data-side="0"]');tile.click();tile.click();await tick();
 assert.equal(writes.length,1);assert.equal(writes[0].revision,0);assert.equal(writes[0].side,0);
 assert.equal(w.document.getElementById('ref-p0').textContent,'1');
});
test('An uncertain response never replays a point; reconnect reads the saved value',async t=>{
 const {w,writes,poll,mode}=await setup(t);mode('lost');w.document.querySelector('[data-side="1"]').click();await tick();
 assert.equal(writes.length,1);assert.equal(w.document.querySelector('[data-side="1"]').disabled,true);
 await poll();assert.equal(writes.length,1);assert.equal(w.document.getElementById('ref-p1').textContent,'1');assert.equal(w.document.querySelector('[data-side="1"]').disabled,false);
});
test('A stale revision refreshes server state and does not claim a successful point',async t=>{
 const {w,writes,mode}=await setup(t);mode('conflict');w.document.querySelector('[data-side="0"]').click();await tick();
 assert.equal(writes.length,1);assert.equal(w.document.getElementById('ref-p0').textContent,'2');assert.equal(w.document.getElementById('ref-p1').textContent,'1');assert.match(w.document.getElementById('ref-connection').textContent,/zmieniły/);
});
test('The final confirmation stops further point entry',async t=>{
 const {w,writes,server,poll}=await setup(t);server.awaiting_confirmation=true;server.sets=[[15,0],[15,0]];await poll();
 assert.equal(w.document.querySelector('[data-side="0"]').disabled,true);assert.equal(w.document.getElementById('ref-finish').hidden,false);
 w.document.getElementById('ref-finish').click();await tick();assert.equal(writes[0].action,'finish');assert.equal(w.document.querySelector('[data-side="0"]').disabled,true);assert.match(w.document.getElementById('ref-connection').textContent,/zakończony/);
});
