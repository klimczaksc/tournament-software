(() => {
 const T=window.uiText||((text)=>text);
  const root=document.getElementById('referee-app');
  if(!root)return;
  let state=null,busy=false,blocked=true,serverOffset=0;
  const status=document.getElementById('ref-connection');
  const tiles=[...root.querySelectorAll('.point-tile')];
  const undo=document.getElementById('ref-undo'),finish=document.getElementById('ref-finish'),start=document.getElementById('ref-start');
  const timeoutButtons=[...root.querySelectorAll('[data-timeout-side]')],timeoutPanel=document.getElementById('ref-timeouts'),timeoutDisplay=document.getElementById('ref-timeout-active'),timeoutEnd=document.getElementById('ref-timeout-end');
  const activeTimeout=()=>state?.timeout?.active&&Date.parse(state.timeout.active.until)>Date.now()+serverOffset?state.timeout.active:null;
  function accept(incoming){if(!state||incoming.revision>=state.revision){state=incoming;if(state.timeout?.server_now)serverOffset=Date.parse(state.timeout.server_now)-Date.now();}}
  function render(){
    if(!state)return;
    if(state.language)window.TournamentI18n?.setLanguage(state.language);
    const active=activeTimeout();
    const back=document.getElementById('ref-return'),handover=document.getElementById('ref-handover'),note=document.getElementById('ref-handover-note');
    if(back)back.hidden=!(state.finalized||state.winner_id||state.handover);
    if(handover){handover.hidden=!!state.winner_id||state.finalized||state.handover;handover.disabled=busy||blocked;}
    if(note)note.hidden=!state.handover;
    if(timeoutPanel)timeoutPanel.hidden=state.awaiting_confirmation||state.finalized||!!state.winner_id;
    timeoutButtons.forEach(button=>{const side=Number(button.dataset.timeoutSide),used=!!state.timeout?.used[side];button.disabled=busy||blocked||!state.started||state.playable===false||state.awaiting_confirmation||!!state.winner_id||!!active||used;button.textContent=T('Czas — ')+state.players[side]+' · '+(used?T('wykorzystany'):T('dostępny'))+T(' (set ')+(state.timeout?.set||state.sets.length+1)+')';});
    if(timeoutDisplay){timeoutDisplay.hidden=!active;if(active){const remaining=Math.max(0,Math.ceil((Date.parse(active.until)-Date.now()-serverOffset)/1000));document.getElementById('ref-timeout-clock').textContent=Math.floor(remaining/60)+':'+String(remaining%60).padStart(2,'0');document.getElementById('ref-timeout-owner').textContent=T('Czas: ')+state.players[active.side];}}
    if(timeoutEnd)timeoutEnd.disabled=busy||blocked;
    if(start){start.hidden=state.started||!!state.winner_id;start.disabled=busy||blocked||state.playable===false;}
    tiles.forEach((tile,i)=>{tile.disabled=busy||blocked||!!active||!state.started||state.playable===false||state.awaiting_confirmation||!!state.winner_id||state.finalized;document.getElementById('ref-p'+i).textContent=state.current[i];tile.querySelector('.ref-name').textContent=state.players[i];});
    document.getElementById('ref-rules').textContent=T('Do ')+state.points_to+T(' punktów · best of ')+state.best_of;
    document.getElementById('ref-sets').textContent=T('Sety: ')+(state.sets.map(s=>s.join(':')).join(' · ')||'—');
    undo.disabled=busy||blocked||!!active||!!state.winner_id||state.finalized;
    finish.hidden=!state.awaiting_confirmation||state.finalized||!!state.winner_id;
    finish.disabled=busy||blocked;
    if(state.playable===false&&!state.winner_id)status.textContent=T('Mecz czeka na uczestników lub wcześniejsze wyniki. Poproś stolik o sprawdzenie.');
    if(state.finalized||state.winner_id)status.textContent=T('Mecz zakończony — wynik zapisany.');
  }
  async function read(){
    const response=await fetch(root.dataset.stateUrl,{cache:'no-store'});
    if(!response.ok)throw new Error(response.status===403?T('Dostęp wygasł. Wejdź ponownie z aktualnym kodem.'):T('Nie można pobrać wyniku. Sprawdź połączenie.'));
    const incoming=await response.json();accept(incoming);blocked=false;status.textContent=T('Połączono · wynik aktualny');render();
  }
  async function action(kind,side){
    if(busy||blocked||!state)return;
    busy=true;render();status.textContent=T('Zapisywanie…');
    try{
      const response=await fetch(root.dataset.actionUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:kind,side,revision:state.revision})});
      if(!response.ok){
        blocked=true;
        await read();
        status.textContent=response.status===409?T('Wynik lub dostępność meczu zmieniły się. Sprawdź wynik przed kolejnym kliknięciem.'):T('Nie zapisano. Sprawdź dostęp, kod i połączenie.');
      }else{const incoming=await response.json();accept(incoming);status.textContent=T('Zapisano');}
    }catch(e){
      // Never replay an uncertain point automatically: the first request may have succeeded.
      blocked=true;status.textContent=T('Brak potwierdzenia zapisu. Łączenie i sprawdzanie wyniku…');
    }finally{busy=false;render();}
  }
  timeoutButtons.forEach(button=>button.addEventListener('click',()=>{const side=Number(button.dataset.timeoutSide);if(confirm(T('Uruchomić 2-minutowy czas dla: ')+state.players[side]+T('? W tym secie można go wykorzystać tylko raz.')))action('timeout',side);}));
  if(timeoutEnd)timeoutEnd.addEventListener('click',()=>action('timeout_end'));
  const handover=document.getElementById('ref-handover');if(handover)handover.addEventListener('click',()=>{if(confirm(T('Przekazać sędziowanie? Zgłoś się do stolika po zastępstwo. Wynik zostanie zachowany.')))action('handover');});
  if(start)start.addEventListener('click',()=>action('start'));
  tiles.forEach(tile=>tile.addEventListener('click',()=>action('point',Number(tile.dataset.side))));
  undo.addEventListener('click',()=>action('undo'));
  finish.addEventListener('click',()=>{if(confirm(T('Zatwierdzić końcowy wynik? Sprawdź zapisane sety.')))action('finish');});
  async function poll(){if(busy||document.hidden)return;try{await read();}catch(e){blocked=true;status.textContent=e.message;render();}}
  poll();setInterval(poll,2000);setInterval(render,250);
})();
