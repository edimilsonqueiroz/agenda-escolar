"""
Testes do módulo de autenticação (app/auth/routes.py).

Cobre:
- GET  /login
- POST /login  (credenciais válidas / inválidas / usuário inativo / não aprovado)
- POST /logout
- GET  /register
- POST /register (cadastro válido / email duplicado / senha fraca / senhas diferentes)
"""
import pytest

from app.extensions import db
from app.models import User
from tests.conftest import inject_session, make_user


# ---------------------------------------------------------------------------
# Página de login
# ---------------------------------------------------------------------------

class TestLoginPage:
    def test_get_login_returns_200(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_authenticated_user_is_redirected_away(self, client, app, admin_user):
        inject_session(client, admin_user.id)
        resp = client.get("/login")
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------

class TestLoginPost:
    def test_valid_credentials_redirect_to_dashboard(self, client, app):
        with app.app_context():
            make_user("admin", "ok@test.com", password="correto")

        resp = client.post(
            "/login",
            data={"email": "ok@test.com", "password": "correto"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]

    def test_wrong_password_stays_on_login(self, client, app):
        with app.app_context():
            make_user("admin", "ok2@test.com", password="correto")

        resp = client.post(
            "/login",
            data={"email": "ok2@test.com", "password": "errado"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_nonexistent_user_stays_on_login(self, client):
        resp = client.post(
            "/login",
            data={"email": "naoexiste@test.com", "password": "qualquer"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_inactive_user_cannot_login(self, client, app):
        with app.app_context():
            make_user("aluno", "inativo@test.com", password="senha123",
                      is_active_user=False)

        resp = client.post(
            "/login",
            data={"email": "inativo@test.com", "password": "senha123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_unapproved_user_cannot_login(self, client, app):
        with app.app_context():
            make_user("aluno", "pendente@test.com", password="senha123",
                      is_approved=False)

        resp = client.post(
            "/login",
            data={"email": "pendente@test.com", "password": "senha123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_email_case_insensitive(self, client, app):
        with app.app_context():
            make_user("admin", "case@test.com", password="senha123")

        resp = client.post(
            "/login",
            data={"email": "CASE@TEST.COM", "password": "senha123"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_redirects_to_login(self, client, admin_user):
        inject_session(client, admin_user.id)
        resp = client.post("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_logout_unauthenticated_returns_401(self, client):
        resp = client.post("/logout")
        # flask-login redireciona para login ou retorna 401
        assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# GET /register
# ---------------------------------------------------------------------------

class TestRegisterPage:
    def test_get_register_returns_200(self, client):
        resp = client.get("/register")
        assert resp.status_code == 200

    def test_authenticated_user_redirected_away(self, client, admin_user):
        inject_session(client, admin_user.id)
        resp = client.get("/register")
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------

class TestRegisterPost:
    _VALID = dict(
        full_name="Novo Aluno",
        email="novo@test.com",
        password="senha123",
        confirm_password="senha123",
    )

    def test_valid_register_creates_unapproved_student(self, client, app):
        resp = client.post("/register", data=self._VALID, follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

        with app.app_context():
            user = User.query.filter_by(email="novo@test.com").first()
            assert user is not None
            assert user.role == "aluno"
            assert user.is_approved is False

    def test_duplicate_email_rejected(self, client, app):
        with app.app_context():
            make_user("aluno", "novo@test.com")

        resp = client.post("/register", data=self._VALID, follow_redirects=False)
        assert resp.status_code == 302
        assert "/register" in resp.headers["Location"]

    def test_short_password_rejected(self, client):
        data = {**self._VALID, "password": "12345", "confirm_password": "12345"}
        resp = client.post("/register", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "/register" in resp.headers["Location"]

    def test_mismatched_passwords_rejected(self, client):
        data = {**self._VALID, "confirm_password": "diferente"}
        resp = client.post("/register", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "/register" in resp.headers["Location"]

    def test_missing_full_name_rejected(self, client):
        data = {**self._VALID, "full_name": ""}
        resp = client.post("/register", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "/register" in resp.headers["Location"]

    def test_invalid_email_rejected(self, client):
        data = {**self._VALID, "email": "nao-e-email"}
        resp = client.post("/register", data=data, follow_redirects=False)
        assert resp.status_code == 302
        assert "/register" in resp.headers["Location"]
