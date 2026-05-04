"""
Testes das rotas principais (app/core/routes.py).

Cobre:
- GET /health
- GET /  (redirecionamentos)
- GET /dashboard  (todos os papéis)
- Controle de acesso por papel (admin, professor, aluno, psicologo)
- Rotas administrativas: turmas, usuários, estatísticas
- Parsing seguro de parâmetros de filtro (sem crash com valores inválidos)
"""
import pytest

from app.extensions import db
from app.models import Classroom, Submission, SubmissionGroupMember, User
from tests.conftest import (
    inject_session,
    make_assignment,
    make_classroom,
    make_user,
)


# ---------------------------------------------------------------------------
# Infraestrutura
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_health_returns_200_and_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.get_json() == {"status": "ok"}


class TestIndexRedirect:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_authenticated_redirects_to_dashboard(self, client, app):
        with app.app_context():
            user = make_user("admin", "idx.admin@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/dashboard" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Dashboard (por papel)
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_unauthenticated_redirected(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_admin_dashboard_returns_200(self, client, app):
        with app.app_context():
            user = make_user("admin", "dash.admin@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/dashboard")
        assert resp.status_code == 200

    def test_professor_dashboard_returns_200(self, client, app):
        with app.app_context():
            user = make_user("professor", "dash.prof@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/dashboard")
        assert resp.status_code == 200

    def test_aluno_dashboard_returns_200(self, client, app):
        with app.app_context():
            user = make_user("aluno", "dash.aluno@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/dashboard")
        assert resp.status_code == 200

    def test_psicologo_dashboard_returns_200(self, client, app):
        with app.app_context():
            user = make_user("psicologo", "dash.psi@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/dashboard")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Controle de acesso por papel
# ---------------------------------------------------------------------------

class TestAccessControl:
    """Rotas administrativas não devem ser acessíveis por outros papéis."""

    def _check_forbidden(self, client, app, role: str, email: str, path: str):
        with app.app_context():
            user = make_user(role, email)
            uid = user.id
        inject_session(client, uid)
        resp = client.get(path)
        assert resp.status_code == 403, (
            f"Esperava 403 para {role} em {path}, recebeu {resp.status_code}"
        )

    def test_professor_cannot_access_admin_users(self, client, app):
        self._check_forbidden(client, app, "professor",
                              "prof.ac1@test.com", "/admin/usuarios")

    def test_aluno_cannot_access_admin_users(self, client, app):
        self._check_forbidden(client, app, "aluno",
                              "aluno.ac2@test.com", "/admin/usuarios")

    def test_psicologo_cannot_access_admin_users(self, client, app):
        self._check_forbidden(client, app, "psicologo",
                              "psi.ac3@test.com", "/admin/usuarios")

    def test_aluno_cannot_access_admin_classrooms(self, client, app):
        self._check_forbidden(client, app, "aluno",
                              "aluno.cl@test.com", "/admin/turmas")

    def test_aluno_cannot_access_professor_assignments(self, client, app):
        self._check_forbidden(client, app, "aluno",
                              "aluno.prof@test.com", "/professor/trabalhos")

    def test_professor_cannot_access_psicologo_appointments(self, client, app):
        self._check_forbidden(client, app, "professor",
                              "prof.psi@test.com", "/psicologo/consultas")

    def test_aluno_cannot_access_admin_stats(self, client, app):
        self._check_forbidden(client, app, "aluno",
                              "aluno.stats@test.com", "/admin/estatisticas")

    def test_admin_can_access_admin_users(self, client, app):
        with app.app_context():
            user = make_user("admin", "admin.ok@test.com")
            uid = user.id
        inject_session(client, uid)
        resp = client.get("/admin/usuarios")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Parsing seguro de filtros (sem crash com valores inválidos)
# ---------------------------------------------------------------------------

class TestSafeFiltering:
    """Garantir que parâmetros inválidos na query string não causam 500."""

    def _check_no_crash(self, client, app, role: str, email: str, url: str):
        with app.app_context():
            user = make_user(role, email)
            uid = user.id
        inject_session(client, uid)
        resp = client.get(url)
        assert resp.status_code in (200, 302, 403, 404), (
            f"Resposta inesperada {resp.status_code} em {url}"
        )

    def test_admin_assignments_invalid_classroom_id(self, client, app):
        self._check_no_crash(
            client, app, "admin", "admin.filt1@test.com",
            "/admin/trabalhos?classroom_id=abc&teacher_id=xyz",
        )

    def test_professor_assignments_invalid_classroom_id(self, client, app):
        self._check_no_crash(
            client, app, "professor", "prof.filt2@test.com",
            "/professor/trabalhos?classroom_id=!@#$",
        )

    def test_professor_finished_assignments_invalid_classroom_id(self, client, app):
        self._check_no_crash(
            client, app, "professor", "prof.filt3@test.com",
            "/professor/trabalhos/finalizados?classroom_id=naoexiste",
        )

    def test_admin_classrooms_search_query(self, client, app):
        self._check_no_crash(
            client, app, "admin", "admin.search@test.com",
            "/admin/turmas?q=9A&year=invalido",
        )


# ---------------------------------------------------------------------------
# Rotas administrativas de turmas
# ---------------------------------------------------------------------------

class TestAdminClassrooms:
    def test_create_classroom(self, client, app):
        with app.app_context():
            admin = make_user("admin", "admin.cls@test.com")
            uid = admin.id

        inject_session(client, uid)
        resp = client.post(
            "/admin/turmas",
            data={"name": "8B", "number": "101", "school_year": "2026"},
            follow_redirects=False,
        )
        assert resp.status_code == 302

        with app.app_context():
            cls = Classroom.query.filter_by(name="8B").first()
            assert cls is not None
            assert cls.school_year == 2026

    def test_create_classroom_missing_fields_stays_on_page(self, client, app):
        with app.app_context():
            admin = make_user("admin", "admin.cls2@test.com")
            uid = admin.id

        inject_session(client, uid)
        resp = client.post(
            "/admin/turmas",
            data={"name": "", "school_year": ""},
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_delete_classroom(self, client, app):
        with app.app_context():
            admin = make_user("admin", "admin.del@test.com")
            cls = make_classroom("Para Deletar")
            cls_id = cls.id
            uid = admin.id

        inject_session(client, uid)
        resp = client.post(
            f"/admin/turmas/{cls_id}/excluir",
            follow_redirects=False,
        )
        assert resp.status_code == 302

        with app.app_context():
            assert Classroom.query.get(cls_id) is None


# ---------------------------------------------------------------------------
# Rotas do perfil
# ---------------------------------------------------------------------------

class TestProfile:
    def test_profile_page_returns_200_authenticated(self, client, app):
        with app.app_context():
            user = make_user("admin", "profile.ok@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/perfil")
        assert resp.status_code == 200


class TestStudentAssignmentSubmissions:
    def test_group_assignment_submission_is_saved_as_group(self, client, app):
        with app.app_context():
            classroom = make_classroom("9G")
            teacher = make_user("professor", "prof.group@test.com", classroom_id=classroom.id)
            leader = make_user("aluno", "leader.group@test.com", classroom_id=classroom.id)
            member = make_user("aluno", "member.group@test.com", classroom_id=classroom.id)
            assignment = make_assignment(
                teacher,
                classroom,
                title="Trabalho em Grupo",
                work_type="group",
            )
            leader_id = leader.id
            member_id = member.id
            assignment_id = assignment.id

        inject_session(client, leader_id)
        resp = client.post(
            f"/trabalho/{assignment_id}/submit",
            data={"group_members": [str(member_id)]},
            follow_redirects=False,
        )

        assert resp.status_code == 302

        with app.app_context():
            submission = Submission.query.filter_by(
                assignment_id=assignment_id,
                student_id=leader_id,
            ).first()
            assert submission is not None
            assert submission.is_group is True

            group_members = SubmissionGroupMember.query.filter_by(
                submission_id=submission.id,
            ).all()
            assert [item.student_id for item in group_members] == [member_id]

    def test_profile_page_redirects_unauthenticated(self, client):
        resp = client.get("/perfil")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
