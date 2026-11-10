(() => {
 const initial=document.getElementById('palette-initial'),catalogNode=document.getElementById('palette-catalog');if(!initial||!catalogNode)return;
 const catalog=JSON.parse(catalogNode.textContent),root=document.documentElement;
 const clone=value=>JSON.parse(JSON.stringify(value));
 const fields=['body','panel','panel2','text','muted','line','accent','danger'];
 const variables=[...fields,'surface','heading-muted','dangerText','accentText','link','flashBg','flashText','connector'];
 let saved=JSON.parse(initial.textContent),draft=clone(saved),dirty=false,editor=null;
 const hex=value=>{value=value.trim().toLowerCase();return /^#[0-9a-f]{6}$/.test(value)?value:/^#[0-9a-f]{3}$/.test(value)?'#'+[...value.slice(1)].map(c=>c+c).join(''):null;};
 const rgb=value=>value.slice(1).match(/../g).map(v=>parseInt(v,16));
 const lum=value=>rgb(value).map(c=>{c/=255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;}).reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
 const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
 const mix=(a,b,t)=>'#'+rgb(a).map((c,i)=>Math.round(c*(1-t)+rgb(b)[i]*t).toString(16).padStart(2,'0')).join('');
 const ink=bg=>ratio('#ffffff',bg)>ratio('#101010',bg)?'#ffffff':'#101010';
 function readable(color,bg){if(ratio(color,bg)>=4.5)return color;const target=ink(bg);for(let i=1;i<=20;i++){const candidate=mix(color,target,i/20);if(ratio(candidate,bg)>=4.5)return candidate;}return target;}
 function values(config){
  const mode=config.mode||root.dataset.theme||'light';
  if(config.id==='custom')return config.custom[mode];
  if(config.id!=='default'&&catalog[config.id])return catalog[config.id][mode];
  const css=getComputedStyle(root);return Object.fromEntries(fields.map(key=>[key,hex(css.getPropertyValue('--'+key))||catalog.forest[mode][key]]));
 }
 function apply(config){
  if(config.style)root.dataset.style=config.style;
  if(config.mode)root.dataset.theme=config.mode;
  variables.forEach(key=>root.style.removeProperty('--'+key));
  if(config.id==='default'){delete root.dataset.palette;if(typeof refreshThemeButton==='function')refreshThemeButton();return;}
  const c=values(config);root.dataset.palette=config.id;
  const vars={...c,surface:c.panel,'heading-muted':c.text,accentText:ink(c.accent),dangerText:ink(c.danger),link:readable(c.accent,c.body),flashBg:mix(c.panel,c.accent,.14),flashText:readable(c.text,mix(c.panel,c.accent,.14)),connector:c.muted};
  Object.entries(vars).forEach(([key,value])=>{if(hex(value))root.style.setProperty('--'+key,value);});
  if(typeof refreshThemeButton==='function')refreshThemeButton();
 }
 function show(){
  if(!editor)return;
  document.getElementById('palette-choice').value=draft.id;
  document.getElementById('palette-mode').value=draft.mode||root.dataset.theme||'light';
  document.getElementById('interface-style').value=draft.style;
  const c=values(draft);
  fields.forEach(key=>{document.querySelector('[data-color="'+key+'"]').value=c[key];const text=document.querySelector('[data-hex="'+key+'"]');if(document.activeElement!==text)text.value=c[key];});
  document.getElementById('custom-palette-json').value=JSON.stringify(draft.custom);
  const low=ratio(c.text,c.body)<4.5||ratio(c.text,c.panel)<4.5;
  document.getElementById('palette-preview-note').textContent=(dirty?'Podgląd — zapisz, aby zastosować na wszystkich ekranach. ':'Zapisana paleta turnieju. ')+(low?'Uwaga: tekst może być słabo czytelny przy wybranych kolorach.':'');
 }
 function preview(){dirty=true;apply(draft);show();}
 function fromServer(){const node=document.getElementById('tournament-palette');return node?JSON.parse(node.dataset.config):saved;}
 function sync(){
  const incoming=fromServer();if(JSON.stringify(incoming)===JSON.stringify(saved))return;
  saved=incoming;
  if(!dirty){draft=clone(saved);apply(saved);show();}
 }
 window.TournamentPalette={setMode(mode){draft.mode=mode;apply(draft);show();},saved(){saved=fromServer();draft=clone(saved);dirty=false;apply(saved);show();}};
 apply(saved);
 document.addEventListener('tournament:updated',sync);
 document.addEventListener('DOMContentLoaded',()=>{
  editor=document.getElementById('appearance-form');if(!editor)return;draft.mode=draft.mode||root.dataset.theme||'light';show();
  document.getElementById('palette-choice').addEventListener('change',e=>{draft.id=e.target.value;if(catalog[draft.id]?.mode)draft.mode=catalog[draft.id].mode;preview();});
  document.getElementById('palette-mode').addEventListener('change',e=>{draft.mode=e.target.value;preview();});
  document.getElementById('interface-style').addEventListener('change',e=>{draft.style=e.target.value;preview();});
  function edit(key,value){
   value=hex(value);if(!value)return;
   if(draft.id!=='custom'){
    const original=clone(draft);
    draft.custom={};for(const mode of ['light','dark']){apply({...original,mode});draft.custom[mode]={...values({...original,mode})};}
    draft.id='custom';
   }
   const mode=draft.mode||root.dataset.theme||'light';draft.custom[mode][key]=value;preview();
  }
  fields.forEach(key=>{document.querySelector('[data-color="'+key+'"]').addEventListener('input',e=>edit(key,e.target.value));document.querySelector('[data-hex="'+key+'"]').addEventListener('input',e=>edit(key,e.target.value));});
  document.getElementById('palette-cancel').addEventListener('click',()=>{dirty=false;draft=clone(saved);apply(saved);show();});
 });
})();
