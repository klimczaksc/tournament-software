"""Validated eight-colour palettes shared by all tournament views."""
import re,json
FIELDS={'body':'Tło strony','panel':'Karty i panele','panel2':'Pola i nagłówki','text':'Tekst główny','muted':'Tekst pomocniczy','line':'Obramowania','accent':'Akcent i przyciski','danger':'Błędy i ostrzeżenia'}
def colors(*values):return dict(zip(FIELDS,values))
PALETTES={
 'default':{'name':'Domyślna','mode':'light'},
 'forest':{'name':'Zieleń','mode':'light','light':colors('#f6f7f4','#ffffff','#f1f4ed','#26342c','#657269','#dce4da','#315f49','#b75648'),'dark':colors('#17201b','#202c24','#29362d','#ebf2e8','#a0ada1','#3b4b40','#8bbc99','#e09486')},
 'paper':{'name':'Papier','mode':'light','light':colors('#fafafa','#ffffff','#f1f1f1','#202020','#656565','#dddddd','#292929','#b44343'),'dark':colors('#181818','#232323','#303030','#f0f0f0','#b0b0b0','#474747','#dedede','#ec9696')},
 'stone':{'name':'Kamień','mode':'light','light':colors('#f5f2ed','#fffdfa','#eae5dd','#393630','#777065','#d9d1c5','#73614b','#b05242'),'dark':colors('#25231f','#302d28','#3e3932','#f2eade','#b8ad9e','#595044','#c7ad89','#e49a86')},
 'graphite':{'name':'Grafit','mode':'dark','light':colors('#eef0f2','#ffffff','#e2e6eb','#232933','#626d7a','#cdd4dd','#46556b','#b34545'),'dark':colors('#1c2026','#272d35','#343c47','#eef2f7','#b0bccb','#4b5665','#adbbd0','#ee9999')},
 'black':{'name':'Czerń','mode':'dark','light':colors('#f1f1f1','#ffffff','#e5e5e5','#101010','#595959','#c7c7c7','#101010','#b33c3c'),'dark':colors('#080808','#141414','#222222','#ffffff','#bcbcbc','#3d3d3d','#eeeeee','#ff9999')},
}
HEX=re.compile(r'^#[0-9a-fA-F]{6}$')
def palette_config(settings):
    settings=settings or {};pid=settings.get('palette_id','default')
    if pid not in (*PALETTES,'custom'):pid='default'
    mode=settings.get('palette_mode')
    if mode not in ('light','dark'):mode=None if pid=='default' else PALETTES.get(pid,PALETTES['forest']).get('mode','light')
    custom={}
    for theme in ('light','dark'):
        raw=settings.get('custom_palette',{})
        raw=raw.get(theme,{}) if isinstance(raw,dict) else {}
        custom[theme]={key:(raw.get(key).lower() if isinstance(raw.get(key),str) and HEX.fullmatch(raw[key]) else PALETTES['forest'][theme][key]) for key in FIELDS}
    return {'id':pid,'mode':mode,'custom':custom,'style':settings.get('interface_style','classic') if settings.get('interface_style') in ('classic','modern') else 'classic'}

def parse_palette(form,existing):
    pid=form.get('palette_id','default');mode=form.get('palette_mode','light')
    if pid not in (*PALETTES,'custom') or mode not in ('light','dark'):raise ValueError('Invalid palette')
    config=palette_config(existing)
    if form.get('custom_palette_json'):
        raw=json.loads(form['custom_palette_json'])
        if not isinstance(raw,dict) or set(raw)!={'light','dark'}:raise ValueError('Invalid palette')
        for theme in raw:
            if not isinstance(raw[theme],dict) or set(raw[theme])!=set(FIELDS):raise ValueError('Invalid palette')
            if any(not isinstance(value,str) or not HEX.fullmatch(value) for value in raw[theme].values()):raise ValueError('Invalid colour')
        config['custom']={theme:{key:raw[theme][key].lower() for key in FIELDS} for theme in raw}
    return {'palette_id':pid,'palette_mode':mode,'custom_palette':config['custom']}
