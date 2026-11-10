"""Explicit UI translations; tournament locale is shared by all its screens."""
import json
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit, unquote
from flask import g, request, redirect, abort, url_for, Response, render_template

LANGUAGES={'pl':'Polski','en':'English','de':'Deutsch','fr':'Français'}
LOCALES={'pl':'pl-PL','en':'en-GB','de':'de-DE','fr':'fr-FR'}
CATALOG=json.loads((Path(__file__).parent/'translations/ui.json').read_text())
PATTERNS=[
 (r'^Knockout pairings are locked because Match #(\d+) already has a user-entered result[.] Clear that result before changing the draw[.]$','Knockout pairings are locked because Match #{0} already has a user-entered result. Clear that result before changing the draw.'),
 (r'^This draw is locked because Match #(\d+) already has a saved result[.] Clear downstream results before reseeding this round[.]$','This draw is locked because Match #{0} already has a saved result. Clear downstream results before reseeding this round.'),
 (r'^Do zmiany: (.*) gra mecz #(\d+)$','Replacement needed: {0} plays match #{1}'),
 (r'^Group (\d+) #(\d+)$','Group {0} · place {1}'),
 (r'^Swiss Round (\d+)$','Swiss round {0}'),
 (r'^Set (\d+): enter both scores as whole numbers[.]$','Set {0}: enter both scores as whole numbers.'),
 (r'^Group (\d+)$','Group {0}'),(r'^Grupa (\d+)$','Group {0}'),
 (r'^Group Round (\d+)$','Group round {0}'),(r'^Round (\d+)$','Round {0}'),
 (r'^Places (\d+)-(\d+)$','Places {0}–{1}'),
 (r'^Winner #(\d+)$','Winner #{0}'),(r'^Loser #(\d+)$','Loser #{0}'),
 (r'^Best #(\d+) · rank (\d+)$','Best #{0} · rank {1}'),
 (r'^Przegrany meczu #(\d+) \(jedna osoba z drużyny\)$','Loser of match #{0} (one team member)'),
 (r'^Przegrany meczu #(\d+)$','Loser of match #{0}'),
]

def language():
    return getattr(g,'language','pl')

def translate(value):
    if value is None:return ''
    text=str(value);stripped=text.strip()
    if stripped != text and stripped in CATALOG:
        return text[:len(text)-len(text.lstrip())]+CATALOG[stripped].get(language(),stripped)+text[len(text.rstrip()):]
    entry=CATALOG.get(text)
    if entry:return entry.get(language(),text)
    for pattern,key in PATTERNS:
        match=re.fullmatch(pattern,text)
        if match:
            return CATALOG.get(key,{}).get(language(),key).format(*match.groups())
    # Keep compound round names, such as a preliminary placement match, readable.
    if ' - ' in text:
        parts=text.split(' - ')
        if all(part in CATALOG or any(re.fullmatch(p,part) for p,_ in PATTERNS) for part in parts):
            return ' — '.join(translate(part) for part in parts)
    return text


def configure_i18n(app,db,Tournament,Match,Phase,settings_for,save_settings):
    @app.before_request
    def choose_language():
        args=request.view_args or {};t=None
        if args.get('tournament_id') is not None:t=db.session.get(Tournament,args['tournament_id'])
        elif args.get('phase_id') is not None:
            phase=db.session.get(Phase,args['phase_id']);t=phase.tournament if phase else None
        elif args.get('match_id') is not None:
            match=db.session.get(Match,args['match_id']);t=match.tournament if match else None
        elif 'token' in args or 'slug' in args:
            import secrets
            for candidate in Tournament.query.all():
                st=settings_for(candidate)
                if st.get('public_enabled') and ((args.get('token') and secrets.compare_digest(st.get('public_token',''),args['token'])) or (args.get('slug') and st.get('public_slug')==args['slug'])):
                    t=candidate;break
        g.language_tournament=t
        saved=settings_for(t).get('language','pl') if t else request.cookies.get('ui_language','pl')
        g.language=saved if saved in LANGUAGES else 'pl'

    @app.context_processor
    def translated_context():
        return dict(_=translate,ui_language=language(),ui_languages=LANGUAGES,ui_locale=LOCALES[language()],ui_catalog=CATALOG,ui_patterns=PATTERNS,language_tournament=getattr(g,'language_tournament',None),ui_catalog_version=hashlib.sha256(json.dumps(CATALOG,ensure_ascii=False).encode()).hexdigest()[:12])
    app.jinja_env.filters['tr']=translate
    def referee_label(value):
        t=getattr(g,'language_tournament',None)
        if t and any(p.name==value for p in t.players):return value
        return translate(value)
    app.jinja_env.filters['tr_referee']=referee_label

    from werkzeug.exceptions import HTTPException
    @app.errorhandler(HTTPException)
    def translated_error(error):
        description=translate(error.description)
        if description==error.description and description not in CATALOG and language()!='en':
            description=translate('The request could not be completed. Check the data or contact the organiser.')
        return render_template('error.html',error=error,description=description),error.code

    @app.route('/ui/catalog.js')
    def ui_catalog_script():
        return Response('window.UITranslations='+app.json.dumps(dict(catalog=CATALOG,patterns=PATTERNS))+';',mimetype='application/javascript')

    @app.route('/language',methods=['POST'])
    def set_language():
        code=request.form.get('language')
        if code not in LANGUAGES:abort(400)
        tid=request.form.get('tournament_id')
        if tid:
            if not getattr(g,'user',None) or g.user.role!='admin':abort(403)
            if len(tid)>12 or not tid.isdigit():abort(400)
            t=db.session.get(Tournament,int(tid))
            if not t:abort(404)
            st=settings_for(t);st['language']=code;save_settings(t,st);db.session.commit()
            return redirect(url_for('tournament_view',tournament_id=t.id))
        destination=request.form.get('next','/')
        parts=urlsplit(destination)
        decoded=unquote(destination)
        if any(ord(c)<32 for c in destination) or decoded.startswith('//') or '\\' in decoded or parts.scheme or parts.netloc or not destination.startswith('/') or destination.startswith('//') or '\\' in destination:
            destination='/'
        response=redirect(destination)
        response.set_cookie('ui_language',code,max_age=365*86400,httponly=True,samesite='Lax',secure=request.is_secure)
        return response

    @app.after_request
    def translated_response(response):
        if response.is_json and request.endpoint in {'referee_state','referee_action','match_statistics_data','public_live_scores'}:
            payload=response.get_json(silent=True)
            if isinstance(payload,dict):
                payload['language']=language();response.set_data(app.json.dumps(payload))
        if request.endpoint=='ui_catalog_script':
            response.headers['Cache-Control']='public, max-age=31536000, immutable'
        else:response.headers.add('Vary','Cookie')
        return response
