// Development-only: npm install --no-save jsdom; node --test test_admin_match_updates.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const script = fs.readFileSync(__dirname + '/static/admin-match-updates.js', 'utf8');
function card(id, {started=false, player='3', score=''}={}) {
  return `<div class="match-card" id="match-${id}" data-player1="${id===1?'1':player}" data-player2="${id===1?'2':'4'}">
  <strong>${started?'W trakcie':'Oczekuje'}</strong>
  <form action="/match/${id}/result" method="post"><input name="set_1_p1" value="${score}"><input name="csrf_token" type="hidden" value="csrf"><button type="submit">Save result</button></form>
  ${started?'':`<form action="/match/${id}/timing" method="post"><button name="action" value="start">Start teraz</button></form>`}
  <details><summary>Edytuj godziny</summary><form action="/match/${id}/timing" method="post"><input name="manual_start"></form></details></div>`;
}
function html(options={}) {
  return `<html style="scroll-behavior:smooth"><body>${options.message?`<div class="flash">${options.message}</div>`:''}
  <details id="group-tables"><summary>Tables</summary><p>${options.started?'Updated table':'Old table'}</p></details>
  <section id="matches">${card(1,options)}${card(2,{player:options.player})}</section>
  <details id="tree" open><summary>Draw</summary><p>${options.started?'New draw':'Old draw'}</p></details>
  <details id="standings" open><summary>Standings</summary></details></body></html>`;
}
function setup(t) {
  const dom=new JSDOM(html(),{url:'https://tournament.test/tournament/1#match-1',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const w=dom.window;
  w.HTMLElement.prototype.getBoundingClientRect=function(){return {top:this.id==='match-1'?100:450,bottom:this.id==='match-1'?400:750};};
  w.scrollX=0;w.scrollY=700;w.innerHeight=1000;
  const scrolls=[];w.scrollTo=options=>scrolls.push(options);
  const requests=[];
  w.fetch=async(url,options)=>{requests.push({url,options});return {ok:true,text:async()=>html({started:true,message:'Zapisano czas meczu.'})};};
  w.eval(script);
  const dirty=(selector,value)=>{const el=w.document.querySelector(selector);el.value=value;el.dispatchEvent(new w.Event('input',{bubbles:true}));return el;};
  const submit=async(selector)=>{
    const form=w.document.querySelector(selector);
    const event=new w.SubmitEvent('submit',{bubbles:true,cancelable:true,submitter:form.querySelector('button')});
    assert.equal(form.dispatchEvent(event),false,'Submission must not navigate');
    await new Promise(resolve=>setImmediate(resolve));
  };
  return {w,requests,scrolls,dirty,submit};
}
test('Start now sends the button value, updates in place and keeps unsaved scores and scroll',async t=>{
  const {w,requests,scrolls,dirty,submit}=setup(t);
  dirty('#match-1 input[name=set_1_p1]','21');
  dirty('#match-2 input[name=set_1_p1]','12').focus();
  w.document.querySelector('#match-1 details').open=true;
  const before=w.location.href;
  await submit('#match-1 form[action$="/timing"]');
  assert.equal(requests.length,1);
  assert.equal(requests[0].options.body.get('action'),'start');
  assert.equal(requests[0].options.method,'POST');
  assert.equal(w.document.querySelector('#match-1 input[name=set_1_p1]').value,'21');
  assert.equal(w.document.querySelector('#match-2 input[name=set_1_p1]').value,'12');
  assert.equal(w.document.activeElement.name,'set_1_p1');
  assert.equal(w.document.activeElement.closest('.match-card').id,'match-2');
  assert.equal(w.document.querySelector('#match-1 details').open,true);
  assert.match(w.document.querySelector('#match-1').textContent,/W trakcie/);
  assert.match(w.document.querySelector('#group-tables').textContent,/Updated table/);
  assert.equal(w.document.querySelector('#group-tables').open,false);
  assert.equal(w.document.querySelector('#tree').open,true);
  assert.equal(w.location.href,before);
  assert.equal(scrolls.length,1);
  assert.equal(scrolls[0].behavior,'instant');
  assert.equal(scrolls[0].top,700);
  assert.equal(w.document.documentElement.style.scrollBehavior,'smooth');
});
test('Saving a score replaces the saved form and preserves other drafts',async t=>{
  const {w,requests,dirty,submit}=setup(t);
  dirty('#match-1 input[name=set_1_p1]','21');dirty('#match-2 input[name=set_1_p1]','12');
  w.fetch=async(url,options)=>{requests.push({url,options});return {ok:true,text:async()=>html({score:'21',message:'Result saved.'})};};
  await submit('#match-1 form[action$="/result"]');
  assert.equal(requests[0].options.body.get('set_1_p1'),'21');
  assert.equal(requests[0].options.body.get('csrf_token'),'csrf');
  assert.equal(w.document.querySelector('#match-1 input[name=set_1_p1]').value,'21');
  assert.equal(w.document.querySelector('#match-2 input[name=set_1_p1]').value,'12');
});
test('Changed participants discard stale unsaved scores and notify the organiser',async t=>{
  const {w,dirty,submit}=setup(t);dirty('#match-2 input[name=set_1_p1]','12');
  w.fetch=async()=>({ok:true,text:async()=>html({player:'9',message:'Result saved.'})});
  await submit('#match-1 form[action$="/result"]');
  assert.equal(w.document.querySelector('#match-2 input[name=set_1_p1]').value,'');
  assert.match(w.document.querySelector('.match-save-notice').textContent,/Zmienili się uczestnicy/);
});
for(const failure of ['network','validation','expired'])test(`${failure} keeps entered scores and enables retry`,async t=>{
  const {w,dirty,submit,scrolls}=setup(t);dirty('#match-1 input[name=set_1_p1]','19');
  w.fetch=async()=>{if(failure==='network')throw new Error('Offline');return {ok:true,text:async()=>failure==='expired'?'<form>Login</form>':html({message:'This match is not ready yet.'})};};
  await submit('#match-1 form[action$="/result"]');
  assert.equal(w.document.querySelector('#match-1 input[name=set_1_p1]').value,'19');
  assert.equal(w.document.querySelector('#match-1 input[name=set_1_p1]').disabled,false);
  assert.equal(w.document.querySelector('.match-save-notice').dataset.error,'true');
  assert.equal(scrolls.length,0);
});
