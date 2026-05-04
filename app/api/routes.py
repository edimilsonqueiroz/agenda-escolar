from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from ..chat.socket_events import build_dm_room_name, online_users, parse_recipient_id
from ..constants import APPOINTMENT_SLOT_MINUTES, AppointmentStatus
from ..extensions import db, limiter
from ..models import Appointment, Assignment, ChatMessage, ChatRoom, PsychologistAvailability, User
from ..security import roles_required

api_bp = Blueprint("api", __name__)


@api_bp.get("/online-users")
@login_required
def online_users_placeholder():
    return jsonify({"online": list(online_users.values())})


@api_bp.get("/assignments")
@login_required
def list_assignments():
    query = Assignment.query

    if current_user.role == "aluno":
        query = query.filter_by(classroom_id=current_user.classroom_id)
    elif current_user.role == "professor":
        query = query.filter_by(teacher_id=current_user.id)
    elif current_user.role == "admin":
        # Admin pode ver todos os trabalhos
        pass
    else:
        # Outros roles não veem trabalhos
        query = query.filter_by(id=None)

    assignments = (
        query.options(joinedload(Assignment.teacher))
        .order_by(Assignment.due_date.asc())
        .limit(50)
        .all()
    )
    return jsonify(
        [
            {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "due_date": item.due_date.isoformat(),
                "classroom_id": item.classroom_id,
                "teacher": item.teacher.full_name,
            }
            for item in assignments
        ]
    )


@api_bp.get("/appointments")
@login_required
def list_appointments():
    query = Appointment.query

    if current_user.role == "aluno":
        query = query.filter_by(student_id=current_user.id)
    elif current_user.role == "psicologo":
        query = query.filter_by(psychologist_id=current_user.id)
    elif current_user.role == "professor":
        return jsonify([])

    appointments = (
        query.options(
            joinedload(Appointment.student),
            joinedload(Appointment.psychologist),
        )
        .order_by(Appointment.start_time.asc())
        .limit(50)
        .all()
    )
    return jsonify(
        [
            {
                "id": item.id,
                "start_time": item.start_time.isoformat(),
                "end_time": item.end_time.isoformat(),
                "status": item.status,
                "student": item.student.full_name,
                "psychologist": item.psychologist.full_name,
            }
            for item in appointments
        ]
    )


@api_bp.patch("/appointments/<int:appointment_id>/status")
@login_required
@roles_required("psicologo", "admin")
@limiter.limit("30/hour")
def update_appointment_status(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).strip().lower()

    if status not in AppointmentStatus.ALL:
        return jsonify({"error": "status invalido"}), 400

    if current_user.role == "psicologo" and appointment.psychologist_id != current_user.id:
        return jsonify({"error": "nao autorizado"}), 403

    appointment.status = status
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.get("/psychologists")
@login_required
def psychologists():
    people = User.query.filter_by(role="psicologo", is_active_user=True).all()
    return jsonify([{"id": p.id, "name": p.full_name} for p in people])


@api_bp.get("/psychologists/<int:psychologist_id>/weekly-slots")
@login_required
def psychologist_weekly_slots(psychologist_id):
    if current_user.role not in {"aluno", "admin", "psicologo"}:
        return jsonify({"error": "nao autorizado"}), 403

    psychologist = User.query.filter_by(id=psychologist_id, role="psicologo", is_active_user=True).first()
    if not psychologist:
        return jsonify({"error": "psicologo nao encontrado"}), 404

    week_offset = request.args.get("week", 0, type=int)
    today = datetime.utcnow().date()
    base_monday = today - timedelta(days=today.weekday())
    week_start = base_monday + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(5)]  # seg-sex

    availabilities = PsychologistAvailability.query.filter(
        PsychologistAvailability.psychologist_id == psychologist_id,
        PsychologistAvailability.weekday.in_([0, 1, 2, 3, 4]),
        PsychologistAvailability.is_active.is_(True),
    ).all()

    period_order = {"manha": 0, "tarde": 1}
    avail_map = {}
    for a in availabilities:
        avail_map.setdefault(a.weekday, []).append(a)

    for weekday in avail_map:
        avail_map[weekday].sort(key=lambda item: (period_order.get(item.period, 99), item.start_time))

    week_start_dt = datetime.combine(week_days[0], datetime.min.time())
    week_end_dt = datetime.combine(week_days[-1], datetime.max.time())
    appointments = Appointment.query.filter(
        Appointment.psychologist_id == psychologist_id,
        Appointment.start_time >= week_start_dt,
        Appointment.start_time <= week_end_dt,
        Appointment.status.in_(["pendente", "confirmado"]),
    ).all()

    appointments_by_day = {}
    for appt in appointments:
        key = appt.start_time.date().isoformat()
        appointments_by_day.setdefault(key, []).append(appt)

    now_dt = datetime.utcnow()
    day_names = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta"]
    payload_days = []

    for index, day in enumerate(week_days):
        day_availabilities = avail_map.get(day.weekday(), [])
        slots = []

        for availability in day_availabilities:
            cursor = datetime.combine(day, availability.start_time)
            day_end = datetime.combine(day, availability.end_time)

            while cursor + timedelta(minutes=APPOINTMENT_SLOT_MINUTES) <= day_end:
                slot_end = cursor + timedelta(minutes=APPOINTMENT_SLOT_MINUTES)
                if cursor < now_dt:
                    cursor += timedelta(minutes=APPOINTMENT_SLOT_MINUTES)
                    continue

                conflict_appt = None
                for appt in appointments_by_day.get(day.isoformat(), []):
                    if appt.start_time < slot_end and appt.end_time > cursor:
                        conflict_appt = appt
                        break

                # Aluno nao deve visualizar agendamentos de outros alunos.
                if current_user.role == "aluno" and conflict_appt and conflict_appt.student_id != current_user.id:
                    cursor += timedelta(minutes=APPOINTMENT_SLOT_MINUTES)
                    continue

                slots.append(
                    {
                        "value": cursor.strftime("%Y-%m-%dT%H:%M"),
                        "time": cursor.strftime("%H:%M"),
                        "reserved": bool(conflict_appt),
                    }
                )

                cursor += timedelta(minutes=APPOINTMENT_SLOT_MINUTES)

        payload_days.append(
            {
                "date": day.isoformat(),
                "day_name": day_names[index],
                "slots": slots,
            }
        )

    return jsonify(
        {
            "week_start": week_days[0].isoformat(),
            "week_end": week_days[-1].isoformat(),
            "days": payload_days,
        }
    )


@api_bp.get("/chat/messages")
@login_required
def chat_messages():
    room_name = (request.args.get("room") or "Geral").strip() or "Geral"
    recipient_id = parse_recipient_id(request.args.get("recipient_id"))

    # Se é uma conversa privada, criar nome de sala consistente
    if request.args.get("recipient_id") and recipient_id is None:
        return jsonify({"error": "recipient_id invalido"}), 400
    if recipient_id is not None:
        room_name = build_dm_room_name(current_user.id, recipient_id)

    room = ChatRoom.query.filter_by(name=room_name).first()
    if not room:
        return jsonify([])

    messages = (
        ChatMessage.query.filter_by(room_id=room.id)
        .options(joinedload(ChatMessage.sender))
        .order_by(ChatMessage.created_at.desc())
        .limit(80)
        .all()
    )
    return jsonify(
        [
            {
                "id": m.id,
                "sender_id": m.sender_id,
                "sender": m.sender.full_name,
                "avatar": m.sender.avatar or "",
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in reversed(messages)
        ]
    )
