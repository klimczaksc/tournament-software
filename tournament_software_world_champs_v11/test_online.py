import os
import tempfile
os.environ['DATA_DIR'] = tempfile.mkdtemp()
os.environ['SETUP_TOKEN'] = 'test-only-token'
from app import app, db, Tournament, Match
from werkzeug.security import generate_password_hash
import re

app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
User = app.extensions['online_user']

def csrf(client, path='/login'):
    page=client.get(path)
    return re.search(r'const csrfToken=("[^"]+")', page.text)[1].strip('"')

def login(client, name, pwd):
    return client.post('/login', data=dict(username=name,password=pwd,csrf_token=csrf(client)))

def test_full_access_lifecycle():
    admin=app.test_client(); guest=app.test_client(); viewer=app.test_client()
    assert guest.get('/').status_code==302
    assert guest.get('/setup').status_code==404
    token=csrf(admin,'/setup?token=test-only-token')
    assert admin.post('/setup',data=dict(token='test-only-token',username='admin',password='StrongPassword123',csrf_token=token)).status_code==302
    assert guest.get('/setup?token=test-only-token').status_code==404
    assert login(admin,'admin','wrong').status_code==200
    assert login(admin,'admin','StrongPassword123').status_code==302
    token=csrf(admin,'/')
    assert admin.post('/create',data=dict(name='Test Cup',player_count=4,system='single_elimination',court_count=2,consolation='on',csrf_token=token)).status_code==302
    with app.app_context(): tid=Tournament.query.first().id
    path=f'/tournament/{tid}'
    assert admin.post(path+'/generate',data=dict(csrf_token=token)).status_code==302
    assert admin.get(path).status_code==200
    assert admin.post('/accounts',data=dict(username='reader',password='ReaderPassword123',csrf_token=token)).status_code==302
    assert login(viewer,'reader','ReaderPassword123').status_code==302
    page=viewer.get(path)
    assert page.status_code==200 and 'Save result' not in page.text and 'Tournament Draws' in page.text
    assert 'Delete' not in viewer.get('/').text
    assert viewer.get('/accounts').status_code==403
    assert viewer.get(path+'/export/db').status_code==403
    # Exercise EVERY existing write endpoint as guest and as viewer.
    for rule in app.url_map.iter_rules():
        if 'POST' not in rule.methods or rule.endpoint in {'login','setup','password','logout'}: continue
        target=rule.rule.replace('<int:tournament_id>',str(tid)).replace('<int:match_id>','1').replace('<int:phase_id>','1')
        assert guest.post(target).status_code==401, target
        assert viewer.post(target, data={'csrf_token':csrf(viewer,'/')}).status_code==403, target
    assert admin.post(path+'/delete').status_code==400 # missing CSRF rejected
    assert guest.get(path).status_code==302
    assert admin.post(path+'/publish',data=dict(published='on',csrf_token=token)).status_code==302
    with app.app_context():
        from app import settings_for
        public='/players/'+settings_for(db.session.get(Tournament,tid))['public_token']
    assert guest.get(public).status_code==200
    assert 'Save result' not in guest.get(public).text
    assert 'Link dla graczy' not in guest.get(public).text
    assert admin.get(public).status_code==200 and 'Save result' not in admin.get(public).text
    assert guest.get('/players/wrong').status_code==404
    # Change a result, ensure guest sees it immediately.
    with app.app_context(): mid=Match.query.filter(Match.player1_id.isnot(None),Match.player2_id.isnot(None)).first().id
    assert admin.post(f'/match/{mid}/result',data=dict(set_1_p1=21,set_1_p2=1,set_2_p1=21,set_2_p2=1,set_3_p1=21,set_3_p2=1,csrf_token=token)).status_code==302
    assert '21-1' in guest.get(public).text or '21:1' in guest.get(public).text
    assert admin.post(path+'/publish',data=dict(csrf_token=token)).status_code==302
    assert guest.get(public).status_code==404
    assert admin.post(path+'/publish',data=dict(published='on',csrf_token=token)).status_code==302
    assert guest.get(public).status_code==404 # old link stays revoked
    # Deactivation invalidates current sessions.
    with app.app_context(): uid=User.query.filter_by(username='reader').first().id
    admin.post('/accounts',data=dict(action='toggle',user_id=uid,csrf_token=token))
    assert viewer.get('/').status_code==302
    assert guest.get('/health').json=={'status':'ok'}

def test_formats_exports_and_import_privacy():
    from app import create_tournament, generate_structure, settings_for, save_settings_dict, export_database_json, import_database_json
    client=app.test_client()
    with app.app_context():
        uid=User.query.filter_by(role='admin').first().id
    with client.session_transaction() as s: s.update(uid=uid,version=1)
    for system in ('single_elimination','group_knockout','round_robin','double_elimination','swiss'):
        with app.app_context():
            t=create_tournament('Format '+system,8,system,True,2)
            generate_structure(t)
            tid=t.id
        assert client.get(f'/tournament/{tid}').status_code==200
        with client.session_transaction() as s: s.clear()
        with app.app_context():
            t=db.session.get(Tournament,tid)
            data=settings_for(t);data.update(public_enabled=True,public_token='token-'+system);save_settings_dict(t,data);db.session.commit()
        assert client.get('/players/token-'+system).status_code==200
        with client.session_transaction() as s: s.update(uid=uid,version=1)
    for export in ('pdf','groups_pdf','schedule_pdf','final_standings_pdf','excel'):
        r=client.get(f'/tournament/{tid}/export/{export}')
        assert r.status_code==200 and len(r.data)>100, export
    with app.app_context():
        payload=export_database_json(db.session.get(Tournament,tid))
        imported=import_database_json(payload)
        # importer returns a tournament instance
        assert not settings_for(imported).get('public_enabled')
        assert not settings_for(imported).get('public_token')
