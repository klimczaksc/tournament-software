const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const {JSDOM}=require('jsdom');
const script=fs.readFileSync(__dirname+'/static/match-statistics.js','utf8');const tick=()=>new Promise(r=>setImmediate(r));
async function setup(t){
 const dom=new JSDOM('<div id="match-stats" data-url="/stats"><div id="stat-duration"></div><div id="stat-quality"></div><div id="stat-estimate"></div><div id="stat-path"></div><table><tbody id="stat-audit"></tbody></table><div id="stat-connection"></div><button id="stats-export"></button></div>',{url:'https://tournament.test',runScripts:'outside-only',pretendToBeVisual:true});t.after(()=>dom.window.close());const w=dom.window;let poll;
 w.setInterval=(fn,delay)=>{if(delay===2000)poll=fn;};
 const data={version:'1',match_id:1,players:['A','B'],duration_seconds:null,started_at:null,ended_at:null,quality:'missing',estimate:{count:0},zone:'Europe/Warsaw',points_missing:false,audit:[],path:[{n:1,set:1,side:0,score:[1,0]},{n:2,set:1,side:0,score:[2,0]},{n:3,set:1,side:1,score:[2,1]},{n:4,set:1,side:0,score:[3,1]}]};
 w.fetch=async()=>({ok:true,status:200,json:async()=>structuredClone(data)});w.eval(script);await tick();return {w,data,poll:()=>poll()};
}
test('One column per rally: scorer has their point number, opponent cell is empty',async t=>{
 const {w}=await setup(t);const rows=w.document.querySelectorAll('tbody tr');assert.equal(rows.length,2);assert.deepEqual([...rows[0].querySelectorAll('td')].map(c=>c.textContent),['1','2','','3']);assert.deepEqual([...rows[1].querySelectorAll('td')].map(c=>c.textContent),['','','1','']);assert.equal(w.document.querySelectorAll('thead th').length,5);
});
test('Undo updates cells in place; each new set starts its own point numbering',async t=>{
 const {w,data,poll}=await setup(t);const table=w.document.querySelector('table'),first=w.document.querySelector('tbody tr td');data.path.pop();data.version='2';await poll();assert.equal(w.document.querySelector('table'),table);assert.equal(w.document.querySelector('tbody tr td'),first);assert.equal(w.document.querySelector('tbody tr').children.length,4);
 data.path.push({n:4,set:2,side:1,score:[0,1]});data.version='3';await poll();const sections=w.document.querySelectorAll('[data-set]');assert.equal(sections.length,2);assert.equal(sections[1].querySelector('thead th:nth-child(2)').textContent,'1');assert.equal(sections[1].querySelector('tbody tr:nth-child(2) td').textContent,'1');assert.equal(sections[1].querySelector('tbody tr:nth-child(1) td').textContent,'');
});
