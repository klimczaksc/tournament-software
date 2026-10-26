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
