/* Reconcile changed entities only. HTTP cursors are portable across reconnects/workers. */
(() => {
 const source=document.getElementById('tournament-events');if(!source)return;
 let cursor='',pending=null;
 const dirty=new WeakSet();let submitted=null;
 document.addEventListener('input',e=>{if(e.target.form)dirty.add(e.target.form);});
 document.addEventListener('change',e=>{if(e.target.form)dirty.add(e.target.form);});
 const find=key=>[...document.querySelectorAll('[data-event-key]')].find(el=>el.dataset.eventKey===key);
 function morph(old,fresh,invalidate=false){
  if(old.nodeType!==fresh.nodeType||old.nodeName!==fresh.nodeName){old.replaceWith(fresh.cloneNode(true));return;}
  if(old.nodeType===3||old.nodeType===8){if(old.nodeValue!==fresh.nodeValue)old.nodeValue=fresh.nodeValue;return;}
  if(old.nodeType!==1)return;
  if(old.tagName==='FORM'&&dirty.has(old)&&old!==submitted&&!invalidate)return;
  const keepOpen=old.tagName==='DETAILS';
  for(const attr of [...old.attributes])if(!fresh.hasAttribute(attr.name)&&!(keepOpen&&attr.name==='open')&&attr.name!=='style')old.removeAttribute(attr.name);
  for(const attr of [...fresh.attributes])if(!(keepOpen&&attr.name==='open')&&old.getAttribute(attr.name)!==attr.value)old.setAttribute(attr.name,attr.value);
  if(old.matches('input,select,textarea')){
   if(old.value!==fresh.value)old.value=fresh.value;
   if(old.type==='checkbox'||old.type==='radio')old.checked=fresh.checked;
  }
  const incoming=[...fresh.childNodes];
  incoming.forEach((child,i)=>{const target=old.childNodes[i];if(target)morph(target,child,invalidate);else old.append(child.cloneNode(true));});
  while(old.childNodes.length>incoming.length)old.lastChild.remove();
 }
 function lists(layout){
  if(!layout||source.dataset.public!=='1')return;
  const batches={next:layout.upcoming.slice(0,5),more:layout.upcoming.slice(5),completed:layout.completed};
  Object.entries(batches).forEach(([name,keys])=>{
   const target=document.querySelector('[data-event-list="'+name+'"]');if(!target)return;
   target.querySelectorAll(':scope > p').forEach(p=>p.remove());
   keys.forEach((key,i)=>{const card=find(key);if(card&&target.children[i]!==card)target.insertBefore(card,target.children[i]||null);});
   if(!keys.length&&name!=='more'){const p=document.createElement('p');p.textContent=name==='next'?'Brak nadchodzących meczów.':'Nie ma jeszcze wyników.';target.append(p);}
  });
  const more=document.getElementById('more-upcoming');if(more){more.hidden=layout.upcoming.length<=5;more.querySelector('summary').textContent='Pokaż pozostałe mecze ('+Math.max(0,layout.upcoming.length-5)+') · rozwiń / zwiń';}
  const results=document.querySelector('#results > summary');if(results)results.textContent='Wyniki meczów ('+layout.completed.length+') · rozwiń / zwiń';
 }
 function apply(patch){
  const visible=[...document.querySelectorAll('[data-event-key^="match:"]')].find(el=>{const r=el.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight;});
  const anchor=visible?.dataset.eventKey,top=visible?.getBoundingClientRect().top;
  const y=window.scrollY,x=window.scrollX,root=document.documentElement;
  const behavior=root.style.scrollBehavior,anchoring=root.style.overflowAnchor;
  root.style.scrollBehavior='auto';root.style.overflowAnchor='none';
  try{
   if(patch.reset)document.querySelectorAll('[data-event-key]').forEach(el=>{if(/^(match:|bracket:|group:)/.test(el.dataset.eventKey)&&!(el.dataset.eventKey in patch.entities))el.remove();});
   for(const key of patch.removed||[])find(key)?.remove();
   for(const [key,html] of Object.entries(patch.entities||{})){
    const template=document.createElement('template');template.innerHTML=html;const fresh=template.content.firstElementChild;if(!fresh)continue;
    const old=find(key);
    if(old){
     const changedPlayers=old.dataset.player1!==fresh.dataset.player1||old.dataset.player2!==fresh.dataset.player2;
     const opened=[...old.querySelectorAll('details')].map(d=>d.open);
     const drafts=[...old.querySelectorAll('form')].filter(f=>dirty.has(f)&&f!==submitted&&!changedPlayers).map(f=>({action:f.getAttribute('action'),fields:[...f.elements].filter(el=>el.name&&el.type!=='hidden'&&el.tagName!=='BUTTON').map(el=>({name:el.name,value:el.value,checked:el.checked,focused:el===document.activeElement}))}));
     morph(old,fresh,changedPlayers);
     old.querySelectorAll('details').forEach((d,i)=>{if(i<opened.length)d.open=opened[i];});
     drafts.forEach(draft=>{const target=[...old.querySelectorAll('form')].find(f=>f.getAttribute('action')===draft.action&&draft.fields.every(field=>f.elements.namedItem(field.name)));if(!target)return;draft.fields.forEach(field=>{const el=target.elements.namedItem(field.name);if(el.disabled)return;el.value=field.value;if(el.type==='checkbox'||el.type==='radio')el.checked=field.checked;if(field.focused)el.focus({preventScroll:true});});dirty.add(target);});
    }
    else if(key.startsWith('match:')){document.querySelector(source.dataset.public==='1'?'[data-event-list="more"]':'#matches .section-body')?.append(fresh);}
   }
   lists(patch.layout);
   if(typeof applyFilter==='function')applyFilter();
   if(Object.keys(patch.entities||{}).some(key=>key.startsWith('bracket:'))&&typeof drawBracketConnectors==='function')drawBracketConnectors();
   const el=anchor&&find(anchor);window.scrollTo({left:x,top:el?y+el.getBoundingClientRect().top-top:y,behavior:'instant'});
  }finally{root.style.scrollBehavior=behavior;root.style.overflowAnchor=anchoring;}
  document.dispatchEvent(new CustomEvent('tournament:updated',{detail:{changed:Object.keys(patch.entities||{}),cursor:patch.cursor}}));
 }
 function status(text){const el=document.getElementById('refresh-status');if(el)el.textContent=text;}
 async function refresh(options={}){
  if(pending){await pending;if(options.submitted)return refresh(options);return;}
  submitted=options.submitted||null;if(submitted)dirty.delete(submitted);
  pending=(async()=>{
   try{
    const response=await fetch(source.dataset.url+'?cursor='+encodeURIComponent(cursor),{cache:'no-store'});
    if(response.status===304){status('Połączono · brak nowych zmian');return;}
    if(!response.ok)throw new Error('Brak aktualizacji — sprawdź połączenie i dostęp.');
    const patch=await response.json();apply(patch);cursor=patch.cursor;
    status('Zaktualizowano '+new Date().toLocaleTimeString('pl-PL')+' · tylko zmienione mecze');
   }catch(e){status(e.message);throw e;}
   finally{submitted=null;pending=null;}
  })();
  return pending;
 }
 function clocks(){document.querySelectorAll('[data-timeout-until]').forEach(el=>{const clock=el.querySelector('[data-timeout-clock]');if(!clock)return;const seconds=Math.max(0,Math.ceil((Date.parse(el.dataset.timeoutUntil)-Date.now())/1000));clock.textContent=seconds?Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0'):'Koniec czasu';});}
 clocks();setInterval(clocks,250);
 window.TournamentEvents={refresh,morph};
 refresh().catch(()=>{});setInterval(()=>{if(!document.hidden)refresh().catch(()=>{});},2000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh().catch(()=>{});});
})();
