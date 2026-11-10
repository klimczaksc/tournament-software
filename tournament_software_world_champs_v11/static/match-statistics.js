(() => {
 const root=document.getElementById('match-stats');if(!root)return;
 let data=null,busy=false;
 const label={start:'Start meczu',point:'Punkt',undo:'Cofnięcie punktu',finish:'Zatwierdzenie wyniku',reset:'Reset panelu'};
 const time=(at)=>at?new Date(at).toLocaleTimeString('pl-PL',{timeZone:data.zone,hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Brak pomiaru czasu';
 function duration(){if(!data)return;let seconds=data.duration_seconds;if(seconds==null&&data.started_at&&!data.ended_at&&!data.complete)seconds=Math.max(0,(Date.now()-new Date(data.started_at).getTime())/1000);document.getElementById('stat-duration').textContent=seconds==null?'Brak pełnego pomiaru':(seconds/60).toFixed(1)+' min'+(!data.ended_at&&!data.complete?' · trwa':'');}
 function render(incoming){
  data=incoming;
  duration();
  document.getElementById('stat-quality').textContent=data.quality==='first_point'?'Pomiar przybliżony: od pierwszego zarejestrowanego punktu.':data.quality==='legacy_unverified'?'Starszy pomiar — moment startu niezweryfikowany.':data.started_at?'Start: '+time(data.started_at)+(data.ended_at?' · koniec: '+time(data.ended_at):' · mecz trwa'):'Brak rzeczywistej godziny startu.';
  const e=data.estimate;
  document.getElementById('stat-estimate').textContent=e.count?'Podobne mecze (ten sam limit, best of i typ fazy): '+e.count+' · mediana '+e.median+' min · środkowe 50%: '+e.p25+'–'+e.p75+' min. '+(e.suggested?'Sugerowany slot: '+e.suggested+' min.':'Sugestia slotu pojawi się od 5 pełnych pomiarów.'):'Brak wystarczających pełnych pomiarów do estymacji. Standardowe 30 minut pozostaje ustawieniem organizatora.';
  const path=document.getElementById('stat-path');
  if(data.points_missing){if(path.textContent!=='Brak zapisanej historii punkt po punkcie. Wynik końcowy nie pozwala jej odtworzyć.')path.textContent='Brak zapisanej historii punkt po punkcie. Wynik końcowy nie pozwala jej odtworzyć.';}
  else{
   if(path.firstChild?.nodeType===3||path.querySelector('p'))path.replaceChildren();
   const bySet=new Map();data.path.forEach(p=>{if(!bySet.has(p.set))bySet.set(p.set,[]);bySet.get(p.set).push(p);});
   for(const [number,points] of bySet){
    let section=path.querySelector('[data-set="'+number+'"]');
    if(!section){section=document.createElement('section');section.dataset.set=number;const h=document.createElement('h3');h.textContent='Set '+number;section.append(h);const nodes=document.createElement('div');nodes.className='point-path';section.append(nodes);path.append(section);}
    const nodes=section.querySelector('.point-path');
    points.forEach((point,i)=>{let node=nodes.children[i];if(!node){node=document.createElement('span');node.className='point-node';nodes.append(node);}const text=point.score.join(':');node.dataset.side=point.side;node.title=data.players[point.side]+' · '+time(point.at);if(node.dataset.value!==text+'|'+point.at){node.dataset.value=text+'|'+point.at;node.textContent=text;const small=document.createElement('small');small.textContent='#'+point.n+' · '+time(point.at);node.append(small);}});
    while(nodes.children.length>points.length)nodes.lastChild.remove();
   }
   for(const section of [...path.querySelectorAll('[data-set]')])if(!bySet.has(Number(section.dataset.set)))section.remove();
  }
  const audit=document.getElementById('stat-audit');
  data.audit.forEach((event,i)=>{if(audit.children[i]?.dataset.id===String(event.id))return;const tr=document.createElement('tr');tr.dataset.id=event.id;for(const text of [time(event.at),label[event.action]||event.action,(event.current||[]).join(':')]){const td=document.createElement('td');td.textContent=text;tr.append(td);}if(audit.children[i])audit.children[i].replaceWith(tr);else audit.append(tr);});
 }
 async function poll(){if(busy||document.hidden)return;busy=true;try{const response=await fetch(root.dataset.url+'?version='+encodeURIComponent(data?.version||''),{cache:'no-store'});if(response.status!==304){if(!response.ok)throw new Error();render(await response.json());}document.getElementById('stat-connection').textContent='Połączono';}catch(e){document.getElementById('stat-connection').textContent='Brak aktualizacji';}finally{busy=false;}}
 document.getElementById('stats-export').addEventListener('click',()=>{if(!data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='mecz-'+data.match_id+'-statystyki.json';a.click();URL.revokeObjectURL(url);});
 poll();setInterval(poll,2000);setInterval(duration,1000);
})();
