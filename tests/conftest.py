"""
Fixtures compartilhadas para toda a suíte de testes.

Estratégia:
- App com SQLite in-memory + StaticPool (mesmo objeto de conexão em todas as threads)
- CSRF e rate-limiting desabilitados
- Cada função de teste recebe um banco limpo (create_all / drop_all por fixture)
- Helpers para criar usuários e autenticar sem passar pelo formulário
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from app.extensions import db as _db
from app.models import (
    Appointment,
    Assignment,
    ChatRoom,
    Classroom,
    Notification,
    User,
)


# ---------------------------------------------------------------------------
# App e banco
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    """Aplicação Flask configurada para testes (sessão inteira)."""
    test_config = dict(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_ENGINE_OPTIONS={
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,
        SECRET_KEY="test-secret-key-not-for-production",
        MAIL_SUPPRESS_SEND=True,
        SERVER_NAME=None,
    )
    flask_app = create_app(test_config=test_config)
    return flask_app


@pytest.fixture(autouse=True)
def setup_db(app):
    """Cria todas as tabelas antes de cada teste e as derruba no final."""
    with app.app_context():
        _db.create_all()
        # Garante sala de chat padrão
        if not ChatRoom.query.filter_by(name="Geral").first():
            _db.session.add(ChatRoom(name="Geral"))
            _db.session.commit()
        yield
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    """Cliente de teste HTTP."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Helpers de criação de entidades
# ---------------------------------------------------------------------------

def make_user(role: str, email: str, full_name: str = "Test User",
              password: str = "senha123", **kwargs) -> User:
    """Cria e persiste um usuário. Deve ser chamado dentro de app_context."""
    user = User(full_name=full_name, email=email, role=role, **kwargs)
    user.set_password(password)
    _db.session.add(user)
    _db.session.commit()
    return user


def make_classroom(name: str = "9A", school_year: int = 2026) -> Classroom:
    classroom = Classroom(name=name, school_year=school_year)
    _db.session.add(classroom)
    _db.session.commit()
    return classroom


def make_assignment(teacher: User, classroom: Classroom, **kwargs) -> Assignment:
    defaults = dict(
        title="Trabalho Teste",
        description="Descricao do trabalho teste.",
        due_date=date.today() + timedelta(days=7),
        teacher_id=teacher.id,
        classroom_id=classroom.id,
    )
    defaults.update(kwargs)
    assignment = Assignment(**defaults)
    _db.session.add(assignment)
    _db.session.commit()
    return assignment


def make_appointment(student: User, psychologist: User, **kwargs) -> Appointment:
    start = datetime.utcnow() + timedelta(days=1)
    defaults = dict(
        student_id=student.id,
        psychologist_id=psychologist.id,
        start_time=start,
        end_time=start + timedelta(minutes=40),
        status="pendente",
    )
    defaults.update(kwargs)
    appointment = Appointment(**defaults)
    _db.session.add(appointment)
    _db.session.commit()
    return appointment


# ---------------------------------------------------------------------------
# Fixtures de usuários pré-criados
# ---------------------------------------------------------------------------

def _detach(user: User) -> User:
    """Recarrega atributos do BD e desacopla da sessão para uso fora do contexto."""
    _db.session.refresh(user)
    _db.session.expunge(user)
    return user


@pytest.fixture
def admin_user(app):
    with app.app_context():
        return _detach(make_user("admin", "admin@test.com", "Admin Test"))


@pytest.fixture
def professor_user(app):
    with app.app_context():
        classroom = make_classroom()
        user = make_user("professor", "prof@test.com", "Prof Test")
        user.teaching_classrooms.append(classroom)
        _db.session.commit()
        return _detach(user)


@pytest.fixture
def student_user(app):
    with app.app_context():
        classroom = make_classroom()
        user = make_user(
            "aluno", "aluno@test.com", "Aluno Test",
            classroom_id=classroom.id,
        )
        return _detach(user)


@pytest.fixture
def psych_user(app):
    with app.app_context():
        return _detach(make_user("psicologo", "psi@test.com", "Psi Test"))


# ---------------------------------------------------------------------------
# Helpers de autenticação
# ---------------------------------------------------------------------------

def inject_session(client, user_id: int):
    """Injeta sessão autenticada sem passar pelo formulário de login."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def auth_client(client, app, user: User):
    """Retorna o cliente com sessão autenticada para o usuário informado."""
    with app.app_context():
        uid = user.id
    inject_session(client, uid)
    return client
