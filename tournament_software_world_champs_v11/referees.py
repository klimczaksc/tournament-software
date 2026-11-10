"""Match-scoped referee access and optimistic, server-authoritative live scoring."""
import json
import secrets
import time
import uuid
from datetime import timedelta
from flask import request, session, g, abort, jsonify, render_template, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from werkzeug.exceptions import HTTPException
from timetable import local_now
from match_statistics import utc_now, as_utc


def configure_referees(app, db, Tournament, Match, settings_for, save_settings, meta_for, set_meta, groups_complete, save_result, timetable_for):
    class RefereeScore(db.Model):
        match_id = db.Column(db.Integer, db.ForeignKey('match.id'), primary_key=True)
        # Desk codes are independent of account passwords and excluded from public responses/backups.
        desk_code = db.Column(db.String(3), nullable=False)
        code_hash = db.Column(db.String(256), nullable=False)
        epoch = db.Column(db.String(32), nullable=False)
        revision = db.Column(db.Integer, nullable=False, default=0)
        signature = db.Column(db.String(100), nullable=False, default='')
        data_json = db.Column(db.Text, nullable=False, default='{}')
    app.extensions['referee_score'] = RefereeScore

    def empty():
        return {'stream_id': uuid.uuid4().hex, 'event_times': [], 'events': [], 'sets': [], 'current': [0, 0], 'started': False, 'finalized': False}

    def signature(m):
        return f'{m.player1_id}:{m.player2_id}:{m.phase.best_of if m.phase else 3}:{m.phase.points_to if m.phase else 21}'

    def data_for(row):
        return json.loads(row.data_json or '{}') or empty()

    def ensure_rows(t):
        existing = {r.match_id for r in RefereeScore.query.join(Match, Match.id == RefereeScore.match_id).filter(Match.tournament_id == t.id)}
        for m in t.matches:
            if m.id not in existing:
                code = f'{secrets.randbelow(1000):03d}'
                db.session.add(RefereeScore(match_id=m.id, desk_code=code, code_hash=generate_password_hash(code), epoch=uuid.uuid4().hex, signature=signature(m), data_json=json.dumps(empty())))
        db.session.commit()

    def clear(tid):
        ids = db.select(Match.id).where(Match.tournament_id == tid)
        RefereeScore.query.filter(RefereeScore.match_id.in_(ids)).delete(synchronize_session=False)

    def codes(t):
        if not settings_for(t).get('referee_enabled'):
            return {}
        return {r.match_id: r.desk_code for r in RefereeScore.query.join(Match, Match.id == RefereeScore.match_id).filter(Match.tournament_id == t.id)}

    def assignments(t, matches):
        if not settings_for(t).get('referee_enabled'):
            return {}
        result = {}
        timing = timetable_for(t, matches)
        reserved = []
        def overlap(a, b):
            if a.id in timing and b.id in timing:
                return timing[a.id]['start'] < timing[b.id]['end'] and timing[b.id]['start'] < timing[a.id]['end']
            return bool(meta_for(a).get('actual_start') and meta_for(b).get('actual_start'))
        def conflict(pid, match):
            if not pid or match.winner_id:return None
            if pid in (match.player1_id,match.player2_id):return match
            return next((other for other in matches if other.id!=match.id and not other.winner_id and pid in (other.player1_id,other.player2_id) and (overlap(match,other) or meta_for(other).get('actual_start'))),None)
        for m in sorted(matches,key=lambda item:(not bool(meta_for(item).get('actual_start') and not item.winner_id),item.order_index)):
            md = meta_for(m)
            if md.get('referee_handover') and not m.winner_id:
                result[m.id] = 'Potrzebny sędzia — przekazanie przy stoliku'
                continue
            if md.get('referee_name'):
                pid=md.get('referee_player_id')
                if not pid:
                    pid=next((p.id for p in t.players if p.name.casefold()==md['referee_name'].casefold()),None)
                other=conflict(pid,m)
                if other:
                    result[m.id] = f"Do zmiany: {md['referee_name']} gra mecz #{other.order_index}"
                elif pid and not m.winner_id and any(used==pid and overlap(m,match) for used,match in reserved):
                    result[m.id] = 'Do zmiany: sędzia prowadzi inny mecz'
                else:
                    result[m.id] = md['referee_name']
                    if pid and not m.winner_id:reserved.append((pid,m))
                continue
            previous = [x for x in matches if x.order_index < m.order_index and x.id != m.id]
            chosen = None
            if md.get('referee_source_key') or md.get('referee_source_order'):
                chosen = next((x for x in previous if (meta_for(x).get('key') == md.get('referee_source_key') if md.get('referee_source_key') else x.order_index == md.get('referee_source_order'))), None)
            else:
                for candidate in sorted(previous, key=lambda x: x.order_index, reverse=True):
                    if candidate.winner_id and not (candidate.player1_id and candidate.player2_id):
                        continue
                    if candidate.loser_id and any(other.id != m.id and not other.winner_id and meta_for(other).get('actual_start') and candidate.loser_id in (other.player1_id, other.player2_id) for other in matches):
                        continue
                    if candidate.court_number != m.court_number:
                        continue
                    if candidate.loser_id and (conflict(candidate.loser_id,m) or any(pid==candidate.loser_id and overlap(m,other) for pid,other in reserved)):
                        continue
                    chosen = candidate
                    break
            if not chosen:
                result[m.id] = 'Do wyznaczenia przy stoliku'
            elif chosen.loser_id and conflict(chosen.loser_id,m):
                result[m.id] = f'Do zmiany: {chosen.loser.name} gra mecz #{conflict(chosen.loser_id,m).order_index}'
            elif chosen.loser_id and not m.winner_id and any(pid==chosen.loser_id and overlap(m,other) for pid,other in reserved):
                result[m.id] = 'Do zmiany: sędzia prowadzi inny mecz'
            elif chosen.loser:
                result[m.id] = chosen.loser.name
                if not m.winner_id:reserved.append((chosen.loser_id,m))
            else:
                result[m.id] = f'Przegrany meczu #{chosen.order_index} (jedna osoba z drużyny)'
        return result

    def scores(t, matches):
        if not settings_for(t).get('referee_enabled'):
            return {}
        rows = RefereeScore.query.join(Match, Match.id == RefereeScore.match_id).filter(Match.tournament_id == t.id).all()
        by_id = {m.id: m for m in matches}
        result = {}
        for row in rows:
            m = by_id.get(row.match_id)
            if not m or row.signature != signature(m):
                continue
            data = data_for(row)
            if not data.get('started'):
                continue
            # Admin result changes are authoritative, never display a stale live score over them.
            if m.winner_id and (not data.get('finalized') or json.loads(m.score_json or '[]') != data['sets']):
                continue
            if data.get('finalized') and not m.winner_id:
                continue
            result[m.id] = {'current': data['current'], 'sets': data['sets'], 'complete': bool(m.winner_id), 'awaiting_confirmation': bool(data.get('finished_at') and not m.winner_id), 'revision': row.revision, 'timeout':timeout_info(data)}
        return result

    def match_public(mid):
        m = db.session.get(Match, mid)
        if not m or not settings_for(m.tournament).get('referee_enabled') or not settings_for(m.tournament).get('public_enabled'):
            abort(404)
        return m

    def allowed(m, row):
        grant = session.get('referee_grants', {}).get(str(m.id), {})
        return bool(row and grant.get('epoch') == row.epoch and grant.get('signature') == signature(m) and grant.get('until', 0) > time.time())

    def ready(m):
        if not m.player1_id or not m.player2_id or m.winner_id or json.loads(m.score_json or '[]'):
            abort(409, 'Mecz ma już wynik lub nie ma jeszcze uczestników. Poproś administratora o sprawdzenie.')
        if m.tournament.system == 'group_knockout' and not m.bracket.startswith('group_') and not groups_complete(m.tournament_id):
            abort(409, 'Najpierw zakończ fazę grupową.')

    def timeout_info(data):
        now=as_utc(utc_now())
        number=len(data.get('sets',[]))+1
        timeouts=data.get('timeouts',[])
        active=next((item for item in reversed(timeouts) if not item.get('closed_at') and as_utc(item['until'])>now),None)
        return {'active':active,'used':[any(item['set']==number and item['side']==side for item in timeouts) for side in (0,1)],'set':number,'server_now':now.isoformat()}

    def state_payload(m, row):
        d = data_for(row)
        playable = bool(m.player1_id and m.player2_id and not m.winner_id and not json.loads(m.score_json or '[]'))
        if m.tournament.system == 'group_knockout' and not m.bracket.startswith('group_') and not groups_complete(m.tournament_id):
            playable = False
        return {'timeout':timeout_info(d), 'playable': playable, 'revision': row.revision, 'sets': d['sets'], 'current': d['current'], 'started': d['started'], 'finalized': d['finalized'], 'awaiting_confirmation': bool(d.get('finished_at')), 'winner_id': m.winner_id, 'handover':bool(meta_for(m).get('referee_handover')), 'players': [m.player1.name if m.player1 else 'TBD', m.player2.name if m.player2 else 'TBD'], 'best_of': m.phase.best_of if m.phase else 3, 'points_to': m.phase.points_to if m.phase else 21}

    @app.route('/tournament/<int:tournament_id>/referees', methods=['POST'])
    def configure_referee_panel(tournament_id):
        t = Tournament.query.get_or_404(tournament_id)
        st = settings_for(t)
        st['referee_enabled'] = request.form.get('enabled') == 'on'
        save_settings(t, st)
        db.session.commit()
        # Revoke sessions on every enable/disable operation.
        for row in RefereeScore.query.join(Match, Match.id == RefereeScore.match_id).filter(Match.tournament_id == t.id):
            row.epoch = uuid.uuid4().hex
        db.session.commit()
        if st['referee_enabled']:
            ensure_rows(t)
        flash('Zapisano ustawienia sędziów. Kody są widoczne przy meczach w panelu administratora.')
        return redirect(url_for('tournament_view', tournament_id=t.id) + '#referees')

    @app.route('/match/<int:match_id>/referee-assignment', methods=['POST'])
    def referee_assignment(match_id):
        m = Match.query.get_or_404(match_id)
        md = meta_for(m)
        name = request.form.get('referee_name', '').strip()
        if len(name) > 100:
            abort(400)
        source = request.form.get('source_match', '')
        for key in ('referee_name', 'referee_player_id', 'referee_source_key', 'referee_source_order', 'referee_handover'):
            md.pop(key, None)
        pid=request.form.get('referee_player_id','')
        if pid:
            player=next((p for p in m.tournament.players if str(p.id)==pid),None)
            if not player:abort(400)
            md['referee_player_id']=player.id;md['referee_name']=player.name
        elif name:
            md['referee_name'] = name
        elif source:
            source_match = db.session.get(Match, int(source)) if source.isdigit() and len(source) <= 10 else None
            if not source_match or source_match.tournament_id != m.tournament_id or source_match.order_index >= m.order_index:
                abort(400)
            key = meta_for(source_match).get('key')
            md['referee_source_key' if key else 'referee_source_order'] = key or source_match.order_index
        set_meta(m, md)
        db.session.commit()
        flash('Zapisano przydział sędziego.')
        return redirect(url_for('tournament_view', tournament_id=m.tournament_id) + f'#match-{m.id}')

    @app.route('/match/<int:match_id>/referee-reset', methods=['POST'])
    def referee_reset(match_id):
        m = Match.query.get_or_404(match_id)
        row = db.session.get(RefereeScore, m.id)
        if not row:
            abort(404)
        if m.winner_id:
            abort(409, 'Najpierw usuń oficjalny wynik, jeśli chcesz ponownie sędziować mecz.')
        code = f'{secrets.randbelow(1000):03d}'
        while code == row.desk_code:
            code = f'{secrets.randbelow(1000):03d}'
        prior=data_for(row)
        if prior.get('stream_id'):app.extensions['match_statistics']['record'](m,'reset',prior)
        row.desk_code, row.code_hash = code, generate_password_hash(code)
        row.epoch, row.revision, row.signature, row.data_json = uuid.uuid4().hex, row.revision + 1, signature(m), json.dumps(empty())
        md = meta_for(m);md.pop('actual_start', None);md.pop('actual_end', None);set_meta(m, md)
        db.session.commit()
        flash('Wyzerowano panel punktowy i zmieniono kod. Poprzedni dostęp sędziego wygasł.')
        return redirect(url_for('tournament_view', tournament_id=m.tournament_id) + f'#match-{m.id}')

    @app.route('/referee/<int:match_id>')
    def referee_page(match_id):
        m = match_public(match_id)
        row = db.session.get(RefereeScore, m.id)
        g.public_view = True
        return render_template('referee.html', tournament=m.tournament, settings=settings_for(m.tournament), match=m, unlocked=allowed(m, row), referee=assignments(m.tournament, list(m.tournament.matches)).get(m.id, 'Do wyznaczenia'))

    @app.route('/referee/<int:match_id>/access', methods=['POST'])
    def referee_access(match_id):
        m = match_public(match_id)
        row = db.session.get(RefereeScore, m.id)
        if not row or not check_password_hash(row.code_hash, request.form.get('code', '')[:32]):
            flash('Nieprawidłowy kod sędziego. Pobierz kod tego meczu przy stoliku.')
            return referee_page(match_id), 403
        if row.signature != signature(m):
            row.signature, row.data_json, row.epoch = signature(m), json.dumps(empty()), uuid.uuid4().hex
            row.revision += 1
            db.session.commit()
        grants = session.get('referee_grants', {})
        grants[str(m.id)] = {'epoch': row.epoch, 'signature': signature(m), 'until': time.time() + 8 * 3600}
        # Limit signed cookie size when one desk device is used for many matches.
        grants = dict(list(grants.items())[-8:])
        session['referee_grants'] = grants
        return redirect(url_for('referee_page', match_id=m.id))

    @app.route('/referee/<int:match_id>/state')
    def referee_state(match_id):
        m = match_public(match_id)
        row = db.session.get(RefereeScore, m.id)
        if not allowed(m, row):
            abort(403)
        return jsonify(state_payload(m, row))

    def calculate(events, m):
        sets, current = [], [0, 0]
        target = m.phase.points_to if m.phase else 21
        needed = (m.phase.best_of if m.phase else 3) // 2 + 1
        for side in events:
            if sum(a > b for a, b in sets) >= needed or sum(b > a for a, b in sets) >= needed:
                abort(409, 'Mecz jest rozstrzygnięty. Zatwierdź wynik albo cofnij punkt.')
            current[side] += 1
            if max(current) >= target and abs(current[0] - current[1]) >= 2:
                sets.append(list(current)); current = [0, 0]
        complete = sum(a > b for a, b in sets) >= needed or sum(b > a for a, b in sets) >= needed
        return sets, current, complete

    @app.route('/referee/<int:match_id>/action', methods=['POST'])
    def referee_action(match_id):
        m = match_public(match_id)
        row = db.session.get(RefereeScore, m.id)
        if not allowed(m, row):
            abort(403)
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or type(payload.get('revision')) is not int:
            abort(400)
        try:
            # CAS is a write lock and rejects stale tabs/double deliveries.
            claimed = db.session.execute(update(RefereeScore).where(RefereeScore.match_id == m.id, RefereeScore.revision == payload['revision'], RefereeScore.epoch == row.epoch).values(revision=RefereeScore.revision + 1))
            if claimed.rowcount != 1:
                db.session.rollback();abort(409, 'Wynik został już zmieniony. Odśwież panel i sprawdź wynik.')
            db.session.refresh(m);db.session.refresh(row)
            if not allowed(m, row):
                abort(403)
            ready(m)
            data = data_for(row)
            if data.get('finalized'):
                abort(409)
            action = payload.get('action')
            data.setdefault('stream_id',uuid.uuid4().hex)
            data.setdefault('event_times',[None]*len(data['events']))
            data['revision']=row.revision
            data.setdefault('timeouts',[])
            timeout=timeout_info(data)
            if timeout['active'] and action not in ('timeout_end','handover'):
                abort(409,'Trwa czas zawodnika. Zakończ go lub poczekaj na upływ 2 minut.')
            if action in ('timeout','timeout_end'):
                if not data.get('started') or data.get('finished_at'):
                    abort(409,'Czas jest dostępny tylko w trakcie seta.')
                if action=='timeout':
                    side=payload.get('side')
                    if type(side) is not int or side not in (0,1):abort(400)
                    if timeout['used'][side]:abort(409,'Ten zawodnik lub drużyna wykorzystał już czas w tym secie.')
                    now=as_utc(utc_now())
                    item={'id':uuid.uuid4().hex,'side':side,'set':timeout['set'],'started_at':now.isoformat(),'until':(now+timedelta(seconds=120)).isoformat()}
                    data['timeouts'].append(item)
                else:
                    item=next((item for item in reversed(data['timeouts']) if not item.get('closed_at')),None)
                    if not item:abort(409,'Nie ma czasu do zakończenia.')
                    now=as_utc(utc_now())
                    item['closed_at']=min(now,as_utc(item['until'])).isoformat()
                app.extensions['match_statistics']['record'](m,'timeout_start' if action=='timeout' else 'timeout_end',data,item['side'],{'set':item['set'],'timeout_id':item['id'],'until':item['until']})
                row.data_json=json.dumps(data);db.session.commit()
                return jsonify(state_payload(m,row))
            if action == 'handover':
                md=meta_for(m);md['referee_handover']=True;set_meta(m,md)
                db.session.commit()
                return jsonify(state_payload(m,row))
            if action == 'finish':
                if not data.get('finished_at'):
                    abort(409, 'Mecz nie ma jeszcze zwycięzcy.')
                data['finalized'] = True
                app.extensions['match_statistics']['record'](m,'finish',data)
                row.data_json = json.dumps(data)
                # Official scoring uses exactly the same propagation as the admin panel.
                save_result(m, data['sets'])
                md = meta_for(m);md['actual_end'] = data['finished_at'];set_meta(m, md)
                app.extensions['match_statistics']['sync'](m)
                db.session.commit()
                return jsonify(state_payload(m, row))
            events = list(data['events'])
            if action in ('point','start'):
                side = payload.get('side')
                if action=='point' and (type(side) is not int or side not in (0, 1) or len(events) >= 2000):
                    abort(400)
                if action=='point':
                    events.append(side)
                    data['event_times'].append(utc_now())
                elif data.get('started'):
                    abort(409, 'Mecz już rozpoczęty.')
            elif action == 'undo':
                if not events:
                    abort(409, 'Nie ma punktu do cofnięcia.')
                removed=events.pop()
                data['event_times'].pop()
            else:
                abort(400)
            sets, current, complete = calculate(events, m)
            if not data.get('started'):
                for other in m.tournament.matches:
                    if other.id != m.id and not other.winner_id and meta_for(other).get('actual_start') and (other.court_number == m.court_number or set(filter(None, (other.player1_id, other.player2_id))) & {m.player1_id, m.player2_id}):
                        abort(409, 'Kort lub zawodnik bierze udział w innym meczu.')
                md = meta_for(m)
                data['timing_quality']='explicit' if action=='start' or md.get('actual_start') else 'first_point'
                md.setdefault('actual_start', local_now(settings_for(m.tournament)).isoformat())
                data['started_at_utc']=as_utc(md['actual_start'],settings_for(m.tournament).get('schedule_timezone','Europe/Warsaw')).isoformat()
                set_meta(m, md)
            data.update(events=events, sets=sets, current=current, started=True)
            if complete:
                data.setdefault('finished_at', local_now(settings_for(m.tournament)).isoformat())
                data.setdefault('finished_at_utc',utc_now())
            else:
                data.pop('finished_at', None)
                data.pop('finished_at_utc',None)
            app.extensions['match_statistics']['record'](m,action,data,payload.get('side') if action=='point' else removed if action=='undo' else None)
            row.data_json = json.dumps(data)
            db.session.commit()
            return jsonify(state_payload(m, row))
        except HTTPException:
            db.session.rollback();raise
        except OperationalError:
            db.session.rollback();abort(409, 'Równoczesny zapis. Sprawdź aktualny wynik przed kolejnym kliknięciem.')

    @app.route('/live/<token>')
    def public_live_scores(token):
        t = next((t for t in Tournament.query.all() if settings_for(t).get('public_enabled') and secrets.compare_digest(settings_for(t).get('public_token', ''), token)), None)
        if not t:
            abort(404)
        matches = list(t.matches)
        return jsonify({'scores': scores(t, matches), 'referees': assignments(t, matches)})

    return {'assignments': assignments, 'scores': scores, 'codes': codes, 'clear': clear, 'ensure': ensure_rows}
