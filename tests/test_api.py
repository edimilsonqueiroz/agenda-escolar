"""
Testes dos endpoints da API REST (app/api/routes.py).

Cobre:
- GET  /api/assignments   (por papel)
- GET  /api/appointments  (por papel)
- PATCH /api/appointments/<id>/status  (status válido/inválido, sem body, autorização)
- GET  /api/psychologists
- GET  /api/chat/messages  (sala pública, DM, recipient_id inválido)
- GET  /api/online-users
"""
import pytest

from app.extensions import db
from app.models import Appointment, Assignment, ChatMessage, ChatRoom, Classroom
from tests.conftest import (
    inject_session,
    make_appointment,
    make_assignment,
    make_classroom,
    make_user,
)


# ---------------------------------------------------------------------------
# Utilitário
# ---------------------------------------------------------------------------

def _api(client, user_id, method, url, **kwargs):
    inject_session(client, user_id)
    fn = getattr(client, method)
    return fn(url, **kwargs)


# ---------------------------------------------------------------------------
# GET /api/assignments
# ---------------------------------------------------------------------------

class TestListAssignments:
    def test_unauthenticated_is_redirected(self, client):
        resp = client.get("/api/assignments")
        assert resp.status_code == 302

    def test_aluno_sees_only_own_classroom(self, client, app):
        with app.app_context():
            room_a = make_classroom("9A")
            room_b = make_classroom("9B")
            prof = make_user("professor", "prof.a@test.com")
            aluno = make_user("aluno", "aluno.a@test.com",
                              classroom_id=room_a.id)
            make_assignment(prof, room_a, title="Trabalho A")
            make_assignment(prof, room_b, title="Trabalho B")
            uid = aluno.id

        inject_session(client, uid)
        resp = client.get("/api/assignments")
        assert resp.status_code == 200
        data = resp.get_json()
        titles = [item["title"] for item in data]
        assert "Trabalho A" in titles
        assert "Trabalho B" not in titles

    def test_professor_sees_only_own_assignments(self, client, app):
        with app.app_context():
            room = make_classroom()
            prof_a = make_user("professor", "prof.mine@test.com")
            prof_b = make_user("professor", "prof.other@test.com")
            make_assignment(prof_a, room, title="Meu Trabalho")
            make_assignment(prof_b, room, title="Trabalho Alheio")
            uid = prof_a.id

        inject_session(client, uid)
        resp = client.get("/api/assignments")
        assert resp.status_code == 200
        data = resp.get_json()
        titles = [item["title"] for item in data]
        assert "Meu Trabalho" in titles
        assert "Trabalho Alheio" not in titles

    def test_admin_sees_all_assignments(self, client, app):
        with app.app_context():
            room = make_classroom()
            prof = make_user("professor", "prof.admin@test.com")
            admin = make_user("admin", "admin.all@test.com")
            make_assignment(prof, room, title="Trabalho Admin")
            uid = admin.id

        inject_session(client, uid)
        resp = client.get("/api/assignments")
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(item["title"] == "Trabalho Admin" for item in data)

    def test_psicologo_sees_no_assignments(self, client, app):
        with app.app_context():
            room = make_classroom()
            prof = make_user("professor", "prof.psi@test.com")
            psi = make_user("psicologo", "psi.empty@test.com")
            make_assignment(prof, room)
            uid = psi.id

        inject_session(client, uid)
        resp = client.get("/api/assignments")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_response_schema_has_required_fields(self, client, app):
        with app.app_context():
            room = make_classroom()
            prof = make_user("professor", "prof.schema@test.com")
            admin = make_user("admin", "admin.schema@test.com")
            make_assignment(prof, room, title="Schema Check")
            uid = admin.id

        inject_session(client, uid)
        resp = client.get("/api/assignments")
        data = resp.get_json()
        assert len(data) > 0
        item = data[0]
        for key in ("id", "title", "description", "due_date", "classroom_id", "teacher"):
            assert key in item, f"Campo '{key}' ausente"


# ---------------------------------------------------------------------------
# GET /api/appointments
# ---------------------------------------------------------------------------

class TestListAppointments:
    def test_unauthenticated_is_redirected(self, client):
        resp = client.get("/api/appointments")
        assert resp.status_code == 302

    def test_aluno_sees_only_own_appointments(self, client, app):
        with app.app_context():
            aluno_a = make_user("aluno", "aluno.appt.a@test.com")
            aluno_b = make_user("aluno", "aluno.appt.b@test.com")
            psi = make_user("psicologo", "psi.appt@test.com")
            make_appointment(aluno_a, psi)
            make_appointment(aluno_b, psi)
            uid = aluno_a.id

        inject_session(client, uid)
        resp = client.get("/api/appointments")
        assert resp.status_code == 200
        data = resp.get_json()
        assert all(item["student"] is not None for item in data)
        assert len(data) == 1

    def test_psicologo_sees_own_appointments(self, client, app):
        with app.app_context():
            aluno = make_user("aluno", "aluno.psi@test.com")
            psi = make_user("psicologo", "psi.own@test.com")
            make_appointment(aluno, psi)
            uid = psi.id

        inject_session(client, uid)
        resp = client.get("/api/appointments")
        assert resp.status_code == 200
        assert len(resp.get_json()) == 1

    def test_professor_sees_empty_list(self, client, app):
        with app.app_context():
            prof = make_user("professor", "prof.appt@test.com")
            uid = prof.id

        inject_session(client, uid)
        resp = client.get("/api/appointments")
        assert resp.status_code == 200
        assert resp.get_json() == []


# ---------------------------------------------------------------------------
# PATCH /api/appointments/<id>/status
# ---------------------------------------------------------------------------

class TestUpdateAppointmentStatus:
    def test_psicologo_can_update_own_appointment(self, client, app):
        with app.app_context():
            aluno = make_user("aluno", "aluno.status@test.com")
            psi = make_user("psicologo", "psi.status@test.com")
            appt = make_appointment(aluno, psi)
            appt_id = appt.id
            uid = psi.id

        inject_session(client, uid)
        resp = client.patch(
            f"/api/appointments/{appt_id}/status",
            json={"status": "confirmado"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True

    def test_invalid_status_returns_400(self, client, app):
        with app.app_context():
            aluno = make_user("aluno", "aluno.inv@test.com")
            psi = make_user("psicologo", "psi.inv@test.com")
            appt = make_appointment(aluno, psi)
            appt_id = appt.id
            uid = psi.id

        inject_session(client, uid)
        resp = client.patch(
            f"/api/appointments/{appt_id}/status",
            json={"status": "invalido"},
        )
        assert resp.status_code == 400

    def test_empty_json_body_returns_400(self, client, app):
        with app.app_context():
            aluno = make_user("aluno", "aluno.empty@test.com")
            psi = make_user("psicologo", "psi.empty@test.com")
            appt = make_appointment(aluno, psi)
            appt_id = appt.id
            uid = psi.id

        inject_session(client, uid)
        resp = client.patch(
            f"/api/appointments/{appt_id}/status",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_psicologo_cannot_update_another_psychologist_appointment(self, client, app):
        with app.app_context():
            aluno = make_user("aluno", "aluno.other@test.com")
            psi_a = make_user("psicologo", "psi.a@test.com")
            psi_b = make_user("psicologo", "psi.b@test.com")
            appt = make_appointment(aluno, psi_a)
            appt_id = appt.id
            uid = psi_b.id

        inject_session(client, uid)
        resp = client.patch(
            f"/api/appointments/{appt_id}/status",
            json={"status": "confirmado"},
        )
        assert resp.status_code == 403

    def test_nonexistent_appointment_returns_404(self, client, app):
        with app.app_context():
            psi = make_user("psicologo", "psi.404@test.com")
            uid = psi.id

        inject_session(client, uid)
        resp = client.patch(
            "/api/appointments/999999/status",
            json={"status": "confirmado"},
        )
        assert resp.status_code == 404

    def test_aluno_cannot_update_status(self, client, app):
        with app.app_context():
            aluno = make_user("aluno", "aluno.forbidden@test.com")
            psi = make_user("psicologo", "psi.for@test.com")
            appt = make_appointment(aluno, psi)
            appt_id = appt.id
            uid = aluno.id

        inject_session(client, uid)
        resp = client.patch(
            f"/api/appointments/{appt_id}/status",
            json={"status": "confirmado"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/psychologists
# ---------------------------------------------------------------------------

class TestPsychologistsList:
    def test_returns_only_active_psychologists(self, client, app):
        with app.app_context():
            psi_active = make_user("psicologo", "psi.active@test.com",
                                   full_name="Psi Ativa")
            make_user("psicologo", "psi.inactive@test.com",
                      full_name="Psi Inativa", is_active_user=False)
            user = make_user("aluno", "req.psi@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/api/psychologists")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.get_json()]
        assert "Psi Ativa" in names
        assert "Psi Inativa" not in names

    def test_unauthenticated_is_redirected(self, client):
        resp = client.get("/api/psychologists")
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# GET /api/chat/messages
# ---------------------------------------------------------------------------

class TestChatMessages:
    def test_unauthenticated_is_redirected(self, client):
        resp = client.get("/api/chat/messages")
        assert resp.status_code == 302

    def test_public_room_returns_messages(self, client, app):
        with app.app_context():
            sender = make_user("admin", "chat.sender@test.com")
            room = ChatRoom.query.filter_by(name="Geral").first()
            msg = ChatMessage(content="Ola mundo", room_id=room.id,
                              sender_id=sender.id)
            db.session.add(msg)
            db.session.commit()
            uid = sender.id

        inject_session(client, uid)
        resp = client.get("/api/chat/messages?room=Geral")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert any(m["content"] == "Ola mundo" for m in data)

    def test_invalid_recipient_id_returns_400(self, client, app):
        with app.app_context():
            user = make_user("admin", "chat.invalid@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/api/chat/messages?recipient_id=abc")
        assert resp.status_code == 400
        assert "invalido" in resp.get_json().get("error", "")

    def test_unknown_room_returns_empty_list(self, client, app):
        with app.app_context():
            user = make_user("admin", "chat.empty@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/api/chat/messages?room=SalaQueNaoExiste")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_dm_room_between_users(self, client, app):
        with app.app_context():
            user_a = make_user("admin", "dm.a@test.com")
            user_b = make_user("professor", "dm.b@test.com")
            uid_a = user_a.id
            uid_b = user_b.id

        inject_session(client, uid_a)
        resp = client.get(f"/api/chat/messages?recipient_id={uid_b}")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_response_schema(self, client, app):
        with app.app_context():
            sender = make_user("admin", "schema.sender@test.com")
            room = ChatRoom.query.filter_by(name="Geral").first()
            db.session.add(ChatMessage(content="schema", room_id=room.id,
                                       sender_id=sender.id))
            db.session.commit()
            uid = sender.id

        inject_session(client, uid)
        resp = client.get("/api/chat/messages?room=Geral")
        data = resp.get_json()
        if data:
            msg = data[0]
            for key in ("id", "sender_id", "sender", "avatar", "content", "created_at"):
                assert key in msg, f"Campo '{key}' ausente na resposta"


# ---------------------------------------------------------------------------
# GET /api/online-users
# ---------------------------------------------------------------------------

class TestOnlineUsers:
    def test_returns_list(self, client, app):
        with app.app_context():
            user = make_user("admin", "online.user@test.com")
            uid = user.id

        inject_session(client, uid)
        resp = client.get("/api/online-users")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "online" in data
        assert isinstance(data["online"], list)
