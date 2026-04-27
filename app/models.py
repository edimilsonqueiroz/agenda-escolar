from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# Tabela de associação: Professor <-> Turmas
teacher_classrooms = db.Table(
    "teacher_classrooms",
    db.Column("teacher_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("classroom_id", db.Integer, db.ForeignKey("classrooms.id"), primary_key=True),
)


class Classroom(TimestampMixin, db.Model):
    __tablename__ = "classrooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    number = db.Column(db.String(20), nullable=True)
    school_year = db.Column(db.Integer, nullable=False)

    students = db.relationship("User", back_populates="classroom", lazy=True)
    assignments = db.relationship("Assignment", back_populates="classroom", lazy=True)


class User(TimestampMixin, UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    is_active_user = db.Column(db.Boolean, default=True, nullable=False)
    can_chat = db.Column(db.Boolean, default=True, nullable=False)
    avatar = db.Column(db.String(255), nullable=True)
    crp_number = db.Column(db.String(30), nullable=True)

    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=True)
    classroom = db.relationship("Classroom", back_populates="students")

    # Relacionamento muitos-para-muitos: Professor <-> Turmas
    teaching_classrooms = db.relationship(
        "Classroom",
        secondary=teacher_classrooms,
        lazy=True,
        backref="teachers"
    )

    assignments_created = db.relationship("Assignment", back_populates="teacher", lazy=True)
    availabilities = db.relationship(
        "PsychologistAvailability",
        back_populates="psychologist",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Assignment(TimestampMixin, db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(100), nullable=True)          # disciplina
    description = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    attachment_path = db.Column(db.String(255), nullable=True)  # PDF anexado pelo professor
    is_finished = db.Column(db.Boolean, nullable=False, default=False)
    work_type = db.Column(db.String(20), nullable=False, default="individual")  # individual | group

    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey("classrooms.id"), nullable=False)

    teacher = db.relationship("User", back_populates="assignments_created")
    classroom = db.relationship("Classroom", back_populates="assignments")
    submissions = db.relationship("Submission", back_populates="assignment", lazy=True, cascade="all, delete-orphan")
    attachments = db.relationship("AssignmentAttachment", back_populates="assignment", lazy=True, cascade="all, delete-orphan")


class AssignmentAttachment(TimestampMixin, db.Model):
    __tablename__ = "assignment_attachments"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=True)

    assignment = db.relationship("Assignment", back_populates="attachments")


class Submission(TimestampMixin, db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assignments.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_group = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    file_path = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pendente")  # pendente | aprovado | devolvido
    grade = db.Column(db.String(20), nullable=True)        # nota livre (ex: "8.5", "A", "Excelente")
    feedback = db.Column(db.Text, nullable=True)           # comentário do professor

    assignment = db.relationship("Assignment", back_populates="submissions")
    student = db.relationship("User", foreign_keys=[student_id])
    group_members = db.relationship("SubmissionGroupMember", back_populates="submission", lazy=True)
    history_events = db.relationship("SubmissionHistoryEvent", back_populates="submission", lazy=True, cascade="all, delete-orphan")


class SubmissionGroupMember(TimestampMixin, db.Model):
    __tablename__ = "submission_group_members"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("submissions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    submission = db.relationship("Submission", back_populates="group_members")
    student = db.relationship("User")


class SubmissionHistoryEvent(TimestampMixin, db.Model):
    __tablename__ = "submission_history_events"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey("submissions.id"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(40), nullable=False)  # enviado | reenviado | aprovado | devolvido
    from_status = db.Column(db.String(20), nullable=True)
    to_status = db.Column(db.String(20), nullable=True)
    grade = db.Column(db.String(20), nullable=True)
    note = db.Column(db.Text, nullable=True)

    submission = db.relationship("Submission", back_populates="history_events")
    actor = db.relationship("User")


class Appointment(TimestampMixin, db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pendente")
    notes = db.Column(db.Text, nullable=True)
    psychologist_notes = db.Column(db.Text, nullable=True)
    chief_complaint = db.Column(db.Text, nullable=True)
    observed_behaviors = db.Column(db.Text, nullable=True)
    emotional_state = db.Column(db.Text, nullable=True)
    clinical_impression = db.Column(db.Text, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)
    next_steps = db.Column(db.Text, nullable=True)

    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    psychologist_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    student = db.relationship("User", foreign_keys=[student_id])
    psychologist = db.relationship("User", foreign_keys=[psychologist_id])
    referrals = db.relationship("Referral", back_populates="appointment", lazy=True, cascade="all, delete-orphan")


class Referral(TimestampMixin, db.Model):
    __tablename__ = "referrals"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id"), nullable=False, index=True)
    referral_type = db.Column(db.String(50), nullable=False)  # e.g., 'psiquiatra', 'fonoaudiologa', 'neurologista', 'assistente_social', 'outro'
    professional_name = db.Column(db.String(120), nullable=True)  # Nome do profissional para onde encaminhar
    institution = db.Column(db.String(200), nullable=True)  # Nome da instituição/clínica
    reason = db.Column(db.Text, nullable=False)  # Motivo do encaminhamento
    priority = db.Column(db.String(20), nullable=False, default="normal")  # 'urgente', 'normal', 'baixa'
    status = db.Column(db.String(20), nullable=False, default="pendente")  # 'pendente', 'recusado', 'realizado', 'cancelado'
    observations = db.Column(db.Text, nullable=True)  # Observações adicionais
    referral_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # Data do encaminhamento

    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    psychologist_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # Signature fields
    signature = db.Column(db.LargeBinary, nullable=True)  # PNG image data (base64 encoded)
    signature_date = db.Column(db.DateTime, nullable=True)  # When the referral was signed
    is_signed = db.Column(db.Boolean, nullable=False, default=False)  # Quick check if signed

    appointment = db.relationship("Appointment", back_populates="referrals")
    student = db.relationship("User", foreign_keys=[student_id])
    psychologist = db.relationship("User", foreign_keys=[psychologist_id])


class PsychologistAvailability(TimestampMixin, db.Model):
    __tablename__ = "psychologist_availabilities"

    id = db.Column(db.Integer, primary_key=True)
    psychologist_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    weekday = db.Column(db.Integer, nullable=False)  # 0=segunda ... 6=domingo
    period = db.Column(db.String(10), nullable=False)  # manha | tarde
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    psychologist = db.relationship("User", back_populates="availabilities")

    __table_args__ = (
        db.UniqueConstraint("psychologist_id", "weekday", "period", name="uq_psychologist_weekday_period"),
    )


class Notification(TimestampMixin, db.Model):
    """Notificações internas para usuários (ex: trabalho devolvido pelo professor)."""
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    link = db.Column(db.String(255), nullable=True)  # URL para redirecionar ao clicar

    user = db.relationship("User")


class ChatRoom(TimestampMixin, db.Model):
    __tablename__ = "chat_rooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class ChatMessage(TimestampMixin, db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)

    room_id = db.Column(db.Integer, db.ForeignKey("chat_rooms.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    room = db.relationship("ChatRoom")
    sender = db.relationship("User")
