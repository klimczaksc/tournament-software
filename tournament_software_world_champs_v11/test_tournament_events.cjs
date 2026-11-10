const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const {JSDOM}=require('jsdom');
const code=fs.readFileSync(__dirname+'/static/tournament-events.js','utf8');const tick=()=>new Promise(r=>setImmediate(r));
function card(id,text='0:0',extra=''){return `<article data-event-key="match:${id}" data-player1="1" data-player2="2"><strong>${text}</strong>${extra}<details><summary>Godziny</summary><form action="/timing"><input name="manual_start" value="10:00"></form></details></article>`;}
async function setup(t,publicMode=false){
 const dom=new JSDOM(`<div id="tournament-events" data-url="/updates/token" data-public="${publicMode?'1':'0'}"></div><div id="refresh-status"></div><section id="matches"><div class="section-body">${card(1)}${card(2)}</div></section><div data-event-list="next"></div><details id="more-upcoming"><summary></summary><div data-event-list="more"></div></details><details id="results"><summary></summary><div data-event-list="completed"></div></details>`,{url:'https://tournament.test/t/token',runScripts:'outside-only',pretendToBeVisual:true});
 t.after(()=>dom.window.close());const w=dom.window;w.setInterval=()=>{};w.scrollTo=()=>{};let patch=null;const urls=[];
 w.fetch=async url=>{urls.push(url);return patch?{ok:true,status:200,json:async()=>patch}:{status:304};};
 w.eval(code);await tick();return {w,urls,set:p=>patch=p};
}
test('Changed score patches preserve both card identity and untouched nodes',async t=>{const {w,set,urls}=await setup(t);const one=w.document.querySelector('[data-event-key="match:1"]'),two=w.document.querySelector('[data-event-key="match:2"]'),score=one.querySelector('strong');set({cursor:'new',entities:{'match:1':card(1,'1:0')},removed:[]});await w.TournamentEvents.refresh();assert.equal(w.document.querySelector('[data-event-key="match:1"]'),one);assert.equal(one.querySelector('strong'),score);assert.equal(score.textContent,'1:0');assert.equal(w.document.querySelector('[data-event-key="match:2"]'),two);assert.ok(urls.every(url=>url.startsWith('/updates/token?cursor=')));});
test('Unsaved forms and expanded details survive a score update and insertion',async t=>{const {w,set}=await setup(t);const one=w.document.querySelector('[data-event-key="match:1"]'),details=one.querySelector('details'),input=one.querySelector('input');details.open=true;input.value='11:15';input.dispatchEvent(new w.Event('input',{bubbles:true}));set({cursor:'n',entities:{'match:1':card(1,'2:0','<p>Nowy status</p>')},removed:[]});await w.TournamentEvents.refresh();const fresh=one.querySelector('input');assert.equal(fresh.value,'11:15');assert.equal(one.querySelector('details').open,true);});
test('Completed matches move between lists without recreating their card',async t=>{const {w,set}=await setup(t,true);const one=w.document.querySelector('[data-event-key="match:1"]');set({cursor:'n',entities:{},removed:[],layout:{upcoming:['match:2'],completed:['match:1']}});await w.TournamentEvents.refresh();assert.equal(w.document.querySelector('[data-event-list="completed"]').firstElementChild,one);assert.equal(w.document.getElementById('more-upcoming').hidden,true);});
test('An unchanged cursor causes no DOM mutation',async t=>{const {w}=await setup(t);const old=w.document.querySelector('#matches').innerHTML;await w.TournamentEvents.refresh();assert.equal(w.document.querySelector('#matches').innerHTML,old);});

test('Confirmed remote result replaces only that result draft and announces the saved match',async t=>{
 const {w,set}=await setup(t);
 const one=w.document.querySelector('[data-event-key="match:1"]'),two=w.document.querySelector('[data-event-key="match:2"]');
 one.dataset.resultVersion=':[]';
 const result=w.document.createElement('form');result.action='/match/1/result';result.innerHTML='<input name="set_1_p1" value=""><input name="set_1_p2" value="">';one.prepend(result);
 result.elements[0].value='9';result.elements[0].dispatchEvent(new w.Event('input',{bubbles:true}));
 const time=one.querySelector('[name="manual_start"]');time.value='12:00';time.dispatchEvent(new w.Event('input',{bubbles:true}));
 const other=two.querySelector('input');other.value='11:45';other.dispatchEvent(new w.Event('input',{bubbles:true}));
 const fresh=`<article data-event-key="match:1" data-result-version="1:[[15,5],[15,5]]" data-event-complete="1" data-match-number="7" data-result-score="15-5, 15-5" data-player1="1" data-player2="2"><form action="/match/1/result"><input name="set_1_p1" value="15"><input name="set_1_p2" value="5"></form><strong>Zakończony</strong><details><summary>Godziny</summary><form action="/timing"><input name="manual_start" value="10:00"></form></details></article>`;
 set({cursor:'accepted',entities:{'match:1':fresh},removed:[]});await w.TournamentEvents.refresh();
 assert.equal(one.querySelector('[name="set_1_p1"]').value,'15');assert.equal(one.querySelector('[name="set_1_p2"]').value,'5');
 assert.equal(one.querySelector('[name="manual_start"]').value,'12:00');assert.equal(two.querySelector('input').value,'11:45');
 assert.match(w.document.querySelector('.tournament-result-notice').textContent,/#7/);assert.equal(w.document.querySelector('.tournament-result-notice').hidden,false);
});
