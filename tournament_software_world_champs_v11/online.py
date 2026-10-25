"""Server-enforced access control and online account lifecycle."""
import os
import secrets
import hmac
from flask import request, session, g, abort, redirect, url_for, render_template, flash
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix


def configure_online(app, db, Tournament, settings_for, save_settings, tournament_view):
    class User(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(80), unique=True, nullable=False)
        password_hash = db.Column(db.String(256), nullable=False)
        role = db.Column(db.String(12), nullable=False, default='viewer')
        active = db.Column(db.Boolean, nullable=False, default=True)
        version = db.Column(db.Integer, nullable=False, default=1)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    limiter = Limiter(get_remote_address, app=app, storage_uri='memory://', default_limits=[])
    # Authorization runs before CSRF so unauthenticated and viewer writes cannot reach handlers.
    @app.before_request
    def authorize():
        g.user = db.session.get(User, session.get('uid')) if session.get('uid') else None
        if g.user and (not g.user.active or session.get('version') != g.user.version):
            session.clear()
            g.user = None
        public = {'login', 'setup', 'health', 'public_tournament', 'static'}
        if request.endpoint in public:
            return
        if not g.user:
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                abort(401)
            return redirect(url_for('login'))
        if request.endpoint in {'accounts', 'export_db'} and g.user.role != 'admin':
            abort(403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.endpoint not in {'logout', 'password'} and g.user.role != 'admin':
            abort(403)

    CSRFProtect(app)

    @app.context_processor
    def identity():
        user = getattr(g, 'user', None)
        return dict(current_user=user, is_admin=bool(user and user.role == 'admin'), public_view=getattr(g, 'public_view', False))

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.route('/health')
    def health():
        db.session.execute(db.text('SELECT 1'))
        return {'status': 'ok'}

    @app.route('/setup', methods=['GET', 'POST'])
    @limiter.limit('10/minute')
    def setup():
        if User.query.filter_by(role='admin').first():
            abort(404)
        expected = os.environ.get('SETUP_TOKEN', '')
        token = request.values.get('token', '')
        if not expected or not hmac.compare_digest(expected, token):
            abort(404)
        if request.method == 'POST':
            username = request.form.get('username', '').strip().lower()
            password = request.form.get('password', '')
            if not 3 <= len(username) <= 80 or len(password) < 8:
                flash('Login: 3–80 znaków. Hasło: minimum 8 znaków.')
            else:
                db.session.add(User(username=username, password_hash=generate_password_hash(password), role='admin'))
                db.session.commit()
                flash('Konto administratora utworzone. Zaloguj się.')
                return redirect(url_for('login'))
        return render_template('auth.html', mode='setup', token=token)

    @app.route('/login', methods=['GET', 'POST'])
    @limiter.limit('10/minute;60/hour', methods=['POST'])
    def login():
        if request.method == 'POST':
            user = User.query.filter_by(username=request.form.get('username', '').strip().lower()).first()
            # A real hash for unknown users avoids a fast username-discovery path.
            valid = check_password_hash(user.password_hash if user else dummy_hash, request.form.get('password', ''))
            if user and user.active and valid:
                session.clear()
                session.update(uid=user.id, version=user.version)
                session.permanent = True
                return redirect(url_for('index'))
            flash('Nieprawidłowy login lub hasło.')
        return render_template('auth.html', mode='login')

    @app.route('/logout', methods=['POST'])
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/password', methods=['GET', 'POST'])
    @limiter.limit('10/minute', methods=['POST'])
    def password():
        if request.method == 'POST':
            new = request.form.get('password', '')
            if not check_password_hash(g.user.password_hash, request.form.get('current_password', '')) or len(new) < 8:
                flash('Sprawdź obecne hasło. Nowe hasło wymaga minimum 8 znaków.')
            else:
                g.user.password_hash = generate_password_hash(new)
                g.user.version += 1
                db.session.commit()
                session['version'] = g.user.version
                flash('Hasło zmienione.')
                return redirect(url_for('index'))
        return render_template('auth.html', mode='password')

    @app.route('/accounts', methods=['GET', 'POST'])
    def accounts():
        if request.method == 'POST':
            action = request.form.get('action', 'create')
            if action == 'create':
                name = request.form.get('username', '').strip().lower()
                pwd = request.form.get('password', '')
                if not 3 <= len(name) <= 80 or len(pwd) < 8 or User.query.filter_by(username=name).first():
                    flash('Login musi być unikalny (3–80 znaków), hasło: minimum 8 znaków.')
                else:
                    db.session.add(User(username=name, password_hash=generate_password_hash(pwd), role='viewer'))
                    db.session.commit()
                    flash('Utworzono konto tylko do odczytu.')
            else:
                user = db.get_or_404(User, request.form.get('user_id', type=int))
                if user.role == 'admin':
                    abort(400)
                if action == 'toggle':
                    user.active = not user.active
                elif action == 'reset' and len(request.form.get('password', '')) >= 8:
                    user.password_hash = generate_password_hash(request.form['password'])
                else:
                    abort(400)
                user.version += 1
                db.session.commit()
            return redirect(url_for('accounts'))
        return render_template('accounts.html', users=User.query.order_by(User.username).all())

    @app.route('/tournament/<int:tournament_id>/publish', methods=['POST'])
    def publish(tournament_id):
        t = db.get_or_404(Tournament, tournament_id)
        data = settings_for(t)
        data['public_enabled'] = request.form.get('published') == 'on'
        # Re-enabling creates a new link; old links stay invalid.
        if data['public_enabled'] and not settings_for(t).get('public_enabled'):
            data['public_token'] = secrets.token_urlsafe(24)
        save_settings(t, data)
        db.session.commit()
        return redirect(url_for('tournament_view', tournament_id=t.id))

    @app.route('/players/<token>')
    def public_tournament(token):
        t = next((t for t in Tournament.query.all() if settings_for(t).get('public_enabled') and hmac.compare_digest(settings_for(t).get('public_token', ''), token)), None)
        if not t:
            abort(404)
        g.public_view = True
        return tournament_view(t.id)

    dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
    with app.app_context():
        db.create_all()
    app.extensions['online_user'] = User
