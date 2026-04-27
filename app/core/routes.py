import os
import uuid
import base64
from io import BytesIO

from datetime import datetime, timedelta
from collections import defaultdict
from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib import colors as rl_colors

from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app, abort
from flask_login import current_user, login_required

from ..extensions import db, limiter
from ..models import Appointment, Assignment, AssignmentAttachment, Classroom, Notification, PsychologistAvailability, User, Submission, SubmissionGroupMember, SubmissionHistoryEvent, Referral
from ..security import roles_required
from ..constants import APPOINTMENT_SLOT_MINUTES, AppointmentStatus, UserRole

core_bp = Blueprint("core", __name__, template_folder="../templates")

VALID_ROLES = UserRole.ALL
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
ALLOWED_SUBMISSION_EXTENSIONS = {"pdf"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_SUBMISSION_SIZE = 10 * 1024 * 1024  # 10 MB
WEEKDAYS = [
    (0, "Segunda"),
    (1, "Terca"),
    (2, "Quarta"),
    (3, "Quinta"),
    (4, "Sexta"),
]
PERIODS = [
    ("manha", "Manha", "08:00", "12:00"),
    ("tarde", "Tarde", "13:00", "17:00"),
]
REFERRAL_TYPES = {
    "psiquiatra": "Psiquiatra",
    "neurologista": "Neurologista",
    "fonoaudiologa": "Fonoaudióloga",
    "pediatra": "Pediatra",
    "oftalmologista": "Oftalmologista",
    "otorrinolaringologista": "Otorrinolaringologista",
    "assistente_social": "Assistente Social",
    "terapeuta_ocupacional": "Terapeuta Ocupacional",
    "educacao_especial": "Educação Especial",
    "outro": "Outro",
}
IEMA_FULL_NAME = "Instituto Estadual de Educacao Ciencia e Tecnologia do Maranhao"



# ---------------------------------------------------------------------------
# PDF Design constants
# ---------------------------------------------------------------------------
PDF_MARGIN_X = 40
PDF_MARGIN_RIGHT = 40
PDF_FOOTER_HEIGHT = 30
PDF_COLOR_PRIMARY = rl_colors.HexColor("#1a3a6b")
PDF_COLOR_SECONDARY = rl_colors.HexColor("#2e6da4")
PDF_COLOR_ACCENT = rl_colors.HexColor("#4a90d9")
PDF_COLOR_LIGHT_BG = rl_colors.HexColor("#eaf1fb")
PDF_COLOR_HEADER_BG = rl_colors.HexColor("#1a3a6b")
PDF_COLOR_SECTION_BG = rl_colors.HexColor("#ddeaf9")
PDF_COLOR_ROW_ALT = rl_colors.HexColor("#f5f8fc")
PDF_COLOR_ROW_HEADER = rl_colors.HexColor("#2e6da4")
PDF_COLOR_TEXT = rl_colors.HexColor("#1a1a1a")
PDF_COLOR_GRAY = rl_colors.HexColor("#555555")
PDF_COLOR_LINE = rl_colors.HexColor("#b0c4de")
PDF_COLOR_WHITE = rl_colors.white
PDF_COLOR_GREEN = rl_colors.HexColor("#1e8449")
PDF_COLOR_ORANGE = rl_colors.HexColor("#d35400")
PDF_COLOR_RED = rl_colors.HexColor("#922b21")
PDF_COLOR_BLUE_DARK = rl_colors.HexColor("#154360")

STATUS_COLORS = {
    "realizado": PDF_COLOR_GREEN,
    "pendente": PDF_COLOR_ORANGE,
    "confirmado": PDF_COLOR_SECONDARY,
    "cancelado": PDF_COLOR_RED,
}


def _safe_pdf_text(value) -> str:
    """Normaliza texto para escrita em PDF sem quebra por encoding."""
    raw = (str(value) if value is not None else "").replace("\r", " ").replace("\n", " ").strip()
    return raw.encode("latin-1", "ignore").decode("latin-1")


def _pdf_inline_response(buffer: BytesIO, filename: str):
    """Retorna PDF para visualizacao inline no navegador (sem download automatico)."""
    buffer.seek(0)
    response = current_app.response_class(buffer.getvalue(), mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


def _get_iema_logo_path() -> str | None:
    """Retorna caminho da logo institucional do IEMA, se existir."""
    candidates = [
        os.path.join(current_app.root_path, "static", "img", "iema-logo.png"),
        os.path.join(current_app.root_path, "static", "img", "iema-logo.jpg"),
        os.path.join(current_app.root_path, "static", "img", "iema-logo.jpeg"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _draw_pdf_header(pdf, page_width: float, page_height: float, document_title: str, generated_at: datetime) -> float:
    """Desenha cabecalho profissional com faixa colorida e logo. Retorna Y do inicio do conteudo."""
    header_height = 70
    top_y = page_height - 20
    bar_y = top_y - header_height
    mx = PDF_MARGIN_X
    mr = PDF_MARGIN_RIGHT

    # Background azul escuro
    pdf.setFillColor(PDF_COLOR_HEADER_BG)
    pdf.rect(mx - 8, bar_y, page_width - mx - mr + 16, header_height + 2, fill=1, stroke=0)

    # Logo
    logo_path = _get_iema_logo_path()
    text_x = mx + 6
    logo_bottom = bar_y + 8
    logo_h = header_height - 16
    if logo_path:
        try:
            logo = ImageReader(logo_path)
            pdf.drawImage(logo, text_x, logo_bottom, width=logo_h, height=logo_h,
                          preserveAspectRatio=True, mask="auto")
            text_x += logo_h + 12
        except Exception:
            pass

    # Nome IEMA grande
    pdf.setFillColor(PDF_COLOR_WHITE)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(text_x, bar_y + header_height - 20, "IEMA")

    # Nome completo
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(rl_colors.HexColor("#ccddf5"))
    pdf.drawString(text_x, bar_y + header_height - 34, _safe_pdf_text(IEMA_FULL_NAME))

    # Titulo do documento
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(rl_colors.HexColor("#a8c8f0"))
    pdf.drawString(text_x, bar_y + header_height - 50, _safe_pdf_text(document_title))

    # Data/hora (direita)
    pdf.setFillColor(PDF_COLOR_WHITE)
    pdf.setFont("Helvetica", 9)
    date_str = _safe_pdf_text(generated_at.strftime("%d/%m/%Y %H:%M"))
    pdf.drawRightString(page_width - mr, bar_y + header_height - 20, date_str)
    pdf.setFillColor(rl_colors.HexColor("#ccddf5"))
    pdf.setFont("Helvetica", 8)
    pdf.drawRightString(page_width - mr, bar_y + header_height - 34, "Agenda Escolar - Documento Oficial")

    # Reset color
    pdf.setFillColor(PDF_COLOR_TEXT)

    return bar_y - 16


def _draw_pdf_footer(pdf, page_width: float, page_height: float, page_num: int, institution: str):
    """Desenha rodape com numero de pagina e nome da instituicao."""
    mx = PDF_MARGIN_X
    mr = PDF_MARGIN_RIGHT
    fy = PDF_FOOTER_HEIGHT
    pdf.setStrokeColor(PDF_COLOR_LINE)
    pdf.setLineWidth(0.5)
    pdf.line(mx - 8, fy + 12, page_width - mr + 8, fy + 12)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(mx - 8, fy, _safe_pdf_text(institution))
    pdf.drawRightString(page_width - mr + 8, fy, f"Pagina {page_num}")
    pdf.setFillColor(PDF_COLOR_TEXT)


def _draw_section_title(pdf, x: float, y: float, width: float, title: str) -> float:
    """Desenha titulo de secao com fundo colorido. Retorna novo Y."""
    h = 18
    pdf.setFillColor(PDF_COLOR_SECTION_BG)
    pdf.setStrokeColor(PDF_COLOR_ACCENT)
    pdf.setLineWidth(0)
    pdf.rect(x - 8, y - h + 4, width + 16, h, fill=1, stroke=0)
    # Barra lateral esquerda
    pdf.setFillColor(PDF_COLOR_SECONDARY)
    pdf.rect(x - 8, y - h + 4, 4, h, fill=1, stroke=0)
    pdf.setFillColor(PDF_COLOR_PRIMARY)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(x, y - 11, _safe_pdf_text(title.upper()))
    pdf.setFillColor(PDF_COLOR_TEXT)
    return y - h - 8


def _draw_info_row(pdf, x: float, y: float, label: str, value: str, col_width: float = 160) -> float:
    """Desenha uma linha label: valor formatada. Retorna novo Y."""
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.drawString(x, y, _safe_pdf_text(label))
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(PDF_COLOR_TEXT)
    pdf.drawString(x + col_width, y, _safe_pdf_text(value or "—"))
    return y - 16


def _draw_info_box(pdf, x: float, y: float, width: float, rows: list) -> float:
    """Desenha caixa de informacoes com multiplas linhas label: valor. Retorna novo Y."""
    line_h = 16
    padding = 10
    total_h = len(rows) * line_h + padding * 2
    pdf.setFillColor(PDF_COLOR_LIGHT_BG)
    pdf.setStrokeColor(PDF_COLOR_LINE)
    pdf.setLineWidth(0.5)
    pdf.roundRect(x - 8, y - total_h + padding, width + 16, total_h, 4, fill=1, stroke=1)
    cy = y - padding + 2
    for label, value in rows:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.setFillColor(PDF_COLOR_GRAY)
        pdf.drawString(x, cy, _safe_pdf_text(label))
        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(PDF_COLOR_TEXT)
        pdf.drawString(x + 150, cy, _safe_pdf_text(value or "—"))
        cy -= line_h
    pdf.setFillColor(PDF_COLOR_TEXT)
    return y - total_h - 10


def _draw_status_badge(pdf, x: float, y: float, status: str):
    """Desenha badge colorido de status ao lado do texto."""
    color = STATUS_COLORS.get(status, PDF_COLOR_GRAY)
    label = _safe_pdf_text(status.capitalize())
    pdf.setFont("Helvetica-Bold", 9)
    text_w = pdf.stringWidth(label, "Helvetica-Bold", 9)
    badge_w = text_w + 12
    badge_h = 14
    pdf.setFillColor(color)
    pdf.roundRect(x, y - 10, badge_w, badge_h, 3, fill=1, stroke=0)
    pdf.setFillColor(PDF_COLOR_WHITE)
    pdf.drawString(x + 6, y - 7, label)
    pdf.setFillColor(PDF_COLOR_TEXT)
    return x + badge_w + 6


def _wrap_text(text: str, max_chars: int = 90) -> list:
    """Quebra texto longo em linhas de ate max_chars caracteres."""
    text = _safe_pdf_text(text)
    if not text:
        return ["—"]
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > max_chars:
            if current:
                lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    if current:
        lines.append(current)
    return lines or ["—"]


def build_psychologist_report_data(psychologist_id: int, selected_student_id_raw: str = ""):
    """Monta dados do relatório de acompanhamentos do psicólogo."""
    students = (
        User.query.join(Appointment, Appointment.student_id == User.id)
        .filter(
            Appointment.psychologist_id == psychologist_id,
            User.role == "aluno",
        )
        .distinct()
        .order_by(User.full_name.asc())
        .all()
    )

    selected_student = None
    query = Appointment.query.filter_by(psychologist_id=psychologist_id).options(
        joinedload(Appointment.student),
        joinedload(Appointment.psychologist),
    )

    if selected_student_id_raw:
        if not selected_student_id_raw.isdigit():
            abort(404)

        student_id = int(selected_student_id_raw)
        selected_student = User.query.filter_by(id=student_id, role="aluno").first_or_404()

        has_appointments = Appointment.query.filter_by(
            psychologist_id=psychologist_id,
            student_id=student_id,
        ).first()
        if not has_appointments:
            abort(404)

        query = query.filter(Appointment.student_id == student_id)

    appointments = query.order_by(Appointment.start_time.desc()).all()

    status_counts = {
        "total": len(appointments),
        "pendente": 0,
        "confirmado": 0,
        "realizado": 0,
        "cancelado": 0,
    }
    by_student = defaultdict(lambda: {"student": None, "total": 0, "realizado": 0, "pendente": 0})

    for appointment in appointments:
        if appointment.status in status_counts:
            status_counts[appointment.status] += 1

        student_bucket = by_student[appointment.student_id]
        student_bucket["student"] = appointment.student
        student_bucket["total"] += 1
        if appointment.status == "realizado":
            student_bucket["realizado"] += 1
        if appointment.status in {"pendente", "confirmado"}:
            student_bucket["pendente"] += 1

    students_summary = sorted(
        by_student.values(),
        key=lambda item: item["student"].full_name.lower() if item["student"] else "",
    )

    return {
        "students": students,
        "selected_student": selected_student,
        "selected_student_id_raw": selected_student_id_raw,
        "appointments": appointments,
        "status_counts": status_counts,
        "students_summary": students_summary,
        "generated_at": datetime.utcnow(),
    }


def allowed_submission_file(filename: str) -> bool:
    """Verifica se arquivo é um PDF permitido para submissão."""
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_SUBMISSION_EXTENSIONS


def save_submission_file(file, assignment_id: int, student_id: int) -> str | None:
    """Salva arquivo de submissão e retorna o path relativo."""
    if not file or file.filename == "":
        return None
    
    if not allowed_submission_file(file.filename):
        return None
    
    # Verifica tamanho
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    file.seek(0)
    
    if file_length > MAX_SUBMISSION_SIZE:
        return None
    
    # Cria pasta de submissões se não existir
    submissions_dir = os.path.join(current_app.root_path, "static", "submissions")
    os.makedirs(submissions_dir, exist_ok=True)
    
    # Gera nome único para o arquivo
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"assignment_{assignment_id}_student_{student_id}_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(submissions_dir, filename)
    
    # Salva arquivo
    file.save(filepath)
    
    # Retorna path relativo
    return f"submissions/{filename}"


def allowed_avatar(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def parse_psychologist_availabilities(form):
    """Parseia agenda semanal (manha/tarde) enviada no formulario de usuario."""
    rows = []
    for weekday, _label in WEEKDAYS:
        for period_key, _period_label, _default_start, _default_end in PERIODS:
            enabled = form.get(f"availability_{weekday}_{period_key}_enabled") == "on"
            if not enabled:
                continue

            start_raw = (form.get(f"availability_{weekday}_{period_key}_start") or "").strip()
            end_raw = (form.get(f"availability_{weekday}_{period_key}_end") or "").strip()

            if not start_raw or not end_raw:
                raise ValueError("Informe horario inicial e final para os periodos ativos da agenda.")

            try:
                start_time = datetime.strptime(start_raw, "%H:%M").time()
                end_time = datetime.strptime(end_raw, "%H:%M").time()
            except ValueError as exc:
                raise ValueError("Formato de horario invalido na agenda da psicologa.") from exc

            if end_time <= start_time:
                raise ValueError("O horario final deve ser maior que o inicial em cada periodo da agenda.")

            rows.append({
                "weekday": weekday,
                "period": period_key,
                "start_time": start_time,
                "end_time": end_time,
            })

    return rows


def _read_pagination_params(default_per_page: int = 12, max_per_page: int = 100):
    """Le parametros de paginacao com limites seguros."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", default_per_page, type=int)
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = default_per_page
    if per_page > max_per_page:
        per_page = max_per_page
    return page, per_page


def is_datetime_within_psychologist_schedule(psychologist_id, start_dt, end_dt):
    """Verifica se o horario solicitado esta dentro de algum periodo da agenda configurada."""
    weekday = start_dt.weekday()
    availabilities = PsychologistAvailability.query.filter_by(
        psychologist_id=psychologist_id,
        weekday=weekday,
        is_active=True,
    ).all()

    for availability in availabilities:
        if start_dt.time() >= availability.start_time and end_dt.time() <= availability.end_time:
            return True

    return False



# ---------------------------------------------------------------------------
# Admin: estatísticas do sistema
# ---------------------------------------------------------------------------

@core_bp.get("/admin/estatisticas")
@login_required
@roles_required("admin")
def admin_stats():
    from ..models import ChatMessage

    # Contagens de usuários
    total_users = User.query.count()
    total_admins = User.query.filter_by(role="admin").count()
    total_professores = User.query.filter_by(role="professor").count()
    total_alunos = User.query.filter_by(role="aluno").count()
    total_psicologos = User.query.filter_by(role="psicologo").count()
    total_inativos = User.query.filter_by(is_active_user=False).count()

    # Contagens de conteúdo
    total_assignments = Assignment.query.count()
    total_classrooms = Classroom.query.count()
    total_appointments = Appointment.query.count()
    total_messages = ChatMessage.query.count()

    # Consultas por status
    appointments_pendentes = Appointment.query.filter_by(status="pendente").count()
    appointments_realizados = Appointment.query.filter_by(status="realizado").count()
    appointments_cancelados = Appointment.query.filter_by(status="cancelado").count()

    # Atividade recente (últimos 30 dias)
    cutoff = datetime.utcnow() - timedelta(days=30)
    novos_usuarios = User.query.filter(User.created_at >= cutoff).count()
    novos_trabalhos = Assignment.query.filter(Assignment.created_at >= cutoff).count()
    novas_consultas = Appointment.query.filter(Appointment.created_at >= cutoff).count()

    # Últimos usuários cadastrados
    recent_users = (
        User.query.order_by(User.created_at.desc()).limit(8).all()
    )

    # Turmas com mais alunos
    classrooms = (
        Classroom.query.order_by(Classroom.name.asc()).all()
    )

    return render_template(
        "admin/stats.html",
        total_users=total_users,
        total_admins=total_admins,
        total_professores=total_professores,
        total_alunos=total_alunos,
        total_psicologos=total_psicologos,
        total_inativos=total_inativos,
        total_assignments=total_assignments,
        total_classrooms=total_classrooms,
        total_appointments=total_appointments,
        total_messages=total_messages,
        appointments_pendentes=appointments_pendentes,
        appointments_realizados=appointments_realizados,
        appointments_cancelados=appointments_cancelados,
        novos_usuarios=novos_usuarios,
        novos_trabalhos=novos_trabalhos,
        novas_consultas=novas_consultas,
        recent_users=recent_users,
        classrooms=classrooms,
    )

@core_bp.get("/admin/usuarios")
@login_required
@roles_required("admin")
def admin_users():
    search = request.args.get("q", "").strip()
    role_filter = request.args.get("role", "").strip()
    page, per_page = _read_pagination_params(default_per_page=12, max_per_page=50)

    query = User.query
    if search:
        query = query.filter(
            (User.full_name.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%"))
        )
    if role_filter and role_filter in VALID_ROLES:
        query = query.filter_by(role=role_filter)
    
    # Excluir admins da listagem (não exibir na tabela)
    query = query.filter(User.role != "admin")

    users_pagination = query.order_by(User.role.asc(), User.full_name.asc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    users = users_pagination.items
    classrooms = Classroom.query.order_by(Classroom.name.asc()).all()

    availability_map = {}
    for user in users:
        if user.role != "psicologo":
            continue
        availability_map[user.id] = {
            f"{a.weekday}_{a.period}": {
                "start": a.start_time.strftime("%H:%M"),
                "end": a.end_time.strftime("%H:%M"),
                "active": bool(a.is_active),
            }
            for a in user.availabilities
        }

    stats = {
        "total": User.query.count(),
        "admin": User.query.filter_by(role="admin").count(),
        "professor": User.query.filter_by(role="professor").count(),
        "aluno": User.query.filter_by(role="aluno").count(),
        "psicologo": User.query.filter_by(role="psicologo").count(),
        "inativos": User.query.filter_by(is_active_user=False).count(),
    }

    return render_template(
        "admin/users.html",
        users=users,
        classrooms=classrooms,
        stats=stats,
        search=search,
        role_filter=role_filter,
        users_pagination=users_pagination,
        availability_map=availability_map,
        weekdays=WEEKDAYS,
        periods=PERIODS,
    )


@core_bp.get("/admin/alunos-pendentes")
@login_required
@roles_required("admin")
def admin_pending_students():
    """Lista alunos pendentes de aprovação"""
    page, per_page = _read_pagination_params(default_per_page=12, max_per_page=50)
    
    # Busca alunos não aprovados
    query = User.query.filter_by(role="aluno", is_approved=False)
    
    students_pagination = query.order_by(User.created_at.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    
    return render_template(
        "admin/pending_students.html",
        students=students_pagination.items,
        students_pagination=students_pagination,
    )


@core_bp.post("/admin/alunos/<int:student_id>/aprovar")
@login_required
@roles_required("admin")
def approve_student(student_id):
    """Aprova um aluno pendente"""
    student = User.query.get_or_404(student_id)
    
    if student.role != "aluno" or student.is_approved:
        flash("Operação inválida.", "danger")
        return redirect(url_for("core.admin_pending_students"))
    
    student.is_approved = True
    db.session.commit()
    flash(f"Aluno {student.full_name} aprovado com sucesso!", "success")
    return redirect(url_for("core.admin_pending_students"))


@core_bp.post("/admin/alunos/<int:student_id>/rejeitar")
@login_required
@roles_required("admin")
def reject_student(student_id):
    """Rejeita um aluno pendente (deleta a conta)"""
    student = User.query.get_or_404(student_id)
    
    if student.role != "aluno" or student.is_approved:
        flash("Operação inválida.", "danger")
        return redirect(url_for("core.admin_pending_students"))
    
    email = student.email
    db.session.delete(student)
    db.session.commit()
    flash(f"Aluno com email {email} rejeitado e removido.", "warning")
    return redirect(url_for("core.admin_pending_students"))


def _validate_user_form(full_name, email, role, availabilities_payload, *, require_password=False, password=""):
    """Valida campos comuns do formulario de criar/editar usuario.
    
    Retorna mensagem de erro (str) se invalido, ou None se valido.
    """
    if not full_name or not email or role not in VALID_ROLES:
        return "Preencha todos os campos obrigatorios corretamente."
    if role == UserRole.ADMIN:
        return "Nao e permitido atribuir o perfil Admin a um usuario."
    if role == UserRole.PSICOLOGO and not availabilities_payload:
        return "Defina ao menos um dia de agenda para a psicologa."
    if require_password and len(password) < 6:
        return "A senha deve ter ao menos 6 caracteres."
    return None


@core_bp.post("/admin/usuarios/novo")
@core_bp.post("/admin/usuarios")
@login_required
@roles_required("admin")
def admin_create_user():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "").strip()
    classroom_id = request.form.get("classroom_id") or None
    teaching_classrooms = request.form.getlist("teaching_classrooms")
    crp_number = request.form.get("crp_number", "").strip() or None

    try:
        availabilities_payload = parse_psychologist_availabilities(request.form)
    except ValueError as err:
        flash(str(err), "warning")
        return redirect(url_for("core.admin_users"))

    error = _validate_user_form(
        full_name, email, role, availabilities_payload,
        require_password=True, password=password,
    )
    if error:
        flash(error, "warning" if "Admin" not in error else "danger")
        return redirect(url_for("core.admin_users"))

    if User.query.filter_by(email=email).first():
        flash("E-mail ja cadastrado.", "danger")
        return redirect(url_for("core.admin_users"))

    user = User(
        full_name=full_name,
        email=email,
        role=role,
        classroom_id=int(classroom_id) if classroom_id else None,
        crp_number=crp_number if role == "psicologo" else None,
    )
    user.set_password(password)
    
    # Se for professor, adicionar turmas que ele vai lecionar
    if role == "professor" and teaching_classrooms:
        for classroom_id_str in teaching_classrooms:
            try:
                cid = int(classroom_id_str)
                c = Classroom.query.get(cid)
                if c:
                    user.teaching_classrooms.append(c)
            except (ValueError, TypeError):
                pass

    if role == "psicologo":
        for row in availabilities_payload:
            user.availabilities.append(
                PsychologistAvailability(
                    weekday=row["weekday"],
                    period=row["period"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    is_active=True,
                )
            )
    
    db.session.add(user)
    db.session.commit()

    flash(f"Usuario '{full_name}' criado com sucesso.", "success")
    return redirect(url_for("core.admin_users"))


@core_bp.post("/admin/usuarios/<int:user_id>/editar")
@login_required
@roles_required("admin")
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "").strip()
    classroom_id = request.form.get("classroom_id") or None
    teaching_classrooms = request.form.getlist("teaching_classrooms")
    crp_number = request.form.get("crp_number", "").strip() or None

    try:
        availabilities_payload = parse_psychologist_availabilities(request.form)
    except ValueError as err:
        flash(str(err), "warning")
        return redirect(url_for("core.admin_users"))

    error = _validate_user_form(full_name, email, role, availabilities_payload)
    if error:
        flash(error, "warning" if "Admin" not in error else "danger")
        return redirect(url_for("core.admin_users"))

    conflict = User.query.filter(User.email == email, User.id != user_id).first()
    if conflict:
        flash("E-mail ja utilizado por outro usuario.", "danger")
        return redirect(url_for("core.admin_users"))

    user.full_name = full_name
    user.email = email
    user.role = role
    user.classroom_id = int(classroom_id) if classroom_id else None
    user.crp_number = crp_number if role == "psicologo" else None
    
    # Se for professor, atualizar turmas que ele vai lecionar
    if role == "professor":
        user.teaching_classrooms.clear()
        if teaching_classrooms:
            for classroom_id_str in teaching_classrooms:
                try:
                    cid = int(classroom_id_str)
                    c = Classroom.query.get(cid)
                    if c:
                        user.teaching_classrooms.append(c)
                except (ValueError, TypeError):
                    pass
    else:
        # Se não for professor, limpar as turmas de ensino
        user.teaching_classrooms.clear()

    PsychologistAvailability.query.filter_by(psychologist_id=user.id).delete()
    db.session.flush()
    if role == "psicologo":
        for row in availabilities_payload:
            user.availabilities.append(
                PsychologistAvailability(
                    weekday=row["weekday"],
                    period=row["period"],
                    start_time=row["start_time"],
                    end_time=row["end_time"],
                    is_active=True,
                )
            )
    
    db.session.commit()

    flash(f"Usuario '{full_name}' atualizado.", "success")
    return redirect(url_for("core.admin_users"))


@core_bp.post("/admin/usuarios/<int:user_id>/toggle")
@login_required
@roles_required("admin")
@limiter.limit("30/hour")
def admin_toggle_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Voce nao pode desativar sua propria conta.", "warning")
        return redirect(url_for("core.admin_users"))

    user.is_active_user = not user.is_active_user
    db.session.commit()

    status = "ativado" if user.is_active_user else "desativado"
    flash(f"Usuario '{user.full_name}' {status}.", "success")
    return redirect(url_for("core.admin_users"))


@core_bp.post("/admin/usuarios/<int:user_id>/toggle-chat")
@login_required
@roles_required("admin")
def admin_toggle_chat(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Voce nao pode bloquear seu proprio chat.", "warning")
        return redirect(url_for("core.admin_users"))

    user.can_chat = not user.can_chat
    db.session.commit()

    status = "desbloqueado" if user.can_chat else "bloqueado"
    flash(f"Chat de '{user.full_name}' {status}.", "success")
    return redirect(url_for("core.admin_users"))


@core_bp.post("/admin/usuarios/<int:user_id>/senha")
@login_required
@roles_required("admin")
@limiter.limit("10/hour")
def admin_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("new_password", "").strip()

    if len(new_password) < 6:
        flash("A nova senha deve ter ao menos 6 caracteres.", "warning")
        return redirect(url_for("core.admin_users"))

    user.set_password(new_password)
    db.session.commit()

    flash(f"Senha de '{user.full_name}' redefinida com sucesso.", "success")
    return redirect(url_for("core.admin_users"))


@core_bp.post("/admin/usuarios/<int:user_id>/excluir")
@login_required
@roles_required("admin")
@limiter.limit("10/hour")
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Voce nao pode excluir sua propria conta.", "warning")
        return redirect(url_for("core.admin_users"))

    name = user.full_name
    db.session.delete(user)
    db.session.commit()

    flash(f"Usuario '{name}' excluido permanentemente.", "success")
    return redirect(url_for("core.admin_users"))


# ---------------------------------------------------------------------------
# Admin: Gerenciamento de Turmas
# ---------------------------------------------------------------------------

@core_bp.get("/admin/turmas")
@login_required
@roles_required("admin")
def admin_classrooms():
    search = request.args.get("q", "").strip()
    year_filter = request.args.get("year", "").strip()
    page, per_page = _read_pagination_params(default_per_page=10, max_per_page=50)

    query = Classroom.query
    if search:
        query = query.filter(Classroom.name.ilike(f"%{search}%"))
    if year_filter and year_filter.isdigit():
        query = query.filter_by(school_year=int(year_filter))

    classrooms_pagination = query.order_by(Classroom.school_year.desc(), Classroom.name.asc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    classrooms = classrooms_pagination.items

    return render_template(
        "admin/classrooms.html",
        classrooms=classrooms,
        search=search,
        year_filter=year_filter,
        classrooms_pagination=classrooms_pagination,
    )


@core_bp.post("/admin/turmas")
@login_required
@roles_required("admin")
def admin_create_classroom():
    name = request.form.get("name", "").strip()
    number = request.form.get("number", "").strip() or None
    school_year = request.form.get("school_year", "").strip()

    if not name or not school_year:
        flash("Preencha o nome e o ano da turma.", "warning")
        return redirect(url_for("core.admin_classrooms"))

    try:
        school_year = int(school_year)
    except ValueError:
        flash("Ano da turma invalido.", "warning")
        return redirect(url_for("core.admin_classrooms"))

    classroom = Classroom(name=name, number=number, school_year=school_year)
    db.session.add(classroom)
    db.session.commit()

    flash(f"Turma '{name}' criada com sucesso.", "success")
    return redirect(url_for("core.admin_classrooms"))


@core_bp.post("/admin/turmas/<int:classroom_id>/editar")
@login_required
@roles_required("admin")
def admin_edit_classroom(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)

    name = request.form.get("name", "").strip()
    number = request.form.get("number", "").strip() or None
    school_year = request.form.get("school_year", "").strip()

    if not name or not school_year:
        flash("Preencha o nome e o ano da turma.", "warning")
        return redirect(url_for("core.admin_classrooms"))

    try:
        school_year = int(school_year)
    except ValueError:
        flash("Ano da turma invalido.", "warning")
        return redirect(url_for("core.admin_classrooms"))

    classroom.name = name
    classroom.number = number
    classroom.school_year = school_year
    db.session.commit()

    flash(f"Turma '{name}' atualizada.", "success")
    return redirect(url_for("core.admin_classrooms"))


@core_bp.post("/admin/turmas/<int:classroom_id>/excluir")
@login_required
@roles_required("admin")
def admin_delete_classroom(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)

    name = classroom.name
    db.session.delete(classroom)
    db.session.commit()

    flash(f"Turma '{name}' excluida.", "success")
    return redirect(url_for("core.admin_classrooms"))


@core_bp.get("/dashboard")
@login_required
def dashboard():
    assignments = []
    appointments = []
    classrooms = []
    students = []
    stats_data = {}

    if current_user.role == "aluno":
        today = datetime.utcnow().date()
        now = datetime.utcnow()
        classroom_id = current_user.classroom_id

        total_assignments = 0
        submitted_assignments = 0
        pending_assignments = 0
        overdue_assignments = 0
        next_assignment = None

        if classroom_id:
            # Total: todos os trabalhos da turma (incluindo finalizados)
            total_assignments = Assignment.query.filter_by(classroom_id=classroom_id).count()

            # Entregas: todas as submissões do aluno na turma (incluindo trabalhos finalizados)
            submitted_assignments_query = (
                db.session.query(Submission.assignment_id)
                .join(Assignment, Submission.assignment_id == Assignment.id)
                .filter(
                    Submission.student_id == current_user.id,
                    Assignment.classroom_id == classroom_id,
                )
                .distinct()
            )
            submitted_assignments = submitted_assignments_query.count()

            submitted_ids_subquery = submitted_assignments_query.subquery()

            active_assignments_query = Assignment.query.filter(
                Assignment.classroom_id == classroom_id,
                Assignment.is_finished.is_(False),
            )

            # Atrasados: só trabalhos ativos (não finalizados)
            overdue_assignments = (
                active_assignments_query
                .filter(
                    Assignment.due_date < today,
                    ~Assignment.id.in_(submitted_ids_subquery),
                )
                .count()
            )

            # Próximo prazo: só trabalhos ativos (não finalizados)
            next_assignment = (
                active_assignments_query
                .filter(Assignment.due_date >= today)
                .order_by(Assignment.due_date.asc())
                .first()
            )

            # Pendentes: trabalhos ativos sem entrega do aluno
            pending_assignments = (
                active_assignments_query
                .filter(
                    ~Assignment.id.in_(submitted_ids_subquery),
                )
                .count()
            )

        total_appointments = Appointment.query.filter_by(student_id=current_user.id).count()
        pending_appointments = Appointment.query.filter(
            Appointment.student_id == current_user.id,
            Appointment.status.in_(["pendente", "confirmado"]),
        ).count()
        finished_appointments = Appointment.query.filter_by(
            student_id=current_user.id,
            status="realizado",
        ).count()

        next_appointment = (
            Appointment.query.filter(
                Appointment.student_id == current_user.id,
                Appointment.start_time >= now,
                Appointment.status.in_(["pendente", "confirmado"]),
            )
            .order_by(Appointment.start_time.asc())
            .first()
        )

        stats_data = dict(
            student_stats={
                "total_assignments": total_assignments,
                "submitted_assignments": submitted_assignments,
                "pending_assignments": pending_assignments,
                "overdue_assignments": overdue_assignments,
                "next_assignment": next_assignment,
                "total_appointments": total_appointments,
                "pending_appointments": pending_appointments,
                "finished_appointments": finished_appointments,
                "next_appointment": next_appointment,
            }
        )

    elif current_user.role == "professor":
        teacher_classroom_ids = [c.id for c in current_user.teaching_classrooms]
        total_my_assignments = Assignment.query.filter_by(teacher_id=current_user.id).count()
        total_submissions_rcv = (
            Submission.query
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .filter(Assignment.teacher_id == current_user.id)
            .count()
        )
        pending_evals = (
            Submission.query
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .filter(
                Assignment.teacher_id == current_user.id,
                Submission.status == "pendente",
            )
            .count()
        )
        approved_count = (
            Submission.query
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .filter(
                Assignment.teacher_id == current_user.id,
                Submission.status == "aprovado",
            )
            .count()
        )
        returned_count = (
            Submission.query
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .filter(
                Assignment.teacher_id == current_user.id,
                Submission.status == "devolvido",
            )
            .count()
        )
        stats_data = dict(
            professor_stats={
                "total_classrooms": len(teacher_classroom_ids),
                "total_my_assignments": total_my_assignments,
                "total_submissions": total_submissions_rcv,
                "pending_evals": pending_evals,
                "approved_count": approved_count,
                "returned_count": returned_count,
            }
        )

    elif current_user.role == "psicologo":
        now = datetime.utcnow()
        day_start = datetime.combine(now.date(), datetime.min.time())
        day_end = day_start + timedelta(days=1)

        base_query = Appointment.query.filter_by(psychologist_id=current_user.id)

        next_appointment = (
            base_query
            .options(joinedload(Appointment.student))
            .filter(
                Appointment.start_time >= now,
                Appointment.status.in_([AppointmentStatus.PENDENTE, AppointmentStatus.CONFIRMADO]),
            )
            .order_by(Appointment.start_time.asc())
            .first()
        )

        stats_data = dict(
            psychologist_stats={
                "total_appointments": base_query.count(),
                "open_appointments": base_query.filter(
                    Appointment.status.in_([AppointmentStatus.PENDENTE, AppointmentStatus.CONFIRMADO])
                ).count(),
                "completed_appointments": base_query.filter_by(status=AppointmentStatus.REALIZADO).count(),
                "canceled_appointments": base_query.filter_by(status=AppointmentStatus.CANCELADO).count(),
                "today_appointments": base_query.filter(
                    Appointment.start_time >= day_start,
                    Appointment.start_time < day_end,
                ).count(),
                "students_supported": (
                    db.session.query(Appointment.student_id)
                    .filter(Appointment.psychologist_id == current_user.id)
                    .distinct()
                    .count()
                ),
                "next_appointment": next_appointment,
            }
        )

    elif current_user.role == "admin":
        from ..models import ChatMessage

        # Admin pode ver todos os trabalhos do sistema
        assignments = (
            Assignment.query
            .order_by(Assignment.created_at.desc())
            .limit(30)
            .all()
        )
        classrooms = Classroom.query.order_by(Classroom.name.asc()).all()
        students = User.query.filter_by(role="aluno").order_by(User.full_name.asc()).limit(50).all()

        cutoff = datetime.utcnow() - timedelta(days=30)
        stats_data = dict(
            total_users=User.query.count(),
            total_admins=User.query.filter_by(role="admin").count(),
            total_professores=User.query.filter_by(role="professor").count(),
            total_alunos=User.query.filter_by(role="aluno").count(),
            total_psicologos=User.query.filter_by(role="psicologo").count(),
            total_inativos=User.query.filter_by(is_active_user=False).count(),
            total_assignments=Assignment.query.count(),
            total_classrooms=Classroom.query.count(),
            total_appointments=Appointment.query.count(),
            total_messages=ChatMessage.query.count(),
            appointments_pendentes=Appointment.query.filter_by(status="pendente").count(),
            appointments_realizados=Appointment.query.filter_by(status="realizado").count(),
            appointments_cancelados=Appointment.query.filter_by(status="cancelado").count(),
            novos_usuarios=User.query.filter(User.created_at >= cutoff).count(),
            novos_trabalhos=Assignment.query.filter(Assignment.created_at >= cutoff).count(),
            novas_consultas=Appointment.query.filter(Appointment.created_at >= cutoff).count(),
            recent_users=User.query.order_by(User.created_at.desc()).limit(8).all(),
        )

    return render_template(
        "dashboard.html",
        assignments=assignments,
        appointments=appointments,
        classrooms=classrooms,
        students=students,
        now=datetime.utcnow(),
        unread_notifications=Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).limit(10).all(),
        **stats_data,
    )


@core_bp.get("/psicologo/consultas")
@login_required
@roles_required("psicologo")
def psychologist_appointments():
    status_filter = (request.args.get("status") or "").strip().lower()
    page, per_page = _read_pagination_params(default_per_page=10, max_per_page=50)
    valid_statuses = {
        AppointmentStatus.PENDENTE,
        AppointmentStatus.CONFIRMADO,
        AppointmentStatus.REALIZADO,
        AppointmentStatus.CANCELADO,
    }

    query = (
        Appointment.query
        .filter_by(psychologist_id=current_user.id)
        .options(joinedload(Appointment.student), joinedload(Appointment.psychologist))
    )
    unfiltered_query = Appointment.query.filter_by(psychologist_id=current_user.id)

    if status_filter in valid_statuses:
        query = query.filter(Appointment.status == status_filter)
    else:
        status_filter = ""

    appointments_pagination = query.order_by(Appointment.start_time.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    appointments = appointments_pagination.items

    # weekly calendar data
    now = datetime.utcnow()
    today = now.date()
    week_offset = request.args.get("week", 0, type=int)
    base_monday = today - timedelta(days=today.weekday())
    week_start = base_monday + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(5)]
    week_end = week_days[-1]

    weekly_appts = (
        Appointment.query
        .filter_by(psychologist_id=current_user.id)
        .options(joinedload(Appointment.student))
        .filter(
            Appointment.start_time >= datetime.combine(week_start, datetime.min.time()),
            Appointment.start_time <= datetime.combine(week_end, datetime.max.time()),
        )
        .order_by(Appointment.start_time.asc())
        .all()
    )

    appointments_by_day = defaultdict(list)
    for appt in weekly_appts:
        appointments_by_day[appt.start_time.date()].append(appt)

    return render_template(
        "psychologist/appointments.html",
        appointments=appointments,
        appointments_pagination=appointments_pagination,
        status_filter=status_filter,
        status_counts={
            "total": unfiltered_query.count(),
            "pendente": unfiltered_query.filter_by(status=AppointmentStatus.PENDENTE).count(),
            "confirmado": unfiltered_query.filter_by(status=AppointmentStatus.CONFIRMADO).count(),
            "realizado": unfiltered_query.filter_by(status=AppointmentStatus.REALIZADO).count(),
            "cancelado": unfiltered_query.filter_by(status=AppointmentStatus.CANCELADO).count(),
        },
        week_offset=week_offset,
        week_start=week_start,
        week_end=week_end,
        week_days=week_days,
        today=today,
        appointments_by_day=appointments_by_day,
    )


@core_bp.get("/aluno/trabalhos")
@login_required
@roles_required("aluno")
def student_assignments():
    assignments = []
    assignment_statuses = {}

    # Weekly calendar params
    now = datetime.utcnow()
    today = now.date()
    week_offset = request.args.get("week", 0, type=int)
    base_monday = today - timedelta(days=today.weekday())
    week_start = base_monday + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(5)]
    week_end = week_days[-1]
    assignments_by_day = defaultdict(list)

    if current_user.classroom_id:
        # All active assignments (for calendar, fetch entire period)
        all_assignments = (
            Assignment.query
            .options(joinedload(Assignment.teacher))
            .filter_by(classroom_id=current_user.classroom_id, is_finished=False)
            .order_by(Assignment.due_date.asc(), Assignment.created_at.desc())
            .all()
        )
        assignments = all_assignments
        assignment_ids = [item.id for item in assignments]

        direct_rows = []
        group_rows = []
        if assignment_ids:
            direct_rows = (
                db.session.query(Submission.assignment_id, Submission.status)
                .join(Assignment, Submission.assignment_id == Assignment.id)
                .filter(
                    Submission.student_id == current_user.id,
                    Assignment.classroom_id == current_user.classroom_id,
                    Assignment.id.in_(assignment_ids),
                )
                .all()
            )
            group_rows = (
                db.session.query(Submission.assignment_id, Submission.status)
                .join(SubmissionGroupMember, SubmissionGroupMember.submission_id == Submission.id)
                .join(Assignment, Submission.assignment_id == Assignment.id)
                .filter(
                    SubmissionGroupMember.student_id == current_user.id,
                    Assignment.classroom_id == current_user.classroom_id,
                    Assignment.id.in_(assignment_ids),
                )
                .all()
            )

        for assignment_id, status in [*direct_rows, *group_rows]:
            current = assignment_statuses.get(assignment_id)
            if current == "devolvido":
                continue
            if status == "devolvido" or current is None:
                assignment_statuses[assignment_id] = status

        # Group assignments by due_date for weekly view
        for a in all_assignments:
            assignments_by_day[a.due_date].append(a)

    return render_template(
        "student/assignments.html",
        assignments=assignments,
        assignment_statuses=assignment_statuses,
        assignments_by_day=assignments_by_day,
        week_offset=week_offset,
        week_start=week_start,
        week_end=week_end,
        week_days=week_days,
        today=today,
        student_classroom=current_user.classroom if current_user.classroom_id else None,
    )


@core_bp.get("/aluno/agendamentos")
@login_required
@roles_required("aluno")
def student_appointments():
    page, per_page = _read_pagination_params(default_per_page=10, max_per_page=50)
    appointments_pagination = (
        Appointment.query.filter_by(student_id=current_user.id)
        .order_by(Appointment.start_time.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    appointments = appointments_pagination.items

    return render_template(
        "student/appointments.html",
        appointments=appointments,
        appointments_pagination=appointments_pagination,
    )


@core_bp.post("/assignments")
@login_required
@roles_required("professor")
def create_assignment():
    title = request.form.get("title", "").strip()
    subject = request.form.get("subject", "").strip()
    description = request.form.get("description", "").strip()
    due_date_raw = request.form.get("due_date", "").strip()
    classroom_id = request.form.get("classroom_id")
    work_type = request.form.get("work_type", "individual")
    if work_type not in ("individual", "group"):
        work_type = "individual"

    if not title or not description or not due_date_raw or not classroom_id:
        flash("Preencha todos os campos do trabalho.", "warning")
        return redirect(url_for("core.professor_assignments"))

    try:
        due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date()
        classroom_id = int(classroom_id)
    except ValueError:
        flash("Dados invalidos no cadastro de trabalho.", "danger")
        return redirect(url_for("core.professor_assignments"))

    if due_date < datetime.today().date():
        flash("A data de entrega não pode ser anterior ao dia de hoje.", "warning")
        return redirect(url_for("core.professor_assignments"))

    # Salva anexos PDF (opcional, múltiplos)
    files = request.files.getlist("attachment")
    attach_dir = os.path.join(current_app.root_path, "static", "submissions")
    os.makedirs(attach_dir, exist_ok=True)
    saved_attachments = []
    for file in files:
        if not file or not file.filename:
            continue
        if not allowed_submission_file(file.filename):
            flash("Apenas arquivos PDF sao permitidos como anexo.", "warning")
            return redirect(url_for("core.professor_assignments"))
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > 10 * 1024 * 1024:
            flash("O arquivo PDF nao pode ultrapassar 10 MB.", "warning")
            return redirect(url_for("core.professor_assignments"))
        ext = file.filename.rsplit(".", 1)[1].lower()
        safe_name = f"assignment_attach_{current_user.id}_{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(attach_dir, safe_name))
        saved_attachments.append((f"submissions/{safe_name}", file.filename))

    assignment = Assignment(
        title=title,
        subject=subject or None,
        description=description,
        due_date=due_date,
        work_type=work_type,
        teacher_id=current_user.id,
        classroom_id=classroom_id,
        attachment_path=saved_attachments[0][0] if saved_attachments else None,
    )
    db.session.add(assignment)
    db.session.flush()  # garante assignment.id antes de criar attachments
    for path, orig_name in saved_attachments:
        db.session.add(AssignmentAttachment(
            assignment_id=assignment.id,
            file_path=path,
            original_name=orig_name,
        ))
    db.session.commit()

    flash("Trabalho cadastrado com sucesso.", "success")
    return redirect(url_for("core.professor_assignments"))


@core_bp.post("/appointments")
@login_required
@roles_required("aluno")
def create_appointment():
    appointments_page_url = url_for("core.student_appointments")
    start_time_raw = request.form.get("start_time", "").strip()
    psychologist_id_raw = request.form.get("psychologist_id", "").strip()
    notes = request.form.get("notes", "").strip()

    if not start_time_raw or not psychologist_id_raw:
        flash("Informe data/hora e psicologo(a).", "warning")
        return redirect(appointments_page_url)

    try:
        start_time = datetime.strptime(start_time_raw, "%Y-%m-%dT%H:%M")
        end_time = start_time + timedelta(minutes=APPOINTMENT_SLOT_MINUTES)
        psychologist_id = int(psychologist_id_raw)
    except ValueError:
        flash("Formato de data invalido.", "danger")
        return redirect(appointments_page_url)

    if start_time < datetime.utcnow():
        flash("Nao e possivel agendar em horario passado.", "warning")
        return redirect(appointments_page_url)

    psychologist = User.query.filter_by(id=psychologist_id, role="psicologo", is_active_user=True).first()
    if not psychologist:
        flash("Psicologo(a) invalido ou inativo.", "danger")
        return redirect(appointments_page_url)

    if not is_datetime_within_psychologist_schedule(psychologist_id, start_time, end_time):
        flash("Horario fora da agenda disponivel da psicologa.", "danger")
        return redirect(appointments_page_url)

    conflict = Appointment.query.filter(
        Appointment.psychologist_id == psychologist_id,
        Appointment.start_time < end_time,
        Appointment.end_time > start_time,
        Appointment.status.in_(["pendente", "confirmado"]),
    ).first()

    if conflict:
        flash("Horario indisponivel para este psicologo(a).", "danger")
        return redirect(appointments_page_url)

    appointment = Appointment(
        student_id=current_user.id,
        psychologist_id=psychologist_id,
        start_time=start_time,
        end_time=end_time,
        status="pendente",
        notes=notes or None,
    )
    db.session.add(appointment)
    db.session.commit()

    flash("Agendamento solicitado com sucesso.", "success")
    return redirect(appointments_page_url)


@core_bp.get("/consultas/<int:appointment_id>/registro")
@login_required
@roles_required("psicologo")
def appointment_record_page(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.psychologist_id != current_user.id:
        abort(403)

    can_edit = appointment.status in {"pendente", "confirmado"}
    return render_template("appointment_record.html", appointment=appointment, can_edit=can_edit)


@core_bp.get("/psicologo/relatorios")
@login_required
@roles_required("psicologo")
def psychologist_reports():
    student_id = (request.args.get("student_id") or "").strip()
    page, per_page = _read_pagination_params(default_per_page=12, max_per_page=50)
    report_data = build_psychologist_report_data(current_user.id, student_id)

    all_appointments = report_data["appointments"]
    appointments_total = len(all_appointments)
    start_index = (page - 1) * per_page
    end_index = start_index + per_page
    report_data["appointments"] = all_appointments[start_index:end_index]
    report_data["appointments_page"] = page
    report_data["appointments_per_page"] = per_page
    report_data["appointments_total"] = appointments_total

    return render_template("psychologist/reports.html", **report_data)


@core_bp.get("/psicologo/relatorios/imprimir")
@login_required
@roles_required("psicologo")
def psychologist_print_reports():
    student_id = (request.args.get("student_id") or "").strip()
    report_data = build_psychologist_report_data(current_user.id, student_id)

    appointments = report_data["appointments"]
    selected_student = report_data["selected_student"]
    status_counts = report_data["status_counts"]
    generated_at = report_data["generated_at"]

    doc_title = "Relatorio de Acompanhamentos Psicologicos"
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("Relatorio de Acompanhamentos Psicologicos")
    pdf.setAuthor(_safe_pdf_text(current_user.full_name))
    pdf.setSubject("Relatorio Psicologico - Agenda Escolar IEMA")
    page_width, page_height = A4
    mx = PDF_MARGIN_X
    mr = PDF_MARGIN_RIGHT
    content_width = page_width - mx - mr
    page_num = [1]

    def new_page():
        nonlocal y
        _draw_pdf_footer(pdf, page_width, page_height, page_num[0], IEMA_FULL_NAME)
        pdf.showPage()
        page_num[0] += 1
        y = _draw_pdf_header(pdf, page_width, page_height, doc_title, generated_at)

    def ensure_space(needed: float = 20):
        nonlocal y
        if y - needed < PDF_FOOTER_HEIGHT + 20:
            new_page()

    y = _draw_pdf_header(pdf, page_width, page_height, doc_title, generated_at)

    # --- Bloco de identificacao ---
    scope_text = f"{selected_student.full_name}" if selected_student else "Todos os alunos atendidos"
    y = _draw_info_box(pdf, mx, y, content_width, [
        ("Psicologo(a) responsavel:", current_user.full_name),
        ("E-mail:", current_user.email),
        ("Escopo do relatorio:", scope_text),
        ("Data de geracao:", generated_at.strftime("%d/%m/%Y as %H:%M")),
    ])

    # --- Cards de resumo ---
    ensure_space(50)
    y = _draw_section_title(pdf, mx, y, content_width, "Resumo Estatistico")

    card_w = (content_width - 12) / 4
    card_h = 42
    cards = [
        ("Total", status_counts["total"], PDF_COLOR_PRIMARY),
        ("Realizados", status_counts["realizado"], PDF_COLOR_GREEN),
        ("Pendentes", status_counts["pendente"] + status_counts["confirmado"], PDF_COLOR_ORANGE),
        ("Cancelados", status_counts["cancelado"], PDF_COLOR_RED),
    ]
    for i, (label, value, color) in enumerate(cards):
        cx = mx + i * (card_w + 4)
        pdf.setFillColor(color)
        pdf.roundRect(cx, y - card_h, card_w, card_h, 5, fill=1, stroke=0)
        pdf.setFillColor(PDF_COLOR_WHITE)
        pdf.setFont("Helvetica-Bold", 22)
        num_str = str(value)
        num_w = pdf.stringWidth(num_str, "Helvetica-Bold", 22)
        pdf.drawString(cx + (card_w - num_w) / 2, y - card_h + 20, num_str)
        pdf.setFont("Helvetica", 9)
        lbl_w = pdf.stringWidth(_safe_pdf_text(label), "Helvetica", 9)
        pdf.drawString(cx + (card_w - lbl_w) / 2, y - card_h + 6, _safe_pdf_text(label))
    pdf.setFillColor(PDF_COLOR_TEXT)
    y -= card_h + 14

    # --- Tabela de acompanhamentos ---
    ensure_space(60)
    y = _draw_section_title(pdf, mx, y, content_width, "Acompanhamentos Detalhados")

    if not appointments:
        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(PDF_COLOR_GRAY)
        pdf.drawString(mx, y - 4, "Nenhum acompanhamento encontrado.")
        y -= 20
        pdf.setFillColor(PDF_COLOR_TEXT)
    else:
        # Cabecalho da tabela
        col_w = [40, 110, 120, 70, content_width - 40 - 110 - 120 - 70]
        col_labels = ["Proto.", "Data/Hora", "Aluno(a)", "Status", "Observacao do Aluno"]
        row_h = 16
        ensure_space(row_h + 4)
        pdf.setFillColor(PDF_COLOR_ROW_HEADER)
        pdf.rect(mx - 4, y - row_h, content_width + 8, row_h, fill=1, stroke=0)
        cx = mx
        pdf.setFillColor(PDF_COLOR_WHITE)
        pdf.setFont("Helvetica-Bold", 9)
        for i, lbl in enumerate(col_labels):
            pdf.drawString(cx + 2, y - row_h + 5, _safe_pdf_text(lbl))
            cx += col_w[i]
        y -= row_h
        pdf.setFillColor(PDF_COLOR_TEXT)

        for idx, appt in enumerate(appointments):
            note_lines = _wrap_text(appt.notes or "", max_chars=40)
            needed_h = max(row_h, len(note_lines) * 12 + 6)
            ensure_space(needed_h + 4)

            # Linha alternada
            if idx % 2 == 0:
                pdf.setFillColor(PDF_COLOR_ROW_ALT)
                pdf.rect(mx - 4, y - needed_h, content_width + 8, needed_h, fill=1, stroke=0)

            pdf.setFillColor(PDF_COLOR_TEXT)
            pdf.setFont("Helvetica-Bold", 9)
            cx = mx
            # Protocolo
            pdf.drawString(cx + 2, y - 13, f"#{appt.id}")
            cx += col_w[0]
            # Data/hora
            pdf.setFont("Helvetica", 9)
            pdf.drawString(cx + 2, y - 13, _safe_pdf_text(appt.start_time.strftime("%d/%m/%Y")))
            pdf.setFillColor(PDF_COLOR_GRAY)
            pdf.drawString(cx + 2, y - 24, _safe_pdf_text(appt.start_time.strftime("%H:%M") + " - " + appt.end_time.strftime("%H:%M")))
            pdf.setFillColor(PDF_COLOR_TEXT)
            cx += col_w[1]
            # Aluno
            pdf.setFont("Helvetica", 9)
            pdf.drawString(cx + 2, y - 13, _safe_pdf_text(appt.student.full_name[:22]))
            cx += col_w[2]
            # Status badge
            _draw_status_badge(pdf, cx + 2, y - 5, appt.status)
            cx += col_w[3]
            # Observacao (multiline)
            pdf.setFillColor(PDF_COLOR_GRAY)
            pdf.setFont("Helvetica", 8.5)
            for li, line in enumerate(note_lines):
                pdf.drawString(cx + 2, y - 11 - li * 13, _safe_pdf_text(line))
            pdf.setFillColor(PDF_COLOR_TEXT)

            # Linha horizontal
            pdf.setStrokeColor(PDF_COLOR_LINE)
            pdf.setLineWidth(0.3)
            pdf.line(mx - 4, y - needed_h, mx + content_width + 4, y - needed_h)
            y -= needed_h

    # --- Assinatura ---
    ensure_space(80)
    y -= 16
    y = _draw_section_title(pdf, mx, y, content_width, "Assinatura do Responsavel")
    y -= 20
    sig_w = min(240, content_width - 20)
    pdf.setFillColor(PDF_COLOR_LIGHT_BG)
    pdf.setStrokeColor(PDF_COLOR_LINE)
    pdf.setLineWidth(0.6)
    pdf.roundRect(mx, y - 56, sig_w, 56, 4, fill=1, stroke=1)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.setFont("Helvetica", 9.5)
    pdf.drawString(mx + 10, y - 16, _safe_pdf_text(f"Psicologo(a): {current_user.full_name}"))
    pdf.drawString(mx + 10, y - 30, _safe_pdf_text(f"E-mail: {current_user.email}"))
    pdf.setLineWidth(0.8)
    pdf.setStrokeColor(PDF_COLOR_PRIMARY)
    pdf.line(mx + 10, y - 44, mx + sig_w - 10, y - 44)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(mx + 10, y - 54, "Assinatura")
    pdf.setFont("Helvetica", 9.5)
    crp_x = mx + sig_w + 20
    pdf.setFillColor(PDF_COLOR_LIGHT_BG)
    pdf.roundRect(crp_x, y - 56, 150, 56, 4, fill=1, stroke=1)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.drawString(crp_x + 10, y - 28, "CRP N\u00ba:")
    crp_value = _safe_pdf_text(current_user.crp_number or "")
    if crp_value:
        pdf.setFillColor(PDF_COLOR_TEXT)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(crp_x + 10, y - 40, crp_value)
        pdf.setFont("Helvetica", 9.5)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.setLineWidth(0.8)
    pdf.setStrokeColor(PDF_COLOR_PRIMARY)
    pdf.line(crp_x + 10, y - 42, crp_x + 138, y - 42)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(crp_x + 10, y - 52, "Conselho Regional de Psicologia")
    pdf.setFillColor(PDF_COLOR_TEXT)
    pdf.setStrokeColor(PDF_COLOR_TEXT)
    y -= 72

    _draw_pdf_footer(pdf, page_width, page_height, page_num[0], IEMA_FULL_NAME)
    pdf.save()
    return _pdf_inline_response(buffer, "relatorio_acompanhamentos.pdf")


@core_bp.get("/psicologo/consultas/<int:appointment_id>/imprimir")
@login_required
@roles_required("psicologo")
def psychologist_print_appointment(appointment_id):
    appointment = (
        Appointment.query.options(
            joinedload(Appointment.student),
            joinedload(Appointment.psychologist),
        )
        .filter_by(id=appointment_id)
        .first_or_404()
    )

    if appointment.psychologist_id != current_user.id:
        abort(403)

    generated_at = datetime.utcnow()
    doc_title = f"Acompanhamento Psicologico - Protocolo #{appointment.id}"
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(_safe_pdf_text(f"Relatorio de Atendimento - Protocolo #{appointment.id}"))
    pdf.setAuthor(_safe_pdf_text(appointment.psychologist.full_name))
    pdf.setSubject("Registro de Atendimento Psicologico - Agenda Escolar IEMA")
    page_width, page_height = A4
    mx = PDF_MARGIN_X
    mr = PDF_MARGIN_RIGHT
    content_width = page_width - mx - mr
    page_num = [1]

    def new_page():
        nonlocal y
        _draw_pdf_footer(pdf, page_width, page_height, page_num[0], IEMA_FULL_NAME)
        pdf.showPage()
        page_num[0] += 1
        y = _draw_pdf_header(pdf, page_width, page_height, doc_title, generated_at)

    def ensure_space(needed: float = 20):
        nonlocal y
        if y - needed < PDF_FOOTER_HEIGHT + 20:
            new_page()

    y = _draw_pdf_header(pdf, page_width, page_height, doc_title, generated_at)

    # --- Identificacao do documento ---
    y = _draw_info_box(pdf, mx, y, content_width, [
        ("Protocolo:", f"#{appointment.id}"),
        ("Documento gerado por:", f"{current_user.full_name} ({current_user.email})"),
        ("Data de geracao:", generated_at.strftime("%d/%m/%Y as %H:%M")),
    ])

    # --- Dados do atendimento ---
    ensure_space(80)
    y = _draw_section_title(pdf, mx, y, content_width, "Dados do Atendimento")

    # Card de status (canto direito)
    stat_color = STATUS_COLORS.get(appointment.status, PDF_COLOR_GRAY)
    stat_w = 120
    stat_h = 36
    pdf.setFillColor(stat_color)
    pdf.roundRect(mx + content_width - stat_w, y - stat_h, stat_w, stat_h, 5, fill=1, stroke=0)
    pdf.setFillColor(PDF_COLOR_WHITE)
    pdf.setFont("Helvetica-Bold", 11)
    stat_label = _safe_pdf_text(appointment.status.capitalize())
    sw = pdf.stringWidth(stat_label, "Helvetica-Bold", 11)
    pdf.drawString(mx + content_width - stat_w + (stat_w - sw) / 2, y - stat_h + 20, stat_label)
    pdf.setFont("Helvetica", 8)
    sl2 = "Status"
    sw2 = pdf.stringWidth(sl2, "Helvetica", 8)
    pdf.drawString(mx + content_width - stat_w + (stat_w - sw2) / 2, y - stat_h + 8, sl2)
    pdf.setFillColor(PDF_COLOR_TEXT)

    # Info do atendimento (esquerda)
    left_info_w = content_width - stat_w - 16
    info_rows = [
        ("Psicologo(a):", appointment.psychologist.full_name),
        ("Aluno(a):", appointment.student.full_name),
        ("Data:", appointment.start_time.strftime("%d/%m/%Y")),
        ("Horario:", appointment.start_time.strftime("%H:%M") + " - " + appointment.end_time.strftime("%H:%M")),
        ("Criado em:", appointment.created_at.strftime("%d/%m/%Y %H:%M")),
        ("Atualizado em:", appointment.updated_at.strftime("%d/%m/%Y %H:%M")),
    ]
    _draw_info_box(pdf, mx, y, left_info_w, info_rows)
    y -= max(len(info_rows) * 14 + 16 + 10, stat_h + 10)

    # --- Observacao do aluno ---
    ensure_space(60)
    y = _draw_section_title(pdf, mx, y, content_width, "Observacao Informada pelo Aluno")
    note_lines = _wrap_text(appointment.notes or "", max_chars=95)
    box_h = len(note_lines) * 14 + 16
    pdf.setFillColor(PDF_COLOR_LIGHT_BG)
    pdf.setStrokeColor(PDF_COLOR_LINE)
    pdf.setLineWidth(0.5)
    pdf.roundRect(mx - 4, y - box_h, content_width + 8, box_h, 4, fill=1, stroke=1)
    pdf.setFillColor(PDF_COLOR_TEXT)
    pdf.setFont("Helvetica", 10)
    ty = y - 13
    for line in note_lines:
        pdf.drawString(mx + 4, ty, _safe_pdf_text(line))
        ty -= 15
    y -= box_h + 12

    # --- Dados clínicos estruturados ---
    clinical_fields = [
        ("Queixa Principal", appointment.chief_complaint),
        ("Comportamentos Observados", appointment.observed_behaviors),
        ("Estado Emocional", appointment.emotional_state),
        ("Impressão Clínica", appointment.clinical_impression),
        ("Recomendações", appointment.recommendations),
        ("Próximas Ações", appointment.next_steps),
    ]
    
    for field_title, field_value in clinical_fields:
        if field_value:
            ensure_space(50)
            y = _draw_section_title(pdf, mx, y, content_width, field_title)
            field_lines = _wrap_text(field_value, max_chars=95)
            field_box_h = len(field_lines) * 14 + 16
            pdf.setFillColor(rl_colors.HexColor("#f5f8fc"))
            pdf.setStrokeColor(PDF_COLOR_LINE)
            pdf.setLineWidth(0.5)
            pdf.roundRect(mx - 4, y - field_box_h, content_width + 8, field_box_h, 4, fill=1, stroke=1)
            pdf.setFillColor(PDF_COLOR_TEXT)
            pdf.setFont("Helvetica", 10)
            fy = y - 13
            for line in field_lines:
                pdf.drawString(mx + 4, fy, _safe_pdf_text(line))
                fy -= 15
            y -= field_box_h + 12

    # --- Registro psicologico (compatibilidade com versoes anteriores) ---
    if appointment.psychologist_notes:
        ensure_space(80)
        y = _draw_section_title(pdf, mx, y, content_width, "Observacoes Adicionais")
        psych_lines = _wrap_text(appointment.psychologist_notes, max_chars=95)
        box2_h = max(len(psych_lines) * 14 + 16, 70)
        pdf.setFillColor(rl_colors.HexColor("#f0f4f9"))
        pdf.setStrokeColor(PDF_COLOR_ACCENT)
        pdf.setLineWidth(1)
        pdf.roundRect(mx - 4, y - box2_h, content_width + 8, box2_h, 4, fill=1, stroke=1)
        # Barra lateral colorida
        pdf.setFillColor(PDF_COLOR_ACCENT)
        pdf.rect(mx - 4, y - box2_h, 4, box2_h, fill=1, stroke=0)
        pdf.setFillColor(PDF_COLOR_TEXT)
        pdf.setFont("Helvetica", 10)
        ty2 = y - 15
        for line in psych_lines:
            pdf.drawString(mx + 8, ty2, _safe_pdf_text(line))
            ty2 -= 15
        y -= box2_h + 16

    # --- Assinatura ---
    ensure_space(90)
    y = _draw_section_title(pdf, mx, y, content_width, "Assinatura do Responsavel")
    y -= 18
    sig_w = min(250, content_width - 20)
    pdf.setFillColor(PDF_COLOR_LIGHT_BG)
    pdf.setStrokeColor(PDF_COLOR_LINE)
    pdf.setLineWidth(0.6)
    pdf.roundRect(mx, y - 64, sig_w, 64, 4, fill=1, stroke=1)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.setFont("Helvetica", 9.5)
    pdf.drawString(mx + 10, y - 14, _safe_pdf_text(f"Psicologo(a): {appointment.psychologist.full_name}"))
    pdf.drawString(mx + 10, y - 28, _safe_pdf_text(f"Data: {generated_at.strftime('%d/%m/%Y')}"))
    pdf.setLineWidth(0.8)
    pdf.setStrokeColor(PDF_COLOR_PRIMARY)
    pdf.line(mx + 10, y - 44, mx + sig_w - 10, y - 44)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(mx + 10, y - 56, "Assinatura do(a) Psicologo(a)")
    pdf.setFillColor(PDF_COLOR_TEXT)
    pdf.setStrokeColor(PDF_COLOR_TEXT)

    crp_x = mx + sig_w + 20
    pdf.setFillColor(PDF_COLOR_LIGHT_BG)
    pdf.setStrokeColor(PDF_COLOR_LINE)
    pdf.setLineWidth(0.6)
    pdf.roundRect(crp_x, y - 64, 150, 64, 4, fill=1, stroke=1)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.setFont("Helvetica", 9.5)
    pdf.drawString(crp_x + 10, y - 26, "CRP N\u00ba:")
    crp_val = _safe_pdf_text(appointment.psychologist.crp_number or "")
    if crp_val:
        pdf.setFillColor(PDF_COLOR_TEXT)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(crp_x + 10, y - 38, crp_val)
        pdf.setFont("Helvetica", 9.5)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.setStrokeColor(PDF_COLOR_PRIMARY)
    pdf.setLineWidth(0.8)
    pdf.line(crp_x + 10, y - 44, crp_x + 138, y - 44)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(crp_x + 10, y - 56, "Conselho Regional de Psicologia")
    pdf.setFillColor(PDF_COLOR_TEXT)
    pdf.setStrokeColor(PDF_COLOR_TEXT)

    _draw_pdf_footer(pdf, page_width, page_height, page_num[0], IEMA_FULL_NAME)
    pdf.save()
    return _pdf_inline_response(buffer, f"acompanhamento_{appointment.id}.pdf")


@core_bp.post("/consultas/<int:appointment_id>/registro")
@login_required
@roles_required("psicologo")
def appointment_record_save(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.psychologist_id != current_user.id:
        abort(403)

    if appointment.status in {"realizado", "cancelado"}:
        flash("Este atendimento ja foi finalizado e esta somente para visualizacao.", "info")
        return redirect(url_for("core.appointment_record_page", appointment_id=appointment.id))

    status = (request.form.get("status") or "").strip().lower()
    psychologist_notes = (request.form.get("psychologist_notes") or "").strip()
    chief_complaint = (request.form.get("chief_complaint") or "").strip()
    observed_behaviors = (request.form.get("observed_behaviors") or "").strip()
    emotional_state = (request.form.get("emotional_state") or "").strip()
    clinical_impression = (request.form.get("clinical_impression") or "").strip()
    recommendations = (request.form.get("recommendations") or "").strip()
    next_steps = (request.form.get("next_steps") or "").strip()

    valid_statuses = {"pendente", "confirmado", "realizado", "cancelado"}
    if status not in valid_statuses:
        flash("Status de atendimento invalido.", "warning")
        return redirect(url_for("core.appointment_record_page", appointment_id=appointment.id))

    appointment.status = status
    appointment.psychologist_notes = psychologist_notes or None
    appointment.chief_complaint = chief_complaint or None
    appointment.observed_behaviors = observed_behaviors or None
    appointment.emotional_state = emotional_state or None
    appointment.clinical_impression = clinical_impression or None
    appointment.recommendations = recommendations or None
    appointment.next_steps = next_steps or None

    db.session.commit()
    flash("Registro de atendimento salvo com sucesso.", "success")
    return redirect(url_for("core.appointment_record_page", appointment_id=appointment.id))


@core_bp.post("/consultas/<int:appointment_id>/encaminhamento/criar")
@login_required
@roles_required("psicologo")
def create_referral(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.psychologist_id != current_user.id:
        abort(403)

    referral_type = (request.form.get("referral_type") or "").strip().lower()
    professional_name = (request.form.get("professional_name") or "").strip()
    institution = (request.form.get("institution") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    priority = (request.form.get("priority") or "normal").strip().lower()
    observations = (request.form.get("observations") or "").strip()

    valid_types = {
        "psiquiatra", "neurologista", "fonoaudiologa", "pediatra",
        "oftalmologista", "otorrinolaringologista", "assistente_social",
        "terapeuta_ocupacional", "educacao_especial", "outro"
    }
    valid_priorities = {"urgente", "normal", "baixa"}

    if not referral_type or referral_type not in valid_types:
        flash("Tipo de encaminhamento invalido.", "warning")
        return redirect(url_for("core.appointment_record_page", appointment_id=appointment.id))

    if not reason:
        flash("Informe o motivo do encaminhamento.", "warning")
        return redirect(url_for("core.appointment_record_page", appointment_id=appointment.id))

    if priority not in valid_priorities:
        priority = "normal"

    referral = Referral(
        appointment_id=appointment.id,
        student_id=appointment.student_id,
        psychologist_id=current_user.id,
        referral_type=referral_type,
        professional_name=professional_name or None,
        institution=institution or None,
        reason=reason,
        priority=priority,
        observations=observations or None,
        status="pendente"
    )
    db.session.add(referral)
    db.session.commit()

    flash("Encaminhamento criado com sucesso.", "success")
    return redirect(url_for("core.appointment_record_page", appointment_id=appointment.id))


@core_bp.post("/encaminhamento/<int:referral_id>/status")
@login_required
@roles_required("psicologo")
def update_referral_status(referral_id):
    referral = Referral.query.get_or_404(referral_id)

    if referral.psychologist_id != current_user.id:
        abort(403)

    new_status = (request.form.get("status") or "").strip().lower()
    valid_statuses = {"pendente", "recusado", "realizado", "cancelado"}

    if new_status not in valid_statuses:
        flash("Status invalido.", "warning")
        return redirect(url_for("core.appointment_record_page", appointment_id=referral.appointment_id))

    referral.status = new_status
    db.session.commit()

    flash(f"Encaminhamento marcado como {new_status}.", "success")
    return redirect(url_for("core.appointment_record_page", appointment_id=referral.appointment_id))


@core_bp.get("/psicologo/encaminhamentos")
@login_required
@roles_required("psicologo")
def psychologist_referrals():
    """Exibe todos os encaminhamentos realizados pelo psicólogo."""
    status_filter = (request.args.get("status") or "").strip().lower()
    page, per_page = _read_pagination_params(default_per_page=12, max_per_page=50)

    query = Referral.query.filter_by(psychologist_id=current_user.id).options(
        joinedload(Referral.student),
        joinedload(Referral.appointment)
    )

    valid_statuses = {"pendente", "recusado", "realizado", "cancelado"}
    if status_filter in valid_statuses:
        query = query.filter(Referral.status == status_filter)
    else:
        status_filter = ""

    referrals_pagination = query.order_by(Referral.referral_date.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    referrals = referrals_pagination.items

    unfiltered_query = Referral.query.filter_by(psychologist_id=current_user.id)
    status_counts = {
        "total": unfiltered_query.count(),
        "pendente": unfiltered_query.filter_by(status="pendente").count(),
        "realizado": unfiltered_query.filter_by(status="realizado").count(),
        "recusado": unfiltered_query.filter_by(status="recusado").count(),
        "cancelado": unfiltered_query.filter_by(status="cancelado").count(),
    }

    return render_template(
        "psychologist/referrals.html",
        referrals=referrals,
        referrals_pagination=referrals_pagination,
        status_filter=status_filter,
        status_counts=status_counts,
    )


@core_bp.get("/encaminhamento/<int:referral_id>/assinar")
@login_required
@roles_required("psicologo")
def referral_sign_page(referral_id):
    """Exibe página para assinar um encaminhamento."""
    referral = Referral.query.options(
        joinedload(Referral.student),
        joinedload(Referral.appointment)
    ).get_or_404(referral_id)

    if referral.psychologist_id != current_user.id:
        abort(403)

    signature_b64 = ""
    if referral.is_signed and referral.signature:
        signature_b64 = base64.b64encode(referral.signature).decode("utf-8")

    return render_template(
        "psychologist/referral_sign.html",
        referral=referral,
        signature_b64=signature_b64,
        REFERRAL_TYPES=REFERRAL_TYPES
    )


@core_bp.post("/encaminhamento/<int:referral_id>/assinar")
@login_required
@roles_required("psicologo")
def save_referral_signature(referral_id):
    """Salva assinatura do encaminhamento."""
    import json
    
    referral = Referral.query.get_or_404(referral_id)

    if referral.psychologist_id != current_user.id:
        return {"success": False, "message": "Nao autorizado"}, 403

    try:
        data = request.get_json()
        signature_data = data.get("signature", "")

        # Remove data URI prefix se presente
        if signature_data.startswith("data:image/png;base64,"):
            signature_data = signature_data[len("data:image/png;base64,"):]

        # Decode base64 para validar
        signature_bytes = base64.b64decode(signature_data)
        
        referral.signature = signature_bytes
        referral.signature_date = datetime.utcnow()
        referral.is_signed = True
        db.session.commit()

        return {"success": True, "message": "Assinatura salva com sucesso"}
    except Exception as e:
        return {"success": False, "message": f"Erro ao salvar assinatura: {str(e)}"}, 400


@core_bp.get("/encaminhamento/<int:referral_id>/imprimir")
@login_required
@roles_required("psicologo")
def print_referral(referral_id):
    """Gera PDF do encaminhamento para impressão."""
    referral = Referral.query.options(
        joinedload(Referral.student),
        joinedload(Referral.appointment),
        joinedload(Referral.psychologist)
    ).get_or_404(referral_id)

    if referral.psychologist_id != current_user.id:
        abort(403)

    generated_at = datetime.utcnow()
    doc_title = f"Encaminhamento Clinico - Protocolo #{referral.id}"
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(_safe_pdf_text(f"Encaminhamento - Protocolo #{referral.id}"))
    pdf.setAuthor(_safe_pdf_text(referral.psychologist.full_name))
    pdf.setSubject("Encaminhamento Clinico - Agenda Escolar IEMA")
    
    page_width, page_height = A4
    mx = PDF_MARGIN_X
    mr = PDF_MARGIN_RIGHT
    content_width = page_width - mx - mr
    
    y = _draw_pdf_header(pdf, page_width, page_height, doc_title, generated_at)

    # --- Identificacao ---
    y = _draw_info_box(pdf, mx, y, content_width, [
        ("Protocolo:", f"#{referral.id}"),
        ("Profissional responsavel:", referral.psychologist.full_name),
        ("Data de geracao:", generated_at.strftime("%d/%m/%Y as %H:%M")),
    ])

    # --- Dados do Encaminhamento ---
    y -= 20
    pdf.setFont("Helvetica-Bold", 12)
    pdf.setFillColor(PDF_COLOR_PRIMARY)
    pdf.drawString(mx, y, "DADOS DO ENCAMINHAMENTO")
    y -= 20

    # Card de tipo e prioridade (canto direito)
    priority_color = {
        "urgente": PDF_COLOR_RED,
        "normal": PDF_COLOR_ORANGE,
        "baixa": PDF_COLOR_GREEN,
    }.get(referral.priority, PDF_COLOR_GRAY)

    type_w = 140
    type_h = 36
    pdf.setFillColor(PDF_COLOR_SECONDARY)
    pdf.roundRect(mx, y - type_h, type_w, type_h, 5, fill=1, stroke=0)
    pdf.setFillColor(PDF_COLOR_WHITE)
    pdf.setFont("Helvetica-Bold", 10)
    type_str = _safe_pdf_text(REFERRAL_TYPES.get(referral.referral_type, referral.referral_type))
    pdf.drawCentredString(mx + type_w/2, y - type_h + 18, type_str)
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(mx + type_w/2, y - type_h + 6, "Tipo")

    # Prioridade
    pri_w = 100
    pri_x = mx + type_w + 10
    pdf.setFillColor(priority_color)
    pdf.roundRect(pri_x, y - type_h, pri_w, type_h, 5, fill=1, stroke=0)
    pdf.setFillColor(PDF_COLOR_WHITE)
    pdf.setFont("Helvetica-Bold", 10)
    pri_str = _safe_pdf_text(referral.priority.upper())
    pdf.drawCentredString(pri_x + pri_w/2, y - type_h + 18, pri_str)
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(pri_x + pri_w/2, y - type_h + 6, "Prioridade")

    y -= type_h + 20

    # Informações principais em tabela
    info_lines = [
        ("Aluno:", referral.student.full_name),
        ("Profissional destino:", referral.professional_name or "(Nao especificado)"),
        ("Instituicao:", referral.institution or "(Nao especificada)"),
        ("Motivo:", referral.reason[:80] + ("..." if len(referral.reason) > 80 else "")),
        ("Data do encaminhamento:", referral.referral_date.strftime("%d/%m/%Y")),
        ("Status:", referral.status.upper()),
    ]

    y = _draw_info_box(pdf, mx, y, content_width, info_lines)

    # --- Detalhes Completos ---
    y -= 16
    pdf.setFont("Helvetica-Bold", 12)
    pdf.setFillColor(PDF_COLOR_PRIMARY)
    pdf.drawString(mx, y, "DETALHES DO ENCAMINHAMENTO")
    y -= 16

    # Motivo completo
    pdf.setFont("Helvetica-Bold", 9)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.drawString(mx, y, "Motivo do encaminhamento:")
    y -= 12
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(PDF_COLOR_TEXT)
    
    # Quebra de linhas para motivo
    motivo_lines = _wrap_text(referral.reason, 90)
    for line in motivo_lines[:5]:  # Máximo 5 linhas
        pdf.drawString(mx + 10, y, _safe_pdf_text(line))
        y -= 12

    # Observações se existirem
    if referral.observations:
        y -= 8
        pdf.setFont("Helvetica-Bold", 9)
        pdf.setFillColor(PDF_COLOR_GRAY)
        pdf.drawString(mx, y, "Observacoes adicionais:")
        y -= 12
        pdf.setFont("Helvetica", 9)
        pdf.setFillColor(PDF_COLOR_TEXT)
        obs_lines = _wrap_text(referral.observations, 90)
        for line in obs_lines[:4]:  # Máximo 4 linhas
            pdf.drawString(mx + 10, y, _safe_pdf_text(line))
            y -= 12

    # --- Assinatura ---
    y -= 16
    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(PDF_COLOR_PRIMARY)
    pdf.drawString(mx, y, "ASSINATURA DO PROFISSIONAL")
    y -= 40

    if referral.is_signed and referral.signature:
        # Desenha assinatura
        try:
            from PIL import Image
            sig_img = Image.open(BytesIO(referral.signature))
            sig_buffer = BytesIO()
            sig_img.save(sig_buffer, format='PNG')
            sig_buffer.seek(0)
            
            sig_reader = ImageReader(sig_buffer)
            sig_width = 150
            sig_height = 60
            pdf.drawImage(sig_reader, mx + 20, y - sig_height, width=sig_width, height=sig_height)
        except Exception:
            pdf.setFont("Helvetica", 9)
            pdf.setFillColor(PDF_COLOR_GRAY)
            pdf.drawString(mx + 20, y - 20, "[Assinatura disponivel no sistema]")
    else:
        pdf.setFont("Helvetica", 9)
        pdf.setFillColor(PDF_COLOR_GRAY)
        pdf.drawString(mx + 20, y - 20, "[ Assinatura do(a) Psicologo(a) ]")

    y -= 80

    # Linha de assinatura
    pdf.setLineWidth(0.5)
    pdf.setStrokeColor(PDF_COLOR_GRAY)
    pdf.line(mx + 20, y, mx + 170, y)

    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(PDF_COLOR_GRAY)
    pdf.drawString(mx + 20, y - 14, _safe_pdf_text(referral.psychologist.full_name))
    pdf.drawString(mx + 20, y - 22, "Psicologo(a) Responsavel")

    if referral.is_signed and referral.signature_date:
        y -= 40
        pdf.setFont("Helvetica", 8)
        pdf.setFillColor(PDF_COLOR_GREEN)
        pdf.drawString(mx, y, f"Documento assinado em: {referral.signature_date.strftime('%d/%m/%Y as %H:%M')}")

    _draw_pdf_footer(pdf, page_width, page_height, 1, IEMA_FULL_NAME)
    pdf.showPage()
    pdf.save()

    return _pdf_inline_response(buffer, f"encaminhamento-protocolo-{referral.id}.pdf")


# ---------------------------------------------------------------------------
# Admin: trabalhos da semana
# ---------------------------------------------------------------------------

@core_bp.get("/admin/trabalhos")
@login_required
@roles_required("admin")
def admin_assignments():
    """Exibe o calendário semanal de trabalhos (seg–sex) pelo due_date."""
    from collections import defaultdict

    today = datetime.utcnow().date()
    week_offset = request.args.get("week", 0, type=int)
    base_monday = today - timedelta(days=today.weekday())
    week_start = base_monday + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(5)]  # seg–sex
    week_end = week_days[-1]

    classroom_id = request.args.get("classroom_id", "", type=str).strip()
    teacher_id   = request.args.get("teacher_id",   "", type=str).strip()

    query = Assignment.query.filter(
        Assignment.due_date >= week_start,
        Assignment.due_date <= week_end,
        Assignment.is_finished.is_(False),
    )

    if classroom_id:
        query = query.filter(Assignment.classroom_id == int(classroom_id))
    if teacher_id:
        query = query.filter(Assignment.teacher_id == int(teacher_id))

    assignments = query.options(joinedload(Assignment.submissions)).order_by(Assignment.due_date.asc(), Assignment.created_at.asc()).all()

    assignments_by_day = defaultdict(list)
    for a in assignments:
        if any(sub.status == "aprovado" for sub in a.submissions):
            continue
        assignments_by_day[a.due_date].append(a)

    classrooms = Classroom.query.order_by(Classroom.name.asc()).all()
    professors = User.query.filter_by(role="professor").order_by(User.full_name.asc()).all()

    return render_template(
        "admin/assignments.html",
        assignments=assignments,
        week_days=week_days,
        assignments_by_day=assignments_by_day,
        week_start=week_start,
        week_end=week_end,
        today=today,
        classrooms=classrooms,
        professors=professors,
        sel_classroom=classroom_id,
        sel_teacher=teacher_id,
        week_offset=week_offset,
    )


# ---------------------------------------------------------------------------
# Professor: calendário semanal de trabalhos
# ---------------------------------------------------------------------------

@core_bp.get("/professor/trabalhos")
@login_required
@roles_required("professor")
def professor_assignments():
    """Calendário semanal de trabalhos das turmas do professor logado."""
    from collections import defaultdict

    today = datetime.utcnow().date()
    week_offset = request.args.get("week", 0, type=int)
    base_monday = today - timedelta(days=today.weekday())
    week_start = base_monday + timedelta(weeks=week_offset)
    week_days = [week_start + timedelta(days=i) for i in range(5)]  # seg–sex
    week_end = week_days[-1]

    classroom_id = request.args.get("classroom_id", "", type=str).strip()

    # Turmas vinculadas ao professor (leciona)
    teacher_classrooms = current_user.teaching_classrooms
    teacher_classroom_ids = [c.id for c in teacher_classrooms]

    query = Assignment.query.filter(
        Assignment.teacher_id == current_user.id,
        Assignment.due_date >= week_start,
        Assignment.due_date <= week_end,
        Assignment.is_finished.is_(False),
    )

    if classroom_id and classroom_id.isdigit():
        query = query.filter(Assignment.classroom_id == int(classroom_id))

    assignments = query.order_by(Assignment.due_date.asc(), Assignment.created_at.asc()).all()

    assignments_by_day = defaultdict(list)
    for a in assignments:
        assignments_by_day[a.due_date].append(a)

    return render_template(
        "professor/assignments.html",
        assignments=assignments,
        week_days=week_days,
        assignments_by_day=assignments_by_day,
        week_start=week_start,
        week_end=week_end,
        today=today,
        classrooms=teacher_classrooms,
        sel_classroom=classroom_id,
        week_offset=week_offset,
    )


@core_bp.get("/professor/trabalhos/finalizados")
@login_required
@roles_required("professor")
def professor_finished_assignments():
    """Página de trabalhos do professor com abas de andamento e finalizados."""
    classroom_id = request.args.get("classroom_id", "", type=str).strip()
    selected_tab = request.args.get("tab", "andamento", type=str).strip().lower()
    if selected_tab not in {"andamento", "finalizados"}:
        selected_tab = "andamento"
    page_ongoing = request.args.get("page_ongoing", 1, type=int)
    page_finished = request.args.get("page_finished", 1, type=int)
    per_page_ongoing = request.args.get("per_page_ongoing", 12, type=int)
    per_page_finished = request.args.get("per_page_finished", 12, type=int)
    if page_ongoing < 1:
        page_ongoing = 1
    if page_finished < 1:
        page_finished = 1
    if per_page_ongoing < 1:
        per_page_ongoing = 12
    if per_page_finished < 1:
        per_page_finished = 12
    if per_page_ongoing > 50:
        per_page_ongoing = 50
    if per_page_finished > 50:
        per_page_finished = 50
    teacher_classrooms = current_user.teaching_classrooms

    ongoing_query = Assignment.query.filter(
        Assignment.teacher_id == current_user.id,
        Assignment.is_finished.is_(False),
    )
    finished_query = Assignment.query.filter(
        Assignment.teacher_id == current_user.id,
        Assignment.is_finished.is_(True),
    )

    if classroom_id and classroom_id.isdigit():
        classroom_id_int = int(classroom_id)
        ongoing_query = ongoing_query.filter(Assignment.classroom_id == classroom_id_int)
        finished_query = finished_query.filter(Assignment.classroom_id == classroom_id_int)

    ongoing_pagination = (
        ongoing_query
        .order_by(Assignment.due_date.asc(), Assignment.created_at.desc())
        .paginate(page=page_ongoing, per_page=per_page_ongoing, error_out=False)
    )
    ongoing_assignments = ongoing_pagination.items

    finished_pagination = (
        finished_query
        .order_by(Assignment.updated_at.desc(), Assignment.due_date.desc())
        .paginate(page=page_finished, per_page=per_page_finished, error_out=False)
    )
    finished_assignments = finished_pagination.items

    return render_template(
        "professor/finished_assignments.html",
        ongoing_assignments=ongoing_assignments,
        finished_assignments=finished_assignments,
        classrooms=teacher_classrooms,
        sel_classroom=classroom_id,
        selected_tab=selected_tab,
        ongoing_pagination=ongoing_pagination,
        finished_pagination=finished_pagination,
    )


# ---------------------------------------------------------------------------
# ALUNO - TRABALHOS
# ---------------------------------------------------------------------------

@core_bp.get("/trabalho/<int:assignment_id>")
@login_required
@roles_required("aluno")
def student_view_assignment(assignment_id):
    """Página de visualização e submissão de trabalho para aluno."""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Verifica se o aluno faz parte dessa turma
    if current_user.classroom_id != assignment.classroom_id:
        abort(403)
    
    # Verifica prazo
    overdue = assignment.due_date < datetime.utcnow().date()

    # Verifica se já existe uma submissão
    submission = Submission.query.filter_by(
        assignment_id=assignment_id,
        student_id=current_user.id
    ).first()
    # Também verifica se o aluno é membro de uma submissão em grupo
    if not submission:
        submission = (
            Submission.query
            .join(SubmissionGroupMember, SubmissionGroupMember.submission_id == Submission.id)
            .filter(
                Submission.assignment_id == assignment_id,
                SubmissionGroupMember.student_id == current_user.id,
            )
            .first()
        )

    # Registra quando o aluno visualiza uma devolução pela primeira vez apos a ultima avaliacao.
    if submission and submission.status == "devolvido":
        last_history_event = (
            SubmissionHistoryEvent.query
            .filter_by(submission_id=submission.id)
            .order_by(SubmissionHistoryEvent.created_at.desc(), SubmissionHistoryEvent.id.desc())
            .first()
        )
        if not last_history_event or last_history_event.action != "visualizado":
            db.session.add(SubmissionHistoryEvent(
                submission_id=submission.id,
                actor_id=current_user.id,
                action="visualizado",
                from_status="devolvido",
                to_status="devolvido",
                note="Aluno visualizou a devolucao para correcao.",
            ))
            db.session.commit()

    can_resubmit = bool(
        submission
        and submission.status == "devolvido"
        and submission.student_id == current_user.id
    )
    
    classmates = User.query.filter(
        User.classroom_id == current_user.classroom_id,
        User.id != current_user.id,
        User.role == "aluno"
    ).order_by(User.full_name).all()
    
    # Adiciona o próprio usuário no início da lista
    all_classmates = [current_user] + classmates
    
    return render_template(
        "student/assignment.html",
        assignment=assignment,
        submission=submission,
        classmates=all_classmates,
        overdue=overdue,
        can_resubmit=can_resubmit,
    )


@core_bp.post("/trabalho/<int:assignment_id>/submit")
@login_required
@roles_required("aluno")
def student_submit_assignment(assignment_id):
    """Submete um trabalho (individual ou em grupo)."""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Verifica se o aluno faz parte dessa turma
    if current_user.classroom_id != assignment.classroom_id:
        abort(403)
    
    # Verifica prazo
    if assignment.due_date < datetime.utcnow().date():
        flash("O prazo de entrega deste trabalho já encerrou.", "danger")
        return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))

    # Verifica se já existe submissão
    existing = Submission.query.filter_by(
        assignment_id=assignment_id,
        student_id=current_user.id
    ).first()
    if not existing:
        existing = (
            Submission.query
            .join(SubmissionGroupMember, SubmissionGroupMember.submission_id == Submission.id)
            .filter(
                Submission.assignment_id == assignment_id,
                SubmissionGroupMember.student_id == current_user.id,
            )
            .first()
        )
    is_resubmission = False
    previous_status = None
    if existing:
        previous_status = existing.status
        if existing.status != "devolvido":
            flash("Você já submeteu este trabalho.", "warning")
            return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))

        # Em trabalho em grupo, apenas o líder pode reenviar
        if existing.is_group and existing.student_id != current_user.id:
            flash("Este trabalho em grupo foi devolvido, mas somente o líder pode reenviar.", "warning")
            return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))

        submission = existing
        is_resubmission = True
        is_group = submission.is_group
        group_member_ids = []
    else:
        is_group = request.form.get("is_group") == "true"
        group_member_ids = request.form.getlist("group_members") if is_group else []

    # Valida seleção de membros apenas na primeira submissão em grupo.
    # Em reenvio, o grupo original é preservado.
    parsed_group_member_ids = []
    if is_group and not is_resubmission:
        # Remove o próprio usuário da lista se for incluído acidentalmente,
        # elimina duplicados e valida formato numérico.
        unique_member_ids = set()
        for member_id_str in group_member_ids:
            try:
                member_id = int(member_id_str)
            except (TypeError, ValueError):
                flash("Erro ao processar integrantes.", "danger")
                return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))

            if member_id == current_user.id or member_id in unique_member_ids:
                continue
            unique_member_ids.add(member_id)
            parsed_group_member_ids.append(member_id)

        if not parsed_group_member_ids:
            flash("Selecione pelo menos um integrante para trabalho em grupo.", "warning")
            return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))

        # Valida se todos são da mesma turma
        for member_id in parsed_group_member_ids:
            member = User.query.get(member_id)
            if not member or member.classroom_id != current_user.classroom_id or member.role != "aluno":
                flash("Integrante inválido.", "danger")
                return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))

            # Bloqueia integrante que já entregou este trabalho (individualmente ou em outro grupo)
            member_existing_submission = Submission.query.filter_by(
                assignment_id=assignment_id,
                student_id=member_id,
            ).first()
            if not member_existing_submission:
                member_existing_submission = (
                    Submission.query
                    .join(SubmissionGroupMember, SubmissionGroupMember.submission_id == Submission.id)
                    .filter(
                        Submission.assignment_id == assignment_id,
                        SubmissionGroupMember.student_id == member_id,
                    )
                    .first()
                )
            if member_existing_submission:
                flash(f"{member.full_name} já entregou este trabalho e não pode entrar em outro grupo.", "warning")
                return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))
    
    # Cria submissão apenas na primeira entrega
    if not is_resubmission:
        submission = Submission(
            assignment_id=assignment_id,
            student_id=current_user.id,
            is_group=is_group,
            submitted_at=datetime.utcnow()
        )
    else:
        submission.submitted_at = datetime.utcnow()
        submission.status = "pendente"
        submission.grade = None
        submission.feedback = None
    
    # Processa arquivo de submissão se existir
    if "submission_file" in request.files:
        file = request.files["submission_file"]
        if file and file.filename:
            if not allowed_submission_file(file.filename):
                flash("Apenas arquivos PDF são permitidos.", "danger")
                return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))
            
            # Verifica tamanho
            file.seek(0, os.SEEK_END)
            file_length = file.tell()
            file.seek(0)
            
            if file_length > MAX_SUBMISSION_SIZE:
                flash("Arquivo muito grande (máximo 10 MB).", "danger")
                return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))
            
            # Salva arquivo
            file_path = save_submission_file(file, assignment_id, current_user.id)
            if file_path:
                submission.file_path = file_path
            else:
                flash("Erro ao salvar arquivo.", "danger")
                return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))
    
    db.session.add(submission)
    db.session.flush()  # Para obter o ID

    db.session.add(SubmissionHistoryEvent(
        submission_id=submission.id,
        actor_id=current_user.id,
        action="reenviado" if is_resubmission else "enviado",
        from_status=previous_status,
        to_status="pendente",
        note=None,
    ))
    
    # Adiciona membros do grupo
    if is_group and not is_resubmission:
        for member_id in parsed_group_member_ids:
            member = SubmissionGroupMember(
                submission_id=submission.id,
                student_id=member_id
            )
            db.session.add(member)

    # Notifica o professor do trabalho
    tipo = "em grupo" if is_group else "individual"
    acao = "reenviou" if is_resubmission else "entregou"
    db.session.add(Notification(
        user_id=assignment.teacher_id,
        title="Nova entrega recebida",
        message=f"{current_user.full_name} {acao} o trabalho \"{assignment.title}\" ({tipo}).",
        link=f"/trabalho/{assignment.id}/submissoes",
    ))

    db.session.commit()
    
    status = "em grupo" if is_group else "individual"
    if is_resubmission:
        flash(f"Trabalho reenviado com sucesso ({status}).", "success")
    else:
        flash(f"Trabalho submetido com sucesso ({status}).", "success")
    return redirect(url_for("core.student_view_assignment", assignment_id=assignment_id))


# ---------------------------------------------------------------------------
# PROFESSOR - VER SUBMISSÕES
# ---------------------------------------------------------------------------

@core_bp.get("/trabalho/<int:assignment_id>/submissoes")
@login_required
@roles_required("professor")
def teacher_view_submissions(assignment_id):
    """Visualiza todas as submissões de um trabalho."""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Verifica se o professor é dono do trabalho
    if assignment.teacher_id != current_user.id:
        abort(403)
    
    submissions = (
        Submission.query
        .options(
            joinedload(Submission.group_members).joinedload(SubmissionGroupMember.student),
            joinedload(Submission.student),
            joinedload(Submission.history_events).joinedload(SubmissionHistoryEvent.actor),
        )
        .filter_by(assignment_id=assignment_id)
        .all()
    )
    
    # Alunos da turma que ainda não submeteram.
    # Em trabalho em grupo, contam como entregues: líder + todos os membros.
    submitted_student_ids = set()
    for submission in submissions:
        submitted_student_ids.add(submission.student_id)
        for member in submission.group_members:
            submitted_student_ids.add(member.student_id)

    base_query = User.query.filter(
        User.classroom_id == assignment.classroom_id,
        User.role == "aluno",
    )
    if submitted_student_ids:
        not_submitted = base_query.filter(~User.id.in_(submitted_student_ids)).order_by(User.full_name).all()
    else:
        not_submitted = base_query.order_by(User.full_name).all()
    
    return render_template(
        "teacher/submissions.html",
        assignment=assignment,
        submissions=submissions,
        not_submitted=not_submitted,
    )


@core_bp.post("/trabalho/<int:assignment_id>/finalizar")
@login_required
@roles_required("professor")
def teacher_finish_assignment(assignment_id):
    """Finaliza um trabalho para removê-lo das listas ativas."""
    assignment = Assignment.query.get_or_404(assignment_id)

    if assignment.teacher_id != current_user.id:
        abort(403)

    if assignment.is_finished:
        flash("Este trabalho já está finalizado.", "info")
        return redirect(url_for("core.teacher_view_submissions", assignment_id=assignment_id))

    assignment.is_finished = True

    # Registra no histórico de todas as submissões desse trabalho.
    for submission in assignment.submissions:
        db.session.add(SubmissionHistoryEvent(
            submission_id=submission.id,
            actor_id=current_user.id,
            action="finalizado",
            from_status=submission.status,
            to_status=submission.status,
            note="Trabalho finalizado manualmente pelo professor.",
        ))

    db.session.commit()
    flash("Trabalho finalizado com sucesso.", "success")
    return redirect(url_for("core.professor_assignments"))


@core_bp.post("/assignments/<int:assignment_id>/reopen")
@login_required
@roles_required("professor")
def reopen_assignment(assignment_id):
    """Reabre um trabalho finalizado, atualizando o prazo de entrega."""
    assignment = Assignment.query.get_or_404(assignment_id)

    if assignment.teacher_id != current_user.id:
        abort(403)

    due_date_raw = request.form.get("due_date", "").strip()
    next_url = request.form.get("next", "").strip()

    if not due_date_raw:
        flash("Informe a nova data de entrega para reabrir o trabalho.", "warning")
        return redirect(url_for("core.dashboard"))

    try:
        due_date = datetime.strptime(due_date_raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Data invalida para reabertura do trabalho.", "danger")
        return redirect(url_for("core.dashboard"))

    assignment.due_date = due_date
    assignment.is_finished = False
    db.session.commit()

    flash("Trabalho reaberto com a nova data de entrega.", "success")

    if next_url.startswith("/"):
        return redirect(next_url)

    return redirect(url_for("core.professor_assignments"))


@core_bp.post("/assignments/<int:assignment_id>/delete")
@login_required
@roles_required("professor")
def delete_assignment(assignment_id):
    """Exclui um trabalho e todas as suas submissões."""
    assignment = Assignment.query.get_or_404(assignment_id)

    if assignment.teacher_id != current_user.id:
        abort(403)

    if assignment.is_finished:
        flash("Não é possível excluir um trabalho finalizado.", "warning")
        return redirect(url_for("core.professor_finished_assignments"))

    next_url = request.form.get("next", "").strip()

    db.session.delete(assignment)
    db.session.commit()

    flash("Trabalho excluído com sucesso.", "success")

    if next_url.startswith("/"):
        return redirect(next_url)

    return redirect(url_for("core.professor_finished_assignments"))


@core_bp.get("/trabalho/<int:assignment_id>/detalhe")
@login_required
@roles_required("professor")
def teacher_view_assignment(assignment_id):
    """Visualiza um trabalho específico (professor)."""
    assignment = Assignment.query.get_or_404(assignment_id)
    
    # Verifica se o professor é dono do trabalho
    if assignment.teacher_id != current_user.id:
        abort(403)
    
    # Conta submissões
    submissions_count = Submission.query.filter_by(assignment_id=assignment_id).count()
    students_count = User.query.filter_by(classroom_id=assignment.classroom_id, role="aluno").count()
    
    return render_template(
        "teacher/assignment.html",
        assignment=assignment,
        submissions_count=submissions_count,
        students_count=students_count,
    )


# ---------------------------------------------------------------------------
# PROFESSOR - AVALIAR SUBMISSÃO
# ---------------------------------------------------------------------------

@core_bp.post("/trabalho/<int:assignment_id>/submissoes/<int:submission_id>/avaliar")
@login_required
@roles_required("professor")
def teacher_evaluate_submission(assignment_id, submission_id):
    """Aprova ou devolve uma submissão com feedback."""
    submission = Submission.query.get_or_404(submission_id)
    assignment = Assignment.query.get_or_404(assignment_id)

    if assignment.teacher_id != current_user.id or submission.assignment_id != assignment_id:
        abort(403)

    action = request.form.get("action")  # "aprovar" ou "devolver"
    feedback = request.form.get("feedback", "").strip()
    grade = request.form.get("grade", "").strip()
    previous_status = submission.status

    if action == "aprovar":
        submission.status = "aprovado"
        submission.feedback = feedback or None
        submission.grade = grade or None
        db.session.add(SubmissionHistoryEvent(
            submission_id=submission.id,
            actor_id=current_user.id,
            action="aprovado",
            from_status=previous_status,
            to_status="aprovado",
            grade=grade or None,
            note=feedback or None,
        ))
        # Notificação positiva ao aluno
        title = f"Trabalho aprovado: {assignment.title}"
        message = f"O professor avaliou e aprovou o seu trabalho \"{assignment.title}\"."
        if grade:
            message += f" Nota: {grade}."
        if feedback:
            message += f" Comentário: {feedback}"
        db.session.add(Notification(
            user_id=submission.student_id,
            title=title,
            message=message,
            link=f"/aluno/trabalhos",
        ))
    elif action == "devolver":
        submission.status = "devolvido"
        submission.feedback = feedback or None
        submission.grade = grade or None
        db.session.add(SubmissionHistoryEvent(
            submission_id=submission.id,
            actor_id=current_user.id,
            action="devolvido",
            from_status=previous_status,
            to_status="devolvido",
            grade=grade or None,
            note=feedback or None,
        ))
        # Notificação ao aluno com motivo
        title = f"Trabalho devolvido: {assignment.title}"
        message = f"O professor devolveu o seu trabalho \"{assignment.title}\" para revisão."
        if feedback:
            message += f" Motivo: {feedback}"
        db.session.add(Notification(
            user_id=submission.student_id,
            title=title,
            message=message,
            link=f"/aluno/trabalhos",
        ))
    else:
        flash("Ação inválida.", "danger")
        return redirect(url_for("core.teacher_view_submissions", assignment_id=assignment_id))

    db.session.commit()
    flash("Avaliação registrada com sucesso.", "success")
    return redirect(url_for("core.teacher_view_submissions", assignment_id=assignment_id))


# ---------------------------------------------------------------------------
# ALUNO - MARCAR NOTIFICAÇÕES COMO LIDAS
# ---------------------------------------------------------------------------

@core_bp.post("/notificacoes/marcar-lidas")
@login_required
def mark_notifications_read():
    """Marca todas as notificações do usuário como lidas."""
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(url_for("core.dashboard"))


# ---------------------------------------------------------------------------
# Chat ao Vivo
# ---------------------------------------------------------------------------

@core_bp.get("/chat")
@login_required
def chat_page():
    """Página dedicada ao chat ao vivo."""
    return render_template("chat.html")


# ---------------------------------------------------------------------------
# Perfil do usuario autenticado
# ---------------------------------------------------------------------------

@core_bp.get("/perfil")
@login_required
def edit_profile():
    """Exibe formulario de edicao do perfil do usuario autenticado."""
    classrooms = Classroom.query.order_by(Classroom.name.asc()).all()
    return render_template(
        "profile.html",
        user=current_user,
        classrooms=classrooms,
    )


@core_bp.post("/perfil")
@login_required
def update_profile():
    """Salva alteracoes no perfil do usuario autenticado."""
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    new_password = request.form.get("new_password", "").strip()

    if not full_name:
        flash("Nome completo nao pode estar vazio.", "danger")
        return redirect(url_for("core.edit_profile"))

    if not email:
        flash("E-mail nao pode estar vazio.", "danger")
        return redirect(url_for("core.edit_profile"))

    # Verificar se o novo e-mail ja existe (e nao eh do usuario atual)
    existing = User.query.filter_by(email=email).first()
    if existing and existing.id != current_user.id:
        flash("Este e-mail ja esta registrado.", "danger")
        return redirect(url_for("core.edit_profile"))

    # Atualizar dados
    current_user.full_name = full_name
    current_user.email = email

    # Se forneceu nova senha, atualizar
    if new_password:
        if len(new_password) < 6:
            flash("A nova senha deve ter no minimo 6 caracteres.", "danger")
            return redirect(url_for("core.edit_profile"))
        current_user.set_password(new_password)

    try:
        db.session.commit()
        flash("Perfil atualizado com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao atualizar perfil: {str(e)}", "danger")

    return redirect(url_for("core.edit_profile"))


@core_bp.post("/perfil/avatar")
@login_required
def upload_avatar():
    """Faz upload da foto de perfil do usuário."""
    if "avatar" not in request.files:
        flash("Nenhum arquivo selecionado.", "danger")
        return redirect(url_for("core.edit_profile"))

    file = request.files["avatar"]
    if file.filename == "":
        flash("Nenhum arquivo selecionado.", "danger")
        return redirect(url_for("core.edit_profile"))

    if not allowed_avatar(file.filename):
        flash("Formato invalido. Use JPG, PNG, GIF ou WebP.", "danger")
        return redirect(url_for("core.edit_profile"))

    # Verificar tamanho (lê no máximo MAX+1 bytes para detectar excesso sem carregar tudo)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_AVATAR_SIZE:
        flash("Imagem muito grande. Limite: 2 MB.", "danger")
        return redirect(url_for("core.edit_profile"))

    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{current_user.id}_{uuid.uuid4().hex}.{ext}"
    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "avatars")
    os.makedirs(upload_dir, exist_ok=True)

    # Remover avatar anterior se existir
    if current_user.avatar:
        old_path = os.path.join(upload_dir, current_user.avatar)
        if os.path.exists(old_path):
            os.remove(old_path)

    file.save(os.path.join(upload_dir, filename))
    current_user.avatar = filename

    try:
        db.session.commit()
        flash("Foto atualizada com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao salvar foto: {str(e)}", "danger")

    return redirect(url_for("core.edit_profile"))


@core_bp.post("/perfil/avatar/remover")
@login_required
def remove_avatar():
    """Remove a foto de perfil do usuário."""
    if current_user.avatar:
        upload_dir = os.path.join(current_app.root_path, "static", "uploads", "avatars")
        old_path = os.path.join(upload_dir, current_user.avatar)
        if os.path.exists(old_path):
            os.remove(old_path)
        current_user.avatar = None
        try:
            db.session.commit()
            flash("Foto removida.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Erro ao remover foto: {str(e)}", "danger")

    return redirect(url_for("core.edit_profile"))
