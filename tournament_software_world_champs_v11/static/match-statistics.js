(() => {
 const T=window.uiText||((text)=>text);
 const root=document.getElementById('match-stats');if(!root)return;
 let data=null,busy=false;
 const label={start:'Start meczu',point:'Punkt',undo:'Cofnięcie punktu',finish:'Zatwierdzenie wyniku',reset:'Reset panelu',timeout_start:'Czas zawodnika (2 min)',timeout_end:'Zakończenie czasu'};
 const time=(at)=>at?new Date(at).toLocaleTimeString(window.uiLocale||'pl-PL',{timeZone:data.zone,hour:'2-digit',minute:'2-digit',second:'2-digit'}):T('Brak pomiaru czasu');
 function duration(){if(!data)return;let seconds=data.duration_seconds;if(seconds==null&&data.started_at&&!data.ended_at&&!data.complete)seconds=Math.max(0,(Date.now()-new Date(data.started_at).getTime())/1000);document.getElementById('stat-duration').textContent=seconds==null?T('Brak pełnego pomiaru'):(seconds/60).toFixed(1)+' min'+(!data.ended_at&&!data.complete?T(' · trwa'):'');}
 function render(incoming){
  const languageChanged=incoming.language&&incoming.language!==document.documentElement.lang;
  if(languageChanged){document.getElementById('stat-path').replaceChildren();document.getElementById('stat-audit').replaceChildren();}
  data=incoming;
  if(data.language)window.TournamentI18n?.setLanguage(data.language);
  duration();
  document.getElementById('stat-quality').textContent=data.quality==='first_point'?T('Pomiar przybliżony: od pierwszego zarejestrowanego punktu.'):data.quality==='legacy_unverified'?T('Starszy pomiar — moment startu niezweryfikowany.'):data.started_at?T('Start: ')+time(data.started_at)+(data.ended_at?T(' · koniec: ')+time(data.ended_at):T(' · mecz trwa')):T('Brak rzeczywistej godziny startu.');
  const e=data.estimate;
  document.getElementById('stat-estimate').textContent=e.count?T('Podobne mecze (ten sam limit, best of i typ fazy): ')+e.count+T(' · mediana ')+e.median+T(' min · środkowe 50%: ')+e.p25+'–'+e.p75+' min. '+(e.suggested?T('Sugerowany slot: ')+e.suggested+' min.':T('Sugestia slotu pojawi się od 5 pełnych pomiarów.')):T('Brak wystarczających pełnych pomiarów do estymacji. Standardowe 30 minut pozostaje ustawieniem organizatora.');
  const path=document.getElementById('stat-path');
  if(data.points_missing){if(path.textContent!==T('Brak zapisanej historii punkt po punkcie. Wynik końcowy nie pozwala jej odtworzyć.'))path.textContent=T('Brak zapisanej historii punkt po punkcie. Wynik końcowy nie pozwala jej odtworzyć.');}
  else{
   if(path.firstChild?.nodeType===3||path.querySelector('p'))path.replaceChildren();
   const bySet=new Map();data.path.forEach(p=>{if(!bySet.has(p.set))bySet.set(p.set,[]);bySet.get(p.set).push(p);});
   for(const [number,points] of bySet){
    let section=path.querySelector('[data-set="'+number+'"]');
    if(!section){
     section=document.createElement('section');section.dataset.set=number;
     const h=document.createElement('h3');section.append(h);
     const scroll=document.createElement('div');scroll.className='point-table-scroll';scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label',T('Przebieg punktów — set ')+number);
     const table=document.createElement('table');table.className='point-table';
     const head=document.createElement('thead');const row=document.createElement('tr');const label=document.createElement('th');label.textContent='Zawodnik / punkt';label.className='point-player';row.append(label);head.append(row);table.append(head);
     const body=document.createElement('tbody');
     for(let side=0;side<2;side++){const tr=document.createElement('tr');tr.dataset.side=side;const th=document.createElement('th');th.scope='row';th.className='point-player';tr.append(th);body.append(tr);}table.append(body);scroll.append(table);section.append(scroll);path.append(section);
    }
    section.querySelector('h3').textContent=T('Set ')+number+' · '+points[points.length-1].score.join(':');
    const header=section.querySelector('thead tr');
    points.forEach((point,i)=>{let cell=header.children[i+1];if(!cell){cell=document.createElement('th');cell.scope='col';header.append(cell);}cell.textContent=String(i+1);cell.title='Kolejny punkt w secie · '+time(point.at);});
    while(header.children.length>points.length+1)header.lastChild.remove();
    section.querySelectorAll('tbody tr').forEach((row,side)=>{
     row.firstElementChild.textContent=data.players[side];
     points.forEach((point,i)=>{let cell=row.children[i+1];if(!cell){cell=document.createElement('td');row.append(cell);}const scored=point.side===side,value=scored?String(point.score[side]):'';if(cell.textContent!==value)cell.textContent=value;cell.classList.toggle('point-won',scored);cell.title=scored?data.players[side]+T(' zdobywa punkt ')+point.score[side]+' · '+time(point.at):T('Punkt przeciwnika');cell.setAttribute('aria-label',scored?cell.title:T('Punkt przeciwnika — pusta kratka'));});
     while(row.children.length>points.length+1)row.lastChild.remove();
    });
   }
   for(const section of [...path.querySelectorAll('[data-set]')])if(!bySet.has(Number(section.dataset.set)))section.remove();
  }
  const audit=document.getElementById('stat-audit');
  data.audit.forEach((event,i)=>{if(audit.children[i]?.dataset.id===String(event.id))return;const tr=document.createElement('tr');tr.dataset.id=event.id;for(const text of [time(event.at),(T(label[event.action]||event.action))+(event.action.startsWith('timeout_')?' · '+data.players[event.side]+T(' (set ')+event.set:''),(event.current||[]).join(':')]){const td=document.createElement('td');td.textContent=text;tr.append(td);}if(audit.children[i])audit.children[i].replaceWith(tr);else audit.append(tr);});
 }
 async function poll(){if(busy||document.hidden)return;busy=true;try{const response=await fetch(root.dataset.url+'?version='+encodeURIComponent(data?.version||''),{cache:'no-store'});if(response.status!==304){if(!response.ok)throw new Error();render(await response.json());}document.getElementById('stat-connection').textContent=T('Połączono');}catch(e){document.getElementById('stat-connection').textContent=T('Brak aktualizacji');}finally{busy=false;}}
 document.getElementById('stats-export').addEventListener('click',()=>{if(!data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='mecz-'+data.match_id+'-statystyki.json';a.click();URL.revokeObjectURL(url);});
 poll();setInterval(poll,2000);setInterval(duration,1000);
})();
