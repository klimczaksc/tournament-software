const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const {JSDOM}=require('jsdom');
const catalog=JSON.parse(fs.readFileSync(__dirname+'/translations/ui.json','utf8'));
const i18n=fs.readFileSync(__dirname+'/static/i18n.js','utf8');const events=fs.readFileSync(__dirname+'/static/tournament-events.js','utf8');const tick=()=>new Promise(r=>setImmediate(r));
test('All catalogue entries provide the four languages and preserve interpolation fields',()=>{
 for(const [key,values] of Object.entries(catalog))for(const lang of ['pl','en','de','fr']){
  assert.equal(typeof values[lang],'string',key+' / '+lang);assert.ok(values[lang].length,key+' / '+lang);
  const fields=s=>(s.match(/\{\d+\}/g)||[]).sort();assert.deepEqual(fields(values[lang]),fields(key),key+' / '+lang);
 }
});
test('Live language changes translate only marked UI, preserve names and dirty scores, and use the new language in list controls',async t=>{
 const card=(status)=>`<article data-event-key="match:1" data-player1="1" data-player2="2"><strong class="player-name">Final</strong><span>${status}</span><form action="/match/1/result"><input name="set_1_p1" value="0"></form></article>`;
 const dom=new JSDOM(`<html lang="pl"><body><div id="tournament-events" data-url="/updates/token" data-public="1"></div><div data-event-key="language" id="tournament-language" data-language="pl" hidden></div><h2 data-ui-key="Najbliższe mecze">Najbliższe mecze</h2><input id="search" data-ui-attrs="{&quot;placeholder&quot;:&quot;Szukaj drużyny / zawodnika&quot;}" placeholder="Szukaj drużyny / zawodnika"><div data-event-list="next">${card('W trakcie')}</div><details id="more-upcoming"><summary></summary><div data-event-list="more"></div></details><details id="results"><summary></summary><div data-event-list="completed"></div></details></body></html>`,{url:'https://tournament.test/t/cup',runScripts:'outside-only',pretendToBeVisual:true});
 t.after(()=>dom.window.close());const w=dom.window;w.UITranslations={catalog,patterns:[]};w.setInterval=()=>{};w.scrollTo=()=>{};let patch=null;w.fetch=async()=>patch?{ok:true,status:200,json:async()=>patch}:{status:304};
 w.eval(i18n);w.eval(events);await tick();
 const old=w.document.querySelector('article'),input=old.querySelector('input');input.value='99';input.dispatchEvent(new w.Event('input',{bubbles:true}));
 patch={cursor:'fr-cursor',reset:false,removed:[],entities:{language:'<div data-event-key="language" id="tournament-language" data-language="fr" hidden></div>','match:1':card('En cours')},layout:{upcoming:['match:1'],completed:[]}};
 await w.TournamentEvents.refresh();
 assert.equal(w.document.documentElement.lang,'fr');assert.equal(w.uiLocale,'fr-FR');
 assert.equal(w.document.querySelector('h2').textContent,'Prochains matchs');assert.equal(w.document.getElementById('search').placeholder,'Chercher une équipe / un joueur');
 assert.equal(w.document.querySelector('article'),old);assert.equal(old.querySelector('input'),input);assert.equal(input.value,'99');assert.equal(old.querySelector('.player-name').textContent,'Final');
 assert.match(w.document.querySelector('#results>summary').textContent,/Résultats des matchs/);
 assert.equal(w.location.href,'https://tournament.test/t/cup');
 w.TournamentI18n.setLanguage('de');assert.equal(w.document.querySelector('h2').textContent,'Nächste Spiele');assert.equal(old.querySelector('.player-name').textContent,'Final');
});
