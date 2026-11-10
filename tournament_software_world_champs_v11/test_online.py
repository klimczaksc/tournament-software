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
    assert admin.post('/setup',data=dict(token='test-only-token',username='admin',password='1234567',csrf_token=token)).status_code==200
    assert admin.post('/setup',data=dict(token='test-only-token',username='admin',password='Abc123!x',csrf_token=token)).status_code==302
    assert guest.get('/setup?token=test-only-token').status_code==404
    assert login(admin,'admin','wrong').status_code==200
    assert login(admin,'admin','Abc123!x').status_code==302
    token=csrf(admin,'/')
    assert admin.post('/create',data=dict(name='Test Cup',player_count=4,system='single_elimination',court_count=2,consolation='on',csrf_token=token)).status_code==302
    with app.app_context(): tid=Tournament.query.first().id
    path=f'/tournament/{tid}'
    assert admin.post(path+'/generate',data=dict(csrf_token=token)).status_code==302
    assert admin.get(path).status_code==200
    assert admin.post('/accounts',data=dict(username='reader',password='Read123!',csrf_token=token)).status_code==302
    assert login(viewer,'reader','Read123!').status_code==302
    page=viewer.get(path)
    assert page.status_code==200 and 'Save result' not in page.text and 'Tournament Draws' in page.text
    assert 'Delete' not in viewer.get('/').text
    assert viewer.get('/accounts').status_code==403
    assert viewer.get(path+'/export/db').status_code==403
    # Exercise EVERY existing write endpoint as guest and as viewer.
    for rule in app.url_map.iter_rules():
        if 'POST' not in rule.methods or rule.endpoint in {'login','setup','password','logout','referee_access','referee_action'}: continue
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


def test_https_forms_keep_referer_and_csrf_protection():
    client = app.test_client()
    page = client.get('/login', base_url='https://tournament.test')
    assert page.headers['Referrer-Policy'] == 'same-origin'
    token = re.search(r'const csrfToken=("[^"]+")', page.text)[1].strip('"')
    data = dict(username='unknown', password='invalid-password', csrf_token=token)
    # Browser submits the same-origin Referer under the returned policy.
    response = client.post('/login', base_url='https://tournament.test', data=data,
        headers={'Referer': 'https://tournament.test/login'})
    assert response.status_code == 200
    assert 'Nieprawidłowy login' in response.text
    assert client.post('/login', base_url='https://tournament.test', data=data).status_code == 400
    assert client.post('/login', base_url='https://tournament.test', data=data,
        headers={'Referer': 'https://other.test/'}).status_code == 400
    assert client.post('/login', base_url='https://tournament.test', data={'username':'unknown'},
        headers={'Referer': 'https://tournament.test/login'}).status_code == 400


def test_tournament_appearance_is_shared_persistent_and_isolated():
    from app import create_tournament, generate_structure, settings_for
    admin = app.test_client()
    assert login(admin, 'admin', 'Abc123!x').status_code == 302
    token = csrf(admin, '/')
    with app.app_context():
        t = create_tournament('Appearance Cup', 4, 'single_elimination', True, 2)
        generate_structure(t)
        tid = t.id
        other = create_tournament('Separate Cup', 4, 'single_elimination', True, 1).id
        before = [(m.id,m.score_json,m.player1_id,m.player2_id,m.order_index) for m in Match.query.filter_by(tournament_id=tid).all()]
    path = f'/tournament/{tid}'
    assert 'data-style="classic"' in admin.get(path).text
    assert admin.post(path+'/appearance', data={'interface_style':'modern','csrf_token':token}).status_code == 302
    html = admin.get(path).text
    assert 'data-style="modern"' in html and 'Zapisz styl' in html
    assert 'data-style="modern"' in admin.get('/').text
    assert 'data-style="classic"' in admin.get(f'/tournament/{other}').text
    assert admin.post(path+'/appearance', data={'interface_style':'invalid','csrf_token':token}).status_code == 400
    admin.post(path+'/publish',data={'published':'on','csrf_token':token})
    with app.app_context():
        t = db.session.get(Tournament, tid)
        assert settings_for(t)['interface_style'] == 'modern'
        public = '/players/'+settings_for(t)['public_token']
        after = [(m.id,m.score_json,m.player1_id,m.player2_id,m.order_index) for m in Match.query.filter_by(tournament_id=tid).all()]
        assert before == after
        reader = User.query.filter_by(username='reader').first()
        reader.active = True
        db.session.commit()
    guest = app.test_client()
    assert 'data-style="modern"' in guest.get(public).text
    assert 'Zapisz styl' not in guest.get(public).text
    reader_client = app.test_client()
    login(reader_client, 'reader', 'Read123!')
    assert 'data-style="modern"' in reader_client.get(path).text
    assert reader_client.post(path+'/appearance',data={'interface_style':'classic','csrf_token':csrf(reader_client,'/')}).status_code == 403
    assert admin.post(path+'/appearance',data={'interface_style':'classic','csrf_token':token}).status_code == 302
    assert 'data-style="classic"' in guest.get(public).text
    assert 'data-style="classic"' in admin.get(path).text


def test_pending_placement_fixture_preserves_groups_and_finishes_all_places():
    from pathlib import Path
    from app import import_database_json, propagate_all, meta_for, set_meta, placement_map, tournament_is_complete, score_sets
    payload = (Path(__file__).parent/'fixtures/pending_placement_13.json').read_text()
    raw = __import__('json').loads(payload)
    expected_groups = [(m['order_index'], m['score_json'], m['winner_seed']) for m in raw['matches'] if m['bracket'].startswith('group_')]
    with app.app_context():
        t = import_database_json(payload) # Includes safe legacy repair; IDs differ from source DB.
        by_number = {m.order_index: m for m in t.matches}
        groups = [(m.order_index, m.score_json, m.winner.seed) for m in t.matches if m.bracket.startswith('group_')]
        assert groups == expected_groups
        assert by_number[33].player1.seed == 10
        assert by_number[33].player2_id is None and by_number[33].winner_id is None
        assert by_number[38].player1_id is None and by_number[38].player2_id is None
        assert by_number[38].winner_id is None
        assert placement_map(t) == {}
        assert not tournament_is_complete(t)
        # Every participant in the imported championship remains in this tournament.
        own_ids = {p.id for p in t.players}
        for number in (23,24,25,26):
            assert by_number[number].player1_id in own_ids and by_number[number].player2_id in own_ids
        def record(m):
            assert m.player1_id and m.player2_id
            m.score_json = '[[15, 5], [15, 5]]'
            m.winner_id, m.loser_id = m.player1_id, m.player2_id
            md = meta_for(m); md['user_result_entered'] = True; set_meta(m,md)
            db.session.commit(); propagate_all(t.id)
        # Resolving #27 supplies the missing player in #33; it does not award a win there.
        record(by_number[27])
        assert by_number[33].player2_id == by_number[27].winner_id
        assert by_number[33].winner_id is None and by_number[38].player2_id is None
        # Finish the rest and verify a unique exact ranking of all thirteen players.
        for _ in range(50):
            playable = [m for m in t.matches if m.player1_id and m.player2_id and not m.winner_id]
            if not playable: break
            record(playable[0])
        assert tournament_is_complete(t)
        places = placement_map(t)
        assert set(places) == own_ids and sorted(places.values()) == list(range(1,14))
        assert places[by_number[27].loser_id] == 13
        groups_after = [(m.order_index, m.score_json, m.winner.seed) for m in t.matches if m.bracket.startswith('group_')]
        assert groups_after == expected_groups


def test_proven_structural_byes_still_advance():
    from app import create_tournament, add_match, propagate_all, meta_for
    with app.app_context():
        t = create_tournament('Structural BYE', 2, 'single_elimination', True, 1)
        player = t.players[0]
        phase = t.phases[0]
        a = add_match(t.id,phase.id,1,'main','BYE',{'kind':'player','player_id':player.id},{'kind':'empty'},'Championship',1,2,0,0,'bye_a')
        b = add_match(t.id,phase.id,2,'main','Next',{'kind':'winner','match_key':'bye_a'},{'kind':'empty'},'Championship',1,2,1,0,'bye_b')
        db.session.commit(); propagate_all(t.id)
        assert a.winner_id == player.id and b.winner_id == player.id


def test_short_public_links_navigation_and_revocation():
    from app import create_tournament, settings_for
    admin=app.test_client(); login(admin,'admin','Abc123!x'); token=csrf(admin,'/')
    with app.app_context():
        tid=create_tournament('Puchar Łódź 2026',4,'single_elimination',True,1).id
    path=f'/tournament/{tid}'
    admin.post(path+'/publish', data={'published':'on','csrf_token':token})
    with app.app_context():
        settings=settings_for(db.session.get(Tournament,tid))
        slug=settings['public_slug']; old='/players/'+settings['public_token']
        assert slug.startswith('puchar-lodz-2026-') and len(slug)<40
    guest=app.test_client()
    page=guest.get('/t/'+slug)
    assert page.status_code==200
    assert 'aria-label="Na górę"' in page.text and 'aria-label="Na dół"' in page.text
    assert guest.get(old).status_code==200
    assert '/t/'+slug in admin.get(path).text
    admin.post(path+'/publish',data={'csrf_token':token})
    assert guest.get('/t/'+slug).status_code==404 and guest.get(old).status_code==404
    admin.post(path+'/publish',data={'published':'on','csrf_token':token})
    assert guest.get('/t/'+slug).status_code==404
    with app.app_context():
        assert settings_for(db.session.get(Tournament,tid))['public_slug'] != slug


def test_excluding_bottom_changes_wildcard_without_changing_group_tables():
    import json
    from pathlib import Path
    from app import (import_database_json, compute_group_tables, best_group_position_rows,
                     settings_for, save_settings_dict, comparison_metrics, resolve_source,
                     championship_qualifier_rows, tournament_seed_rows)
    raw=json.loads((Path(__file__).parent/'fixtures/pending_placement_13.json').read_text())
    settings=json.loads(raw['tournament']['settings_json'])
    settings['best_next_place_qualifiers']=1
    raw['tournament']['settings_json']=json.dumps(settings)
    with app.app_context():
        t=import_database_json(json.dumps(raw))
        def snapshot(tables):
            return [(key,[(r['player'].seed,r['points'],r['matches'],r['sets_won'],r['sets_lost'],r['point_diff']) for r in rows]) for key,rows in tables]
        tables=compute_group_tables(t)
        original=snapshot(tables)
        assert best_group_position_rows(tables,3)[0][1]['player'].seed == 7
        settings=settings_for(t);settings['wildcard_comparison']='exclude_bottom';save_settings_dict(t,settings);db.session.commit()
        adjusted=compute_group_tables(t)
        assert snapshot(adjusted)==original
        # Original 3rd place in the five-person group remains the candidate.
        row=dict(adjusted)['group_1'][2]
        metrics=comparison_metrics(row)
        assert row['player'].seed==7 and row['matches']==4 and row['wins']==2
        assert metrics['matches']==3 and metrics['wins']==1
        assert (metrics['sets_won'],metrics['sets_lost'])==(2,4)
        assert metrics['point_diff']==-10
        # Exclude the FINAL last place (seed 12), not the lowest original seed (13).
        assert row['excluded_opponents']==['Player 12']
        assert best_group_position_rows(adjusted,3)[0][1]['player'].seed==3
        first=resolve_source({'kind':'best_group_pos','pos':3,'rank':1},t.id,{},dict(adjusted),True)
        assert db.session.get(__import__('app').Player,first).seed==3
        qualifiers=championship_qualifier_rows(t)
        assert [q['player'].seed for q in qualifiers if q['wildcard_rank']]==[3]
        seeds=tournament_seed_rows(t)
        normalized=next(r for r in seeds if r['player'].seed==7)
        assert normalized['ppm']==2/3 and normalized['set_diff_pm']==-2/3
        # Turning the method off reproduces the original wildcard ranking.
        settings['wildcard_comparison']='ppm';save_settings_dict(t,settings);db.session.commit()
        assert best_group_position_rows(compute_group_tables(t),3)[0][1]['player'].seed==7


def test_wildcard_option_saved_before_results_and_locked_afterwards():
    from app import create_tournament, generate_structure, settings_for
    admin=app.test_client();login(admin,'admin','Abc123!x');token=csrf(admin,'/')
    with app.app_context():
        t=create_tournament('Wildcard settings',13,'group_knockout',True,2);tid=t.id
        assert settings_for(t)['wildcard_comparison']=='ppm'
    path=f'/tournament/{tid}'
    fields={'wildcard_comparison':'exclude_bottom','group_count':3,'qualifiers_per_group':2,'best_next_place_qualifiers':2,'consolation':'on','generate_after':'1','csrf_token':token}
    assert admin.post(path+'/settings',data=fields).status_code==302
    with app.app_context():
        t=db.session.get(Tournament,tid)
        assert settings_for(t)['wildcard_comparison']=='exclude_bottom'
        assert len(t.matches)>0
        m=next(m for m in t.matches if m.bracket.startswith('group_'))
        mid=m.id
    assert admin.post(f'/match/{mid}/result',data={'set_1_p1':21,'set_1_p2':5,'set_2_p1':21,'set_2_p2':5,'csrf_token':token}).status_code==302
    html=admin.get(path).text
    assert 'Metoda jest zablokowana' in html
    fields.update(wildcard_comparison='ppm',generate_after='0',name='Must not change')
    assert admin.post(path+'/settings',data=fields).status_code==302
    with app.app_context():
        t=db.session.get(Tournament,tid)
        assert settings_for(t)['wildcard_comparison']=='exclude_bottom'
        assert t.name=='Wildcard settings'
    fields['wildcard_comparison']='invalid'
    assert admin.post(path+'/settings',data=fields).status_code==400


def test_interleaved_schedule_dependencies_closing_matches_and_scores():
    import json
    from pathlib import Path
    from app import import_database_json, assign_schedule, meta_for, closing_match_kind
    raw=json.loads((Path(__file__).parent/'fixtures/pending_placement_13.json').read_text())
    with app.app_context():
        t=import_database_json(json.dumps(raw))
        groups_before={m.id:(m.order_index,m.score_json,m.winner_id) for m in t.matches if m.bracket.startswith('group_')}
        original_ids={m.id for m in t.matches}
        for courts in (2,3,1,4):
            t.court_count=courts
            assign_schedule(t,renumber=True)
            matches=sorted(t.matches,key=lambda m:m.order_index)
            assert {m.id for m in matches}==original_ids
            assert [closing_match_kind(m) for m in matches[-2:]]==['bronze','final']
            assert meta_for(matches[-2])['schedule_wave'] < meta_for(matches[-1])['schedule_wave']
            assert matches[-1].court_number==1
            keyed={meta_for(m).get('key'):m for m in matches if meta_for(m).get('key')}
            waves={}
            for m in matches:
                md=meta_for(m);wave=md['schedule_wave']
                waves.setdefault(wave,[]).append(m)
                for src in md.get('sources',[]):
                    if src.get('kind') in ('winner','loser'):
                        dep=keyed[src['match_key']]
                        assert dep.order_index<m.order_index
                        assert meta_for(dep)['schedule_wave']<wave
            for batch in waves.values():
                assert len(batch)<=courts
                assert len({m.court_number for m in batch})==len(batch)
                players=[pid for m in batch for pid in (m.player1_id,m.player2_id) if pid]
                assert len(players)==len(set(players))
            if courts==2:
                assert any(any(meta_for(m).get('place_start')==1 for m in batch) and any((meta_for(m).get('place_start') or 0)>3 for m in batch) for batch in waves.values())
            assert {m.id:(m.order_index,m.score_json,m.winner_id) for m in t.matches if m.bracket.startswith('group_')}==groups_before
            numbers={m.id:m.order_index for m in matches}
            assign_schedule(t,renumber=False)
            assert {m.id:m.order_index for m in t.matches}==numbers


def test_schedule_reordering_refuses_started_knockout():
    from app import create_tournament, generate_structure, meta_for
    admin=app.test_client();login(admin,'admin','Abc123!x');token=csrf(admin,'/')
    with app.app_context():
        t=create_tournament('Started bracket',8,'single_elimination',True,2)
        generate_structure(t);tid=t.id
        match=next(m for m in t.matches if m.player1_id and m.player2_id)
        mid=match.id
    admin.post(f'/match/{mid}/result',data={'set_1_p1':21,'set_1_p2':0,'set_2_p1':21,'set_2_p2':0,'set_3_p1':21,'set_3_p2':0,'csrf_token':token})
    with app.app_context():
        t=db.session.get(Tournament,tid)
        before={m.id:(m.order_index,m.score_json,m.winner_id) for m in t.matches}
    assert admin.post(f'/tournament/{tid}/schedule',data={'reorder':'1','csrf_token':token}).status_code==302
    with app.app_context():
        t=db.session.get(Tournament,tid)
        assert {m.id:(m.order_index,m.score_json,m.winner_id) for m in t.matches}==before


def test_live_timetable_parallel_courts_delay_manual_floor_and_dependencies():
    from datetime import datetime
    from types import SimpleNamespace
    from timetable import build_timetable
    from app import closing_match_kind
    def match(i,court,p1,p2,**md):
        return SimpleNamespace(id=i,order_index=i,court_number=court,player1_id=p1,player2_id=p2,
                               winner_id=None,bracket='main',notes=__import__('json').dumps(md))
    meta=lambda m: __import__('json').loads(m.notes)
    a=match(1,1,1,2,key='a',actual_start='2030-05-01T10:00')
    b=match(2,2,3,4,key='b')
    c=match(3,1,5,6,key='c')
    d=match(4,2,None,7,key='d',sources=[{'kind':'winner','match_key':'a'}])
    bronze=match(5,1,8,9,place_start=3,place_end=4)
    final=match(6,2,10,11,place_start=1,place_end=2)
    t=SimpleNamespace(system='single_elimination')
    settings={'schedule_start':'2030-05-01T10:00','match_minutes':30}
    now=datetime(2030,5,1,10,45)
    slots=build_timetable(t,[a,b,c,d,bronze,final],settings,meta,closing_match_kind,now)
    assert slots[1]['end']==datetime(2030,5,1,10,46) # Ongoing overtime blocks its court.
    assert slots[2]['start']==now # Another court can start independently.
    assert slots[3]['start']==slots[1]['end']
    assert slots[4]['start']>=slots[1]['end'] and slots[4]['start']>=slots[2]['end']
    assert slots[5]['start']>=max(slots[i]['end'] for i in (1,2,3,4))
    assert slots[6]['start']>=slots[5]['end']
    # A real finish releases the court. The other court keeps its own allocation.
    a.winner_id=1;a.notes=__import__('json').dumps({'key':'a','actual_start':'2030-05-01T10:00','actual_end':'2030-05-01T10:45'})
    c.notes=__import__('json').dumps({'key':'c','manual_start':'2030-05-01T11:30'})
    revised=build_timetable(t,[a,b,c,d,bronze,final],settings,meta,closing_match_kind,now)
    assert revised[2]['start']==slots[2]['start']
    assert revised[3]['start']==datetime(2030,5,1,11,30)
    c.notes=__import__('json').dumps({'key':'c','manual_start':'2030-05-01T10:15'})
    revised=build_timetable(t,[a,b,c,d,bronze,final],settings,meta,closing_match_kind,now)
    assert revised[3]['start']==now and revised[3]['shifted']
    # A player cannot be double-booked, even across different courts.
    c.player1_id=3
    revised=build_timetable(t,[a,b,c,d,bronze,final],settings,meta,closing_match_kind,now)
    assert revised[3]['start']>=revised[2]['end']


def test_live_timetable_groups_wait_before_knockout_and_byes_take_no_time():
    from datetime import datetime
    from pathlib import Path
    from app import import_database_json, meta_for, closing_match_kind, save_settings_dict, settings_for
    from timetable import build_timetable
    with app.app_context():
        t=import_database_json((Path(__file__).parent/'fixtures/pending_placement_13.json').read_text())
        settings=settings_for(t);settings.update(schedule_start='2030-05-01T10:00',match_minutes=30)
        save_settings_dict(t,settings);db.session.commit()
        slots=build_timetable(t,list(t.matches),settings,meta_for,closing_match_kind,datetime(2030,5,1,9))
        group_end=max(slots[m.id]['end'] for m in t.matches if m.bracket.startswith('group_'))
        for m in t.matches:
            if not m.bracket.startswith('group_') and not m.winner_id:
                assert slots[m.id]['start']>=group_end
            for src in meta_for(m).get('sources',[]):
                if src.get('kind') in ('winner','loser'):
                    dep=next(x for x in t.matches if meta_for(x).get('key')==src['match_key'])
                    assert slots[m.id]['start']>=slots[dep.id]['end']


def test_timing_admin_controls_record_finish_once_and_public_sections():
    from app import create_tournament, generate_structure, meta_for, settings_for
    admin=app.test_client();login(admin,'admin','Abc123!x');token=csrf(admin,'/')
    with app.app_context():
        t=create_tournament('Live Clock Cup',8,'single_elimination',True,2);generate_structure(t);tid=t.id
        mids=[m.id for m in t.matches if m.player1_id and m.player2_id and not m.winner_id]
    path=f'/tournament/{tid}'
    assert admin.post(path+'/timetable',data={'schedule_start':'2030-05-01T10:00','match_minutes':'0','csrf_token':token}).status_code==400
    assert admin.post(path+'/timetable',data={'schedule_start':'bad','csrf_token':token}).status_code==400
    assert admin.post(path+'/timetable',data={'schedule_start':'2030-05-01T10:00','schedule_timezone':'not/a/zone','csrf_token':token}).status_code==400
    assert admin.post(path+'/timetable',data={'schedule_start':'2030-05-01T10:00','match_minutes':'30','schedule_timezone':'Europe/Warsaw','csrf_token':token}).status_code==302
    assert 'Edytuj godziny meczu' in admin.get(path).text
    assert admin.post(f'/match/{mids[0]}/timing',data={'action':'start','csrf_token':token}).status_code==302
    payload={'set_1_p1':21,'set_1_p2':1,'set_2_p1':21,'set_2_p2':1,'csrf_token':token}
    assert admin.post(f'/match/{mids[0]}/result',data=payload).status_code==302
    with app.app_context():
        md=meta_for(db.session.get(Match,mids[0]));finish=md['actual_end'];assert md.get('actual_start')
    assert admin.post(f'/match/{mids[0]}/result',data=payload).status_code==302
    with app.app_context(): assert meta_for(db.session.get(Match,mids[0]))['actual_end']==finish
    # Finish time cannot be added to an unresolved match, or be in the future.
    assert admin.post(f'/match/{mids[1]}/timing',data={'actual_end':'2020-01-01T10:00','csrf_token':token}).status_code==400
    assert admin.post(f'/match/{mids[1]}/timing',data={'actual_start':'2099-01-01T10:00','csrf_token':token}).status_code==400
    # A manual correction remains visible in the admin; public cards omit actual timing.
    assert admin.post(f'/match/{mids[0]}/timing',data={'actual_start':'2020-01-01T10:00','actual_end':'2020-01-01T10:45','csrf_token':token}).status_code==302
    admin.post(path+'/publish',data={'published':'on','csrf_token':token})
    with app.app_context(): public='/t/'+settings_for(db.session.get(Tournament,tid))['public_slug']
    guest=app.test_client();page=guest.get(public).text
    next_section=page.split('<div class="next-matches" data-event-list="next">')[1].split('<details class="section" id="more-upcoming"')[0]
    assert next_section.count('<article ')==5
    assert 'id="more-upcoming"' in page and 'id="results" data-view-state' in page
    assert '01.01 10:45' in admin.get(path).text
    assert '2030' not in page # rendered clocks show day/month, not ISO fields
    assert 'Start teraz' not in page and 'Edytuj godziny' not in page
    assert guest.get(public+'?display=1').status_code==200
    assert 'Pełny ekran' in guest.get(public+'?display=1').text
    assert guest.post(f'/match/{mids[0]}/timing').status_code==401
    for export in ('schedule_pdf','excel'):
        assert admin.get(path+'/export/'+export).status_code==200


def test_in_place_controls_and_clear_public_monitor_statuses():
    from app import create_tournament,generate_structure,settings_for,save_settings_dict
    admin=app.test_client()
    with app.app_context(): uid=User.query.filter_by(role='admin').first().id
    with admin.session_transaction() as session: session.update(uid=uid,version=1)
    token=csrf(admin,'/')
    with app.app_context():
        t=create_tournament('In-place controls',8,'single_elimination',True,2);generate_structure(t);tid=t.id
        md=settings_for(t);md.update(schedule_start='2026-01-01T10:00',public_enabled=True,public_token='in-place-public',public_slug='in-place-public')
        save_settings_dict(t,md);db.session.commit()
        mid=next(m.id for m in t.matches if m.player1_id and m.player2_id and not m.winner_id)
    html=admin.get(f'/tournament/{tid}').text
    assert 'static/admin-match-updates.js' in html and 'data-player1=' in html
    response=admin.post(f'/match/{mid}/timing',data={'action':'start','csrf_token':token},follow_redirects=True)
    assert response.status_code==200 and 'Zapisano czas meczu.' in response.text
    assert f'id="match-{mid}"' in response.text
    guest=app.test_client()
    assert guest.get('/static/admin-match-updates.js').status_code==200
    public=guest.get('/players/in-place-public?display=1').text
    assert 'match-status-live' in public and 'W trakcie' in public
    assert 'start rzeczywisty' not in public
    ongoing=public.split(f'data-match-id="{mid}"')[1].split('</article>')[0]
    assert 'match-time' not in ongoing # Actual start remains in the admin only.
    assert 'match-time' in public # Waiting matches retain their planned hours.


def referee_fixture(players=4, system='single_elimination'):
    from app import create_tournament,generate_structure,settings_for,save_settings_dict
    admin=app.test_client()
    with app.app_context(): uid=User.query.filter_by(role='admin').first().id
    with admin.session_transaction() as s:s.update(uid=uid,version=1)
    token=csrf(admin,'/')
    with app.app_context():
        t=create_tournament('Referee Cup',players,system,True,2);generate_structure(t)
        for ph in t.phases:ph.points_to=3;ph.best_of=3
        md=settings_for(t);md.update(public_enabled=True,public_token='ref-'+str(t.id),public_slug='ref-'+str(t.id),schedule_start='2026-01-01T10:00')
        save_settings_dict(t,md);db.session.commit();tid=t.id
        mid=next(m.id for m in t.matches if m.player1_id and m.player2_id and not m.winner_id)
    assert admin.post(f'/tournament/{tid}/referees',data={'enabled':'on','csrf_token':token}).status_code==302
    with app.app_context(): code=app.extensions['referee_score'].query.get(mid).desk_code
    return admin,token,tid,mid,code


def test_referee_codes_scope_csrf_live_points_undo_and_official_propagation():
    import json
    from app import meta_for
    admin,admin_token,tid,mid,code=referee_fixture()
    assert len(code)==3 and code.isdigit()
    referee=app.test_client();outsider=app.test_client()
    assert referee.get(f'/referee/{mid}').status_code==200
    assert 'inputmode="numeric"' in referee.get(f'/referee/{mid}').text
    token=csrf(referee,f'/referee/{mid}')
    assert referee.post(f'/referee/{mid}/access',data={'code':code}).status_code==400
    wrong='999' if code!='999' else '998'
    assert referee.post(f'/referee/{mid}/access',data={'code':wrong,'csrf_token':token}).status_code==403
    assert referee.get(f'/referee/{mid}/state').status_code==403
    assert referee.post(f'/referee/{mid}/action',json={'revision':0,'action':'point','side':0},headers={'X-CSRFToken':token}).status_code==403
    assert referee.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token}).status_code==302
    state=referee.get(f'/referee/{mid}/state').json
    def action(kind,side=None,revision=None):
        nonlocal state
        r=referee.post(f'/referee/{mid}/action',json={'revision':state['revision'] if revision is None else revision,'action':kind,'side':side},headers={'X-CSRFToken':token})
        if r.status_code==200:state=r.json
        return r
    assert action('point',0).status_code==200 and state['current']==[1,0]
    with app.app_context():
        m=db.session.get(Match,mid);assert m.score_json=='[]' and not m.winner_id and meta_for(m).get('actual_start')
    public=outsider.get('/live/ref-'+str(tid)).json
    assert public['scores'][str(mid)]['current']==[1,0]
    assert 'code' not in json.dumps(public) and 'events' not in json.dumps(public)
    assert 'Kod sędziego' not in outsider.get('/players/ref-'+str(tid)).text
    assert 'Sędzia:' in outsider.get('/players/ref-'+str(tid)).text
    # A stale tab / repeated delivery must not add a second point.
    assert action('point',0,revision=0).status_code==409
    assert action('undo').status_code==200 and state['current']==[0,0]
    assert action('finish').status_code==409
    # Deuce: 2:2 -> 3:2 does not finish a set; 4:2 does.
    for side in [0,1,0,1,0]:assert action('point',side).status_code==200
    assert state['sets']==[] and state['current']==[3,2]
    assert action('point',0).status_code==200 and state['sets']==[[4,2]]
    assert action('undo').status_code==200 and state['sets']==[] and state['current']==[3,2]
    assert action('point',0).status_code==200
    for _ in range(3):assert action('point',0).status_code==200
    assert state['awaiting_confirmation'] and state['sets']==[[4,2],[3,0]]
    assert action('point',1).status_code==409
    with app.app_context(): assert db.session.get(Match,mid).winner_id is None
    assert action('finish').status_code==200 and state['winner_id'] and state['finalized']
    with app.app_context():
        m=db.session.get(Match,mid);assert m.winner_id==m.player1_id and json.loads(m.score_json)==[[4,2],[3,0]]
        assert any(meta_for(x).get('sources') and m.winner_id in (x.player1_id,x.player2_id) for x in m.tournament.matches if x.id!=m.id)
    assert action('undo').status_code==409
    assert outsider.get('/live/ref-'+str(tid)).json['scores'][str(mid)]['complete']
    with app.app_context(): other=next(x.id for x in db.session.get(Tournament,tid).matches if x.id!=mid)
    assert referee.get(f'/referee/{other}/state').status_code==403
    # A referee session cannot use admin write endpoints.
    assert referee.post(f'/match/{mid}/result',data={'csrf_token':token}).status_code==401
    assert 'Kod sędziego' in admin.get(f'/tournament/{tid}').text


def test_referee_reset_disable_admin_override_and_participant_changes_revoke_access():
    from app import meta_for,set_meta
    admin,atok,tid,mid,code=referee_fixture()
    referee=app.test_client();token=csrf(referee,f'/referee/{mid}')
    referee.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token})
    state=referee.get(f'/referee/{mid}/state').json
    assert referee.post(f'/referee/{mid}/action',json={'action':'point','side':0,'revision':state['revision']},headers={'X-CSRFToken':token}).status_code==200
    assert admin.post(f'/match/{mid}/referee-reset',data={'csrf_token':atok}).status_code==302
    assert referee.get(f'/referee/{mid}/state').status_code==403
    with app.app_context(): code=app.extensions['referee_score'].query.get(mid).desk_code
    referee.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token})
    assert referee.get(f'/referee/{mid}/state').json['current']==[0,0]
    # Admin result takes priority, including over an already unlocked scoring panel.
    admin.post(f'/match/{mid}/result',data={'set_1_p1':3,'set_1_p2':0,'set_2_p1':3,'set_2_p2':0,'csrf_token':atok})
    revision=referee.get(f'/referee/{mid}/state').json['revision']
    assert referee.post(f'/referee/{mid}/action',json={'action':'point','side':0,'revision':revision},headers={'X-CSRFToken':token}).status_code==409
    assert str(mid) not in referee.get('/live/ref-'+str(tid)).json['scores']
    assert admin.post(f'/tournament/{tid}/referees',data={'csrf_token':atok}).status_code==302
    assert referee.get(f'/referee/{mid}').status_code==404
    admin.post(f'/tournament/{tid}/referees',data={'enabled':'on','csrf_token':atok})
    assert referee.get(f'/referee/{mid}/state').status_code==403
    referee.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token})
    with app.app_context():
        m=db.session.get(Match,mid);m.player1_id=m.tournament.players[-1].id;db.session.commit()
    assert referee.get(f'/referee/{mid}/state').status_code==403
    # Publishing disabled revokes all public referee and live endpoints too.
    admin.post(f'/tournament/{tid}/publish',data={'csrf_token':atok})
    assert referee.get(f'/referee/{mid}').status_code==404 and referee.get('/live/ref-'+str(tid)).status_code==404


def test_referee_loser_assignments_manual_override_and_regeneration_cleanup():
    from app import referee_services,generate_structure,meta_for
    admin,token,tid,mid,code=referee_fixture(8,'round_robin')
    with app.app_context():
        t=db.session.get(Tournament,tid);first=next(x for x in t.matches if x.id==mid)
        target=next(x for x in t.matches if x.order_index>first.order_index and first.player2_id not in (x.player1_id,x.player2_id))
        target_id=target.id
    admin.post(f'/match/{mid}/result',data={'set_1_p1':3,'set_1_p2':0,'set_2_p1':3,'set_2_p2':0,'csrf_token':token})
    admin.post(f'/match/{target_id}/referee-assignment',data={'source_match':mid,'csrf_token':token})
    with app.app_context():
        t=db.session.get(Tournament,tid);first=db.session.get(Match,mid)
        assert referee_services['assignments'](t,list(t.matches))[target_id]==first.loser.name
    admin.post(f'/match/{target_id}/referee-assignment',data={'referee_name':'Sędzia testowy','csrf_token':token})
    assert 'Sędzia testowy' in app.test_client().get('/players/ref-'+str(tid)).text
    with app.app_context():
        old_epochs={r.epoch for r in app.extensions['referee_score'].query.all()}
        generate_structure(db.session.get(Tournament,tid))
        rows=app.extensions['referee_score'].query.join(Match,Match.id==app.extensions['referee_score'].match_id).filter(Match.tournament_id==tid).all()
        assert len(rows)==len(db.session.get(Tournament,tid).matches)
        assert not old_epochs & {r.epoch for r in rows}


def test_referee_pin_attempts_are_limited_and_expired_sessions_cannot_write():
    admin,atok,tid,mid,code=referee_fixture()
    guest=app.test_client();token=csrf(guest,f'/referee/{mid}')
    wrong='999' if code!='999' else '998'
    for _ in range(8):
        assert guest.post(f'/referee/{mid}/access',data={'code':wrong,'csrf_token':token},environ_overrides={'REMOTE_ADDR':'198.51.100.77'}).status_code==403
    assert guest.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token},environ_overrides={'REMOTE_ADDR':'198.51.100.77'}).status_code==429
    # Separate IP only isolates this test's counter; no production rate limits are disabled.
    assert guest.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token},environ_overrides={'REMOTE_ADDR':'198.51.100.78'}).status_code==302
    with guest.session_transaction() as s:
        grants=s['referee_grants'];grants[str(mid)]['until']=0;s['referee_grants']=grants
    assert guest.get(f'/referee/{mid}/state').status_code==403
    assert guest.post(f'/referee/{mid}/action',json={'action':'point','side':0,'revision':0},headers={'X-CSRFToken':token}).status_code==403


def test_event_deltas_are_scoped_private_and_do_not_send_whole_pages():
    admin,atok,tid,mid,code=referee_fixture()
    guest=app.test_client();url='/updates/ref-'+str(tid)
    initial=guest.get(url);assert initial.status_code==200
    patch=initial.json;key='match:'+str(mid)
    assert key in patch['entities'] and patch['reset'] and '<!doctype' not in initial.text
    assert 'Kod sędziego' not in initial.text and 'code_hash' not in initial.text
    assert guest.get(url+'?cursor='+patch['cursor']).status_code==304
    assert guest.get(f'/tournament/{tid}/updates').status_code==302
    private=admin.get(f'/tournament/{tid}/updates').json
    assert 'Kod sędziego' in private['entities'][key]
    # No redirect to an HTML tournament document for event-aware action requests.
    result=admin.post(f'/match/{mid}/timing',data={'action':'start','csrf_token':atok},headers={'X-Tournament-Action':'1'})
    assert result.status_code==200 and result.json['ok'] and 'Location' not in result.headers
    delta=guest.get(url+'?cursor='+patch['cursor']).json
    assert key in delta['entities'] and 'standings' not in delta['entities']
    assert not delta['reset']
    recovery=guest.get(url+'?cursor=unknown').json
    assert recovery['reset'] and len(recovery['entities'])>=len(delta['entities'])
    admin.post(f'/tournament/{tid}/publish',data={'csrf_token':atok})
    assert guest.get(url).status_code==404


def test_point_statistics_time_quality_undo_and_backup_restore():
    import json
    from app import statistics_services,export_database_json,import_database_json
    admin,atok,tid,mid,code=referee_fixture()
    referee=app.test_client();token=csrf(referee,f'/referee/{mid}')
    referee.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token})
    state=referee.get(f'/referee/{mid}/state').json
    def action(kind,side=None):
        nonlocal state
        r=referee.post(f'/referee/{mid}/action',json={'action':kind,'side':side,'revision':state['revision']},headers={'X-CSRFToken':token})
        assert r.status_code==200,r.text
        state=r.json
    action('start');action('point',0);action('point',1);action('undo');action('point',0)
    payload=referee.get(f'/match/{mid}/statistics/data').json
    assert [p['score'] for p in payload['path']]==[[1,0],[2,0]]
    assert all(p['at'] and '+00:00' in p['at'] for p in payload['path'])
    assert [a['action'] for a in payload['audit']]==['start','point','point','undo','point']
    assert payload['quality']=='explicit' and payload['duration_seconds'] is None
    assert referee.get(f'/match/{mid}/statistics/data?version='+payload['version']).status_code==304
    action('point',0)
    for _ in range(3):action('point',0)
    action('finish')
    payload=referee.get(f'/match/{mid}/statistics/data').json
    assert payload['complete'] and payload['duration_seconds']>=0 and len(payload['path'])==6
    assert payload['estimate']['count']==0 # A seconds-long test game is not a useful duration sample.
    assert admin.get(f'/match/{mid}/statistics').status_code==200
    assert admin.get(f'/tournament/{tid}/statistics').status_code==200
    with app.app_context():
        original=db.session.get(Match,mid);number=original.order_index
        backup=export_database_json(db.session.get(Tournament,tid))
        assert 'desk_code' not in backup and 'code_hash' not in backup
        imported=import_database_json(backup)
        clone=next(m for m in imported.matches if m.order_index==number)
        restored=statistics_services['details'](clone)
        assert [p['score'] for p in restored['path']]==[p['score'] for p in payload['path']]
        assert [a['action'] for a in restored['audit']]==[a['action'] for a in payload['audit']]
        assert restored['duration_seconds']==payload['duration_seconds']
    # First point without an explicit start is deliberately labelled approximate.
    admin2,atok2,tid2,mid2,code2=referee_fixture()
    r=app.test_client();tok2=csrf(r,f'/referee/{mid2}')
    r.post(f'/referee/{mid2}/access',data={'code':code2,'csrf_token':tok2})
    rev=r.get(f'/referee/{mid2}/state').json['revision']
    assert r.post(f'/referee/{mid2}/action',json={'action':'point','side':1,'revision':rev},headers={'X-CSRFToken':tok2}).status_code==200
    assert r.get(f'/match/{mid2}/statistics/data').json['quality']=='first_point'


def test_duration_estimator_requires_five_full_comparable_samples():
    import json
    from app import create_tournament,generate_structure,statistics_services,meta_for,set_meta
    with app.app_context():
        t=create_tournament('Duration samples',8,'round_robin',True,2);generate_structure(t)
        minutes=[20,25,30,35,40]
        for m,duration in zip(t.matches,minutes):
            m.score_json='[[21, 0], [21, 0]]';m.winner_id=m.player1_id;m.loser_id=m.player2_id
            md=meta_for(m);md.update(actual_start='2026-01-01T10:00:00',actual_end=f'2026-01-01T10:{duration:02d}:00');set_meta(m,md)
            statistics_services['sync'](m,quality='manual')
        db.session.commit()
        estimate=statistics_services['estimate'](t.matches[0])
        assert estimate['count']==5 and estimate['median']==30 and estimate['suggested']==30
        # An incomplete/missing result must not stay in the training set.
        t.matches[0].winner_id=None;db.session.commit()
        estimate=statistics_services['estimate'](t.matches[1])
        assert estimate['count']==4 and estimate['suggested'] is None


def test_two_minute_timeouts_each_side_once_per_set_and_persist_on_reload(monkeypatch):
    from datetime import datetime,timezone,timedelta
    import referees
    admin,atok,tid,mid,code=referee_fixture()
    client=app.test_client();token=csrf(client,f'/referee/{mid}')
    assert client.post(f'/referee/{mid}/access',data={'code':code,'csrf_token':token},environ_overrides={'REMOTE_ADDR':'203.0.113.91'}).status_code==302
    state=client.get(f'/referee/{mid}/state').json
    clock=[datetime(2026,11,10,10,0,tzinfo=timezone.utc)]
    monkeypatch.setattr(referees,'utc_now',lambda:clock[0].isoformat())
    def action(kind,side=None,revision=None):
        nonlocal state
        r=client.post(f'/referee/{mid}/action',json={'action':kind,'side':side,'revision':state['revision'] if revision is None else revision},headers={'X-CSRFToken':token})
        if r.status_code==200:state=r.json
        return r
    assert action('timeout',0).status_code==409 # Not before the match starts.
    assert action('start').status_code==200
    before=state['revision']
    assert action('timeout',0).status_code==200
    pause=state['timeout']['active']
    assert (datetime.fromisoformat(pause['until'])-datetime.fromisoformat(pause['started_at'])).total_seconds()==120
    assert state['timeout']['used']==[True,False]
    assert action('timeout',1).status_code==409
    assert action('point',0).status_code==409 and action('undo').status_code==409
    assert action('timeout',0,revision=before).status_code==409
    assert client.get(f'/referee/{mid}/state').json['timeout']['active']['id']==pause['id']
    public=app.test_client().get('/players/ref-'+str(tid)).text
    assert 'data-timeout-until=' in public and 'data-timeout-clock' in public
    clock[0]+=timedelta(seconds=119)
    assert action('point',0).status_code==409
    clock[0]+=timedelta(seconds=1)
    assert action('point',0).status_code==200
    assert not state['timeout']['active'] and state['timeout']['used']==[True,False]
    assert action('timeout',0).status_code==409 # Refresh / expiration does not refund the quota.
    assert action('timeout',1).status_code==200
    clock[0]+=timedelta(seconds=20)
    assert action('timeout_end').status_code==200
    assert state['timeout']['used']==[True,True] and not state['timeout']['active']
    assert action('timeout',1).status_code==409
    assert action('point',0).status_code==200
    assert action('point',0).status_code==200 # Set 1 ends 3:0.
    assert state['sets']==[[3,0]] and state['timeout']['set']==2 and state['timeout']['used']==[False,False]
    assert action('timeout',0).status_code==200
    data=client.get(f'/match/{mid}/statistics/data').json
    assert len(data['timeouts'])==3
    assert [e['action'] for e in data['audit']].count('timeout_start')==3
    assert [e['action'] for e in data['audit']].count('timeout_end')==1
    assert data['audit'][-1]['side']==0 and data['audit'][-1]['set']==2
