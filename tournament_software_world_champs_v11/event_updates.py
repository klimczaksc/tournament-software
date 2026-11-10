"""Stateless HTTP deltas with bounded cursors; no long-lived Gunicorn threads."""
from collections import OrderedDict
from html.parser import HTMLParser
import hashlib
import json
import time
from flask import request, g, jsonify, abort, get_flashed_messages
from sqlalchemy import event


class Entities(HTMLParser):
    VOID = {'input','br','hr','img','meta','link','source','wbr','area','base','col','embed','param','track'}
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth=0; self.active=[]; self.entities={}; self.metadata={}
    def append(self, text):
        for capture in self.active: capture['parts'].append(text)
    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:self.depth+=1
        attrs=dict(attrs);key=attrs.get('data-event-key')
        if key:
            self.active.append(dict(key=key,tag=tag,depth=self.depth,parts=[]))
            self.metadata[key]=attrs
        self.append(self.get_starttag_text())
        if key and tag in self.VOID:self.finish(key)
    def handle_startendtag(self, tag, attrs):self.handle_starttag(tag,attrs)
    def finish(self,key):
        capture=next(c for c in self.active if c['key']==key)
        self.entities[key]=''.join(capture['parts']);self.active.remove(capture)
    def handle_endtag(self,tag):
        self.append('</'+tag+'>')
        for capture in list(self.active):
            if capture['depth']==self.depth and capture['tag']==tag:self.finish(capture['key'])
        if tag not in self.VOID:self.depth=max(0,self.depth-1)
    def handle_data(self,data):self.append(data)
    def handle_entityref(self,name):self.append('&'+name+';')
    def handle_charref(self,name):self.append('&#'+name+';')
    def handle_comment(self,data):self.append('<!--'+data+'-->')


def configure_event_updates(app, db, Tournament, settings_for, tournament_view):
    history=OrderedDict();built={}
    event.listen(db.session, 'after_commit', lambda _: built.clear())

    def snapshot(t, public):
        scope=(t.id,'public' if public else 'admin')
        cached=built.get(scope)
        if cached and time.monotonic()-cached[0]<1:return scope,cached[1]
        # Reuse the authoritative templates, extracting only explicitly keyed fragments.
        g.public_view=public and request.endpoint=='public_event_updates'
        parser=Entities();parser.feed(tournament_view(t.id))
        layout={'upcoming':[],'completed':[]}
        if public:
            for key,attrs in parser.metadata.items():
                if key.startswith('match:'):
                    layout['completed' if attrs.get('data-event-complete')=='1' else 'upcoming'].append(key)
        entity_hashes={}
        for key,value in parser.entities.items():
            if key in ('tree-shell','group-shell'):
                prefix='bracket:' if key=='tree-shell' else 'group:'
                for child,html in parser.entities.items():
                    if child.startswith(prefix):value=value.replace(html,'<entity key="'+child+'"></entity>')
            entity_hashes[key]=hashlib.sha256(value.encode()).hexdigest()
        cursor=hashlib.sha256(json.dumps([scope,entity_hashes,layout],sort_keys=True).encode()).hexdigest()
        result={'cursor':cursor,'entities':parser.entities,'hashes':entity_hashes,'layout':layout}
        built[scope]=(time.monotonic(),result)
        return scope,result

    def response(t,public):
        scope,current=snapshot(t,public)
        cursor=request.args.get('cursor','')[:64]
        if cursor==current['cursor']:return '',304
        old=history.get((scope,cursor))
        changed={key:html for key,html in current['entities'].items() if not old or old['hashes'].get(key)!=current['hashes'][key]}
        removed=[key for key in old['hashes'] if key not in current['hashes']] if old else []
        history[(scope,current['cursor'])]=current;history.move_to_end((scope,current['cursor']))
        while len(history)>64:history.popitem(last=False)
        return jsonify(cursor=current['cursor'],reset=not bool(old),entities=changed,removed=removed,layout=current['layout'] if not old or old['layout']!=current['layout'] else None)

    @app.route('/updates/<token>')
    def public_event_updates(token):
        import secrets
        t=next((t for t in Tournament.query.all() if settings_for(t).get('public_enabled') and secrets.compare_digest(settings_for(t).get('public_token',''),token)),None)
        if not t:abort(404)
        return response(t,True)

    @app.route('/tournament/<int:tournament_id>/updates')
    def tournament_event_updates(tournament_id):
        t=Tournament.query.get_or_404(tournament_id)
        return response(t,not (g.user and g.user.role=='admin'))

    @app.after_request
    def action_response(response):
        if request.headers.get('X-Tournament-Action')=='1' and request.endpoint in {'update_match_result','save_match_timing','referee_assignment','referee_reset','save_timetable','reschedule','configure_referee_panel'} and response.status_code in (301,302,303):
            messages=get_flashed_messages()
            success=('Result saved.','Zapisano czas meczu.','Zapisano przydział sędziego.','Wyzerowano panel punktowy','Zapisano timetable.','Court allocation updated.','Zapisano przeplataną','Zapisano ustawienia sędziów.')
            ok=any(any(phrase in m for phrase in success) for m in messages)
            response.set_data(json.dumps(dict(ok=ok,messages=messages),ensure_ascii=False))
            response.status_code=200 if ok else 422
            response.mimetype='application/json'
            response.headers.pop('Location',None)
            return response
        return response
