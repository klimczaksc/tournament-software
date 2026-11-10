/* UI-only translation. User names, form values and match data are never walked. */
(()=>{
 const data=window.UITranslations;if(!data)return;
 const {catalog,patterns}=data;let lang=document.documentElement.lang||'pl';
 const locales={pl:'pl-PL',en:'en-GB',de:'de-DE',fr:'fr-FR'};
 function text(value){const source=String(value??'');const trimmed=source.trim();if(source!==trimmed&&catalog[trimmed])return source.slice(0,source.length-source.trimStart().length)+(catalog[trimmed][lang]??trimmed)+source.slice(source.trimEnd().length);if(catalog[source])return catalog[source][lang]??source;
  for(const [pattern,key] of patterns){const match=source.match(new RegExp(pattern));if(match)return (catalog[key]?.[lang]||key).replace(/\{(\d+)\}/g,(_,i)=>match[Number(i)+1]??'');}
  return source;
 }
 function setLanguage(code){if(!locales[code]||(code===lang&&window.uiLocale===locales[code]))return;lang=code;document.documentElement.lang=code;window.uiLocale=locales[code];
  document.querySelectorAll('[data-ui-key]').forEach(el=>{el.textContent=text(el.dataset.uiKey);});
  document.querySelectorAll('[data-ui-attrs]').forEach(el=>{for(const [attr,key] of Object.entries(JSON.parse(el.dataset.uiAttrs)))el.setAttribute(attr,text(key));});
  document.querySelectorAll('.language-flag').forEach(el=>el.setAttribute('aria-pressed',String(el.value===code)));
 }
 window.uiText=text;window.uiLocale=locales[lang];window.TournamentI18n={text,setLanguage};
 document.addEventListener('tournament:updated',()=>{setLanguage(document.getElementById('tournament-language')?.dataset.language||lang);});
 document.addEventListener('DOMContentLoaded',()=>setLanguage(document.getElementById('tournament-language')?.dataset.language||lang));
})();
