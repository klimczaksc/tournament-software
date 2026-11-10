"""Private workspaces for self-registered organisers; legacy admin data stays intact."""
from flask import g,request,has_request_context
from sqlalchemy import event


def configure_access(app,db,Tournament,Match,Phase,User):
    class TournamentOwner(db.Model):
        tournament_id=db.Column(db.Integer,db.ForeignKey('tournament.id'),primary_key=True)
        user_id=db.Column(db.Integer,db.ForeignKey(User.id),nullable=False,index=True)
        tournament=db.relationship(Tournament,backref=db.backref('ownership',uselist=False,cascade='all, delete-orphan'))

    def owner_id(t):
        return t.ownership.user_id if t and t.ownership else None

    def can_manage(user,t):
        return bool(user and user.active and (user.role=='admin' or (user.role=='organizer' and owner_id(t)==user.id)))

    def can_read(user,t):
        return bool(t and user and user.active and (can_manage(user,t) or (user.role=='viewer' and owner_id(t) is None)))

    def scoped_tournament():
        args=request.view_args or {}
        if 'tournament_id' in args:return db.session.get(Tournament,args['tournament_id'])
        if 'match_id' in args:
            m=db.session.get(Match,args['match_id']);return m.tournament if m else None
        if 'phase_id' in args:
            phase=db.session.get(Phase,args['phase_id']);return phase.tournament if phase else None
        return None

    @event.listens_for(db.session,'before_flush')
    def assign_new_tournaments(session,flush_context,instances):
        if not has_request_context():return
        user=getattr(g,'user',None)
        if not user or user.role!='organizer':return
        for obj in list(session.new):
            if isinstance(obj,Tournament) and obj.ownership is None:
                session.add(TournamentOwner(tournament=obj,user_id=user.id))

    def visible_tournaments(user):
        query=Tournament.query
        if user.role=='organizer':query=query.join(TournamentOwner).filter(TournamentOwner.user_id==user.id)
        elif user.role=='viewer':query=query.filter(~Tournament.ownership.has())
        return query.order_by(Tournament.id.desc()).all()

    app.extensions['can_manage_tournament']=can_manage
    app.extensions['can_read_tournament']=can_read
    app.extensions['tournament_owner']=TournamentOwner
    app.extensions['visible_tournaments']=visible_tournaments
    return dict(manage=can_manage,read=can_read,scope=scoped_tournament)
