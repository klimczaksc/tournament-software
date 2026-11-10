"""Durable point audit, corrected score paths and quality-controlled duration samples."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from statistics import median, quantiles
import hashlib,json,math
from flask import request,g,abort,jsonify,render_template


def utc_now():return datetime.now(timezone.utc).isoformat()


def as_utc(value,zone='Europe/Warsaw'):
    if not value:return None
    try:
        dt=datetime.fromisoformat(value)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=ZoneInfo(zone))
        return dt.astimezone(timezone.utc)
    except (ValueError,TypeError):return None


def configure_statistics(app,db,Tournament,Match,settings_for,meta_for,RefereeScore):
    class MatchPointEvent(db.Model):
        id=db.Column(db.Integer,primary_key=True,autoincrement=True)
        match_id=db.Column(db.Integer,db.ForeignKey('match.id'),nullable=False,index=True)
        stream_id=db.Column(db.String(32),nullable=False,index=True)
        action=db.Column(db.String(20),nullable=False)
        recorded_at=db.Column(db.String(50),nullable=False)
        payload=db.Column(db.Text,nullable=False)
    class MatchDurationSample(db.Model):
        match_id=db.Column(db.Integer,db.ForeignKey('match.id'),primary_key=True)
        signature=db.Column(db.String(100),nullable=False)
        score_json=db.Column(db.Text,nullable=False)
        started_at=db.Column(db.String(50),nullable=False)
        ended_at=db.Column(db.String(50),nullable=False)
        seconds=db.Column(db.Float,nullable=False)
        quality=db.Column(db.String(30),nullable=False)
        points_to=db.Column(db.Integer,nullable=False)
        best_of=db.Column(db.Integer,nullable=False)
        phase_type=db.Column(db.String(50),nullable=False)
    app.extensions['match_point_event']=MatchPointEvent
    app.extensions['match_duration_sample']=MatchDurationSample

    def signature(m):return f'{m.player1_id}:{m.player2_id}:{m.phase.best_of if m.phase else 3}:{m.phase.points_to if m.phase else 21}'
    def record(m,action,data,side=None):
        db.session.add(MatchPointEvent(match_id=m.id,stream_id=data['stream_id'],action=action,recorded_at=utc_now(),payload=json.dumps({'side':side,'revision':data.get('revision'),'current':data['current'],'sets':data['sets'],'point_number':len(data['events'])})))
    def sync(m,quality=None):
        sample=db.session.get(MatchDurationSample,m.id)
        md=meta_for(m);zone=settings_for(m.tournament).get('schedule_timezone','Europe/Warsaw')
        start=as_utc(md.get('actual_start'),zone);end=as_utc(md.get('actual_end'),zone)
        if not m.winner_id or not m.player1_id or not m.player2_id or not start or not end or end<start:
            if sample:db.session.delete(sample)
            return None
        row=db.session.get(RefereeScore,m.id)
        data=json.loads(row.data_json) if row else {}
        q=quality or (data.get('timing_quality','legacy_unverified') if row and data.get('started') and row.signature==signature(m) else 'explicit')
        values=dict(signature=signature(m),score_json=m.score_json,started_at=start.isoformat(),ended_at=end.isoformat(),seconds=(end-start).total_seconds(),quality=q,points_to=m.phase.points_to if m.phase else 21,best_of=m.phase.best_of if m.phase else 3,phase_type=m.phase.phase_type if m.phase else 'main')
        if not sample:sample=MatchDurationSample(match_id=m.id,**values);db.session.add(sample)
        else:
            for key,value in values.items():setattr(sample,key,value)
        return sample
    def clear(tid):
        ids=db.select(Match.id).where(Match.tournament_id==tid)
        MatchPointEvent.query.filter(MatchPointEvent.match_id.in_(ids)).delete(synchronize_session=False)
        MatchDurationSample.query.filter(MatchDurationSample.match_id.in_(ids)).delete(synchronize_session=False)
    def estimate(m):
        target=m.phase.points_to if m.phase else 21;bo=m.phase.best_of if m.phase else 3;phase=m.phase.phase_type if m.phase else 'main'
        rows=MatchDurationSample.query.filter_by(points_to=target,best_of=bo,phase_type=phase).all()
        values=[]
        for row in rows:
            current=db.session.get(Match,row.match_id)
            if not current or not current.winner_id or row.signature!=signature(current) or current.score_json!=row.score_json:continue
            sets=json.loads(row.score_json or '[]');needed=bo//2+1
            full=any(sum(pair[side]>pair[1-side] for pair in sets)>=needed for side in (0,1))
            full=full and len(sets)<=bo and all(max(pair)>=target and abs(pair[0]-pair[1])>=2 for pair in sets)
            if full and row.quality in ('explicit','manual') and 60<=row.seconds<=21600:values.append(row.seconds/60)
        if not values:return {'count':0,'median':None,'p25':None,'p75':None,'suggested':None}
        quartiles=quantiles(values,n=4,method='inclusive') if len(values)>1 else [values[0]]*3
        return {'count':len(values),'median':round(median(values),1),'p25':round(quartiles[0],1),'p75':round(quartiles[2],1),'suggested':int(math.ceil(median(values)/5)*5) if len(values)>=5 else None}
    def details(m):
        row=db.session.get(RefereeScore,m.id);data=json.loads(row.data_json) if row else {}
        compatible=bool(row and row.signature==signature(m))
        if compatible and m.winner_id and (not data.get('finalized') or data.get('sets')!=json.loads(m.score_json or '[]')):compatible=False
        events=data.get('events',[]) if compatible else []
        times=data.get('event_times',[]) if compatible else []
        path=[];score=[0,0];set_number=1
        target=m.phase.points_to if m.phase else 21
        for index,side in enumerate(events):
            score[side]+=1
            path.append({'n':index+1,'set':set_number,'side':side,'score':list(score),'at':times[index] if index<len(times) else None})
            if max(score)>=target and abs(score[0]-score[1])>=2:score=[0,0];set_number+=1
        md=meta_for(m);zone=settings_for(m.tournament).get('schedule_timezone','Europe/Warsaw')
        start=as_utc(md.get('actual_start'),zone);end=as_utc(md.get('actual_end'),zone)
        elapsed=round((end-start).total_seconds(),1) if start and end and end>=start else None
        quality=data.get('timing_quality','legacy_unverified') if compatible and data.get('started') else 'explicit' if start else 'missing'
        sample=db.session.get(MatchDurationSample,m.id)
        if sample and sample.signature==signature(m) and sample.score_json==m.score_json and sample.quality=='manual':quality='manual'
        audit=[{'id':e.id,'action':e.action,'at':e.recorded_at,**json.loads(e.payload)} for e in MatchPointEvent.query.filter_by(match_id=m.id).order_by(MatchPointEvent.id).all()]
        payload={'match_id':m.id,'players':[m.player1.name if m.player1 else 'TBD',m.player2.name if m.player2 else 'TBD'],'path':path,'audit':audit,'started_at':start.isoformat() if start else None,'ended_at':end.isoformat() if end else None,'duration_seconds':elapsed,'quality':quality,'complete':bool(m.winner_id),'historical_points':bool(events and any(p['at'] is None for p in path)),'points_missing':not bool(path),'estimate':estimate(m),'zone':zone}
        payload['version']=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        return payload
    def accessible(mid):
        m=db.session.get(Match,mid)
        if not m or (not getattr(g,'user',None) and not settings_for(m.tournament).get('public_enabled')):abort(404)
        return m
    @app.route('/match/<int:match_id>/statistics')
    def match_statistics(match_id):
        m=accessible(match_id);g.public_view=not bool(getattr(g,'user',None))
        return render_template('match_statistics.html',tournament=m.tournament,settings=settings_for(m.tournament),match=m)
    @app.route('/match/<int:match_id>/statistics/data')
    def match_statistics_data(match_id):
        m=accessible(match_id);payload=details(m)
        if request.args.get('version')==payload['version']:return '',304
        return jsonify(payload)
    @app.route('/tournament/<int:tournament_id>/statistics')
    def tournament_statistics(tournament_id):
        t=Tournament.query.get_or_404(tournament_id)
        return render_template('tournament_statistics.html',tournament=t,settings=settings_for(t),measurements=[{'match':m,'details':details(m)} for m in t.matches])
    def export(t):
        result=[]
        for m in t.matches:
            row=db.session.get(RefereeScore,m.id)
            audit=MatchPointEvent.query.filter_by(match_id=m.id).order_by(MatchPointEvent.id).all()
            state=json.loads(row.data_json) if row and row.signature==signature(m) else None
            if audit or (state and state.get('started')):
                result.append({'order':m.order_index,'state':state,'audit':[dict(stream_id=e.stream_id,action=e.action,at=e.recorded_at,payload=json.loads(e.payload)) for e in audit]})
        return result
    def restore(t,entries):
        if not entries:return
        from uuid import uuid4
        app.extensions['referee_services']['ensure'](t)
        by_order={m.order_index:m for m in t.matches}
        for entry in entries:
            m=by_order.get(entry.get('order'))
            if not m:continue
            state=entry.get('state')
            if isinstance(state,dict) and len(state.get('events',[]))<=2000 and all(type(side) is int and side in (0,1) for side in state.get('events',[])):
                row=db.session.get(RefereeScore,m.id);row.data_json=json.dumps(state);row.signature=signature(m)
            for e in entry.get('audit',[])[:5000]:
                if e.get('action') not in ('point','undo','start','finish','reset'):continue
                db.session.add(MatchPointEvent(match_id=m.id,stream_id=str(e.get('stream_id') or uuid4().hex)[:32],action=e['action'],recorded_at=e['at'],payload=json.dumps(e.get('payload',{}))))
            sync(m)
        db.session.commit()
    def backfill():
        for m in Match.query.filter(Match.winner_id.isnot(None)).all():
            if not db.session.get(MatchDurationSample,m.id):sync(m)
        db.session.commit()
    services={'backfill':backfill,'record':record,'sync':sync,'clear':clear,'details':details,'estimate':estimate,'export':export,'restore':restore}
    app.extensions['match_statistics']=services
    return services
