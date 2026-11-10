(() => {
  const root=document.getElementById('referee-app');
  if(!root)return;
  let state=null,busy=false,blocked=true;
  const status=document.getElementById('ref-connection');
  const tiles=[...root.querySelectorAll('.point-tile')];
  const undo=document.getElementById('ref-undo'),finish=document.getElementById('ref-finish');
  function render(){
    if(!state)return;
    tiles.forEach((tile,i)=>{tile.disabled=busy||blocked||state.playable===false||state.awaiting_confirmation||!!state.winner_id||state.finalized;document.getElementById('ref-p'+i).textContent=state.current[i];tile.querySelector('.ref-name').textContent=state.players[i];});
    document.getElementById('ref-rules').textContent='Do '+state.points_to+' punktów · best of '+state.best_of;
    document.getElementById('ref-sets').textContent='Sety: '+(state.sets.map(s=>s.join(':')).join(' · ')||'—');
    undo.disabled=busy||blocked||!!state.winner_id||state.finalized;
    finish.hidden=!state.awaiting_confirmation||state.finalized||!!state.winner_id;
    finish.disabled=busy||blocked;
    if(state.playable===false&&!state.winner_id)status.textContent='Mecz czeka na uczestników lub wcześniejsze wyniki. Poproś stolik o sprawdzenie.';
    if(state.finalized||state.winner_id)status.textContent='Mecz zakończony — wynik zapisany.';
  }
  async function read(){
    const response=await fetch(root.dataset.stateUrl,{cache:'no-store'});
    if(!response.ok)throw new Error(response.status===403?'Dostęp wygasł. Wejdź ponownie z aktualnym kodem.':'Nie można pobrać wyniku. Sprawdź połączenie.');
    const incoming=await response.json();if(!state||incoming.revision>=state.revision)state=incoming;blocked=false;status.textContent='Połączono · wynik aktualny';render();
  }
  async function action(kind,side){
    if(busy||blocked||!state)return;
    busy=true;render();status.textContent='Zapisywanie…';
    try{
      const response=await fetch(root.dataset.actionUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:kind,side,revision:state.revision})});
      if(!response.ok){
        blocked=true;
        await read();
        status.textContent=response.status===409?'Wynik lub dostępność meczu zmieniły się. Sprawdź wynik przed kolejnym kliknięciem.':'Nie zapisano. Sprawdź dostęp, kod i połączenie.';
      }else{const incoming=await response.json();if(!state||incoming.revision>=state.revision)state=incoming;status.textContent='Zapisano';}
    }catch(e){
      // Never replay an uncertain point automatically: the first request may have succeeded.
      blocked=true;status.textContent='Brak potwierdzenia zapisu. Łączenie i sprawdzanie wyniku…';
    }finally{busy=false;render();}
  }
  tiles.forEach(tile=>tile.addEventListener('click',()=>action('point',Number(tile.dataset.side))));
  undo.addEventListener('click',()=>action('undo'));
  finish.addEventListener('click',()=>{if(confirm('Zatwierdzić końcowy wynik? Sprawdź zapisane sety.'))action('finish');});
  async function poll(){if(busy||document.hidden)return;try{await read();}catch(e){blocked=true;status.textContent=e.message;render();}}
  poll();setInterval(poll,2000);
})();
