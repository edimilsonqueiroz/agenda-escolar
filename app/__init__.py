from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Flask, g, jsonify, redirect, request, send_from_directory, url_for
from flask_login import current_user
from sqlalchemy.exc import OperationalError

from .config import get_config
from .extensions import csrf, db, limiter, login_manager, mail, migrate, socketio
from .models import ChatRoom, User


BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")


def to_brasilia_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BRASILIA_TZ)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def create_app(test_config: dict | None = None):
    app = Flask(__name__)
    app.config.from_object(get_config())
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins="*")
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    login_manager.login_view = "auth.login"

    # Adiciona exceção CSRF para socket.io
    @csrf.exempt
    def socket_io_static():
        pass

    register_blueprints(app)
    register_hooks(app)
    register_commands(app)

    with app.app_context():
        create_default_chat_room()

    return app


def register_blueprints(app):
    from .api.routes import api_bp
    from .auth.routes import auth_bp
    from .chat.socket_events import register_socket_events
    from .core.routes import core_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    register_socket_events(socketio)


def register_hooks(app):
    @app.template_filter("br_datetime")
    def br_datetime_filter(value, fmt="%d/%m/%Y %H:%M"):
        localized = to_brasilia_datetime(value)
        if localized is None:
            return "-"
        return localized.strftime(fmt)

    @app.get("/favicon.ico")
    @limiter.exempt
    def favicon():
        """Retorna um favicon vazio para evitar erro 404"""
        return "", 204

    @app.before_request
    def exempt_socketio():
        """Exempta socket.io do CSRF e rate limiting"""
        if request.path.startswith('/socket.io'):
            request.environ['CSRF_EXEMPT'] = True
            # Exemta rate limiting também
            from flask_limiter import LIMITER_STORAGE_UNAVAILABLE_PLACEHOLDER
            request.environ['RATELIMIT_LIMIT_REACHED'] = False

    @app.get("/health")
    def health_check():
        return jsonify({"status": "ok"})

    @app.get("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("core.dashboard"))
        return redirect(url_for("auth.login"))

    @app.context_processor
    def inject_notifications():
        """Injeta contagem de notificações não lidas para todos os templates."""
        if current_user.is_authenticated:
            if hasattr(g, "notification_count"):
                return {"notification_count": g.notification_count}

            from .models import Notification
            count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            g.notification_count = count
            return {"notification_count": count}
        return {"notification_count": 0}


def register_commands(app):
    from datetime import date

    import click

    from .extensions import db
    from .models import Assignment, Classroom, User

    @app.cli.command("seed")
    def seed():
        classroom = Classroom.query.filter_by(name="9A", school_year=date.today().year).first()
        if not classroom:
            classroom = Classroom(name="9A", school_year=date.today().year)
            db.session.add(classroom)
            db.session.flush()

        users_data = [
            ("Administrador", "admin@escola.local", "admin", None),
            ("Professor Demo", "prof@escola.local", "professor", None),
            ("Aluno Demo", "aluno@escola.local", "aluno", classroom.id),
            ("Psicologa Demo", "psi@escola.local", "psicologo", None),
        ]

        for full_name, email, role, classroom_id in users_data:
            existing = User.query.filter_by(email=email).first()
            if existing:
                continue
            user = User(full_name=full_name, email=email, role=role, classroom_id=classroom_id)
            user.set_password("123456")
            db.session.add(user)

        if not Assignment.query.first():
            teacher = User.query.filter_by(email="prof@escola.local").first()
            if teacher:
                assignment = Assignment(
                    title="Pesquisa sobre biomas brasileiros",
                    description="Preparar resumo de 2 paginas para apresentacao em sala.",
                    due_date=date.today(),
                    teacher_id=teacher.id,
                    classroom_id=classroom.id,
                )
                db.session.add(assignment)

        db.session.commit()
        click.echo("Seed concluido com sucesso.")


def create_default_chat_room():
    try:
        room = ChatRoom.query.filter_by(name="Geral").first()
        if not room:
            room = ChatRoom(name="Geral")
            db.session.add(room)
            db.session.commit()
    except OperationalError:
        # Tables may not exist yet before first migration/upgrade.
        db.session.rollback()
