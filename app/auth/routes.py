from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

from ..extensions import db, limiter, mail
from ..models import User

auth_bp = Blueprint("auth", __name__, template_folder="../templates")


@auth_bp.get("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("core.dashboard"))
    return render_template("auth/login.html")


@auth_bp.post("/login")
@limiter.limit("10/minute")
def login_post():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash("Credenciais invalidas.", "danger")
        return redirect(url_for("auth.login"))

    if not user.is_active_user:
        flash("Usuario inativo.", "warning")
        return redirect(url_for("auth.login"))

    if not user.is_approved:
        flash("Sua conta está pendente de aprovação do administrador. Você será notificado em breve.", "warning")
        return redirect(url_for("auth.login"))

    login_user(user)
    return redirect(url_for("core.dashboard"))


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.get("/register")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("core.dashboard"))
    return render_template("auth/register.html")


@auth_bp.post("/register")
@limiter.limit("5/minute")
def register_post():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    # Validações
    if not full_name:
        flash("Nome completo é obrigatório.", "danger")
        return redirect(url_for("auth.register"))

    if not email or "@" not in email:
        flash("E-mail válido é obrigatório.", "danger")
        return redirect(url_for("auth.register"))

    if len(password) < 6:
        flash("Senha deve ter no mínimo 6 caracteres.", "danger")
        return redirect(url_for("auth.register"))

    if password != confirm_password:
        flash("As senhas não coincidem.", "danger")
        return redirect(url_for("auth.register"))

    if not phone:
        flash("Telefone / WhatsApp é obrigatório.", "danger")
        return redirect(url_for("auth.register"))

    # Verifica se usuário já existe
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash("Este e-mail já está cadastrado.", "danger")
        return redirect(url_for("auth.register"))

    # Cria novo usuário (apenas aluno)
    try:
        user = User(
            full_name=full_name,
            email=email,
            role="aluno",
            is_active_user=True,
            is_approved=False,  # Pendente de aprovação do administrador
            phone=phone or None,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Cadastro realizado com sucesso! Sua conta está pendente de aprovação do administrador.", "success")
        return redirect(url_for("auth.login"))
    except Exception as e:
        db.session.rollback()
        flash("Erro ao registrar. Tente novamente.", "danger")
        return redirect(url_for("auth.register"))


def get_reset_token(email, expires_in=3600):
    """Gera um token seguro para reset de senha"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='password-reset-salt')


def verify_reset_token(token, expires_in=3600):
    """Verifica e retorna o email do token de reset"""
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='password-reset-salt', max_age=expires_in)
        return email
    except (SignatureExpired, BadSignature):
        return None


def send_password_reset_email(email, reset_url):
    """Envia email com link de reset de senha"""
    msg = Message(
        subject="Redefinição de Senha - Agenda Escolar",
        recipients=[email],
        html=f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #0d7377;">Redefinição de Senha</h2>
                    <p>Você solicitou a redefinição de sua senha na <strong>Agenda Escolar</strong>.</p>
                    <p>Clique no botão abaixo para redefinir sua senha:</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{reset_url}" style="background-color: #0d7377; color: white; padding: 12px 30px; text-decoration: none; border-radius: 4px; display: inline-block; font-weight: bold;">
                            Redefinir Senha
                        </a>
                    </div>
                    <p style="font-size: 0.9em; color: #666;">
                        Ou copie e cole este link no seu navegador:<br>
                        <a href="{reset_url}" style="color: #0d7377; word-break: break-all;">{reset_url}</a>
                    </p>
                    <p style="font-size: 0.9em; color: #999; margin-top: 30px; border-top: 1px solid #eee; padding-top: 20px;">
                        Este link expira em 1 hora. Se você não solicitou uma redefinição de senha, ignore este email.
                    </p>
                </div>
            </body>
        </html>
        """
    )
    try:
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False


@auth_bp.get("/forgot-password")
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("core.dashboard"))
    return render_template("auth/forgot_password.html")


@auth_bp.post("/forgot-password")
@limiter.limit("5/minute")
def forgot_password_post():
    email = request.form.get("email", "").strip().lower()

    if not email:
        flash("E-mail é obrigatório.", "danger")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.filter_by(email=email).first()
    if not user:
        # Por segurança, não revelamos se o email existe
        flash("Se este e-mail estiver registrado, você receberá um link de reset.", "info")
        return redirect(url_for("auth.login"))

    # Gera token
    token = get_reset_token(email)
    reset_url = url_for("auth.reset_password", token=token, _external=True)

    # Envia email com o link
    if send_password_reset_email(email, reset_url):
        flash("Se este e-mail estiver registrado, você receberá um link de reset.", "info")
    else:
        flash("Erro ao enviar email. Tente novamente mais tarde.", "danger")
    
    return redirect(url_for("auth.login"))


@auth_bp.get("/reset-password/<token>")
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("core.dashboard"))

    email = verify_reset_token(token)
    if not email:
        flash("Token inválido ou expirado.", "danger")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token, email=email)


@auth_bp.post("/reset-password/<token>")
@limiter.limit("5/minute")
def reset_password_post(token):
    email = verify_reset_token(token)
    if not email:
        flash("Token inválido ou expirado.", "danger")
        return redirect(url_for("auth.login"))

    password = request.form.get("password", "").strip()
    confirm_password = request.form.get("confirm_password", "").strip()

    if len(password) < 6:
        flash("Senha deve ter no mínimo 6 caracteres.", "danger")
        return redirect(url_for("auth.reset_password", token=token))

    if password != confirm_password:
        flash("As senhas não coincidem.", "danger")
        return redirect(url_for("auth.reset_password", token=token))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Usuário não encontrado.", "danger")
        return redirect(url_for("auth.login"))

    try:
        user.set_password(password)
        db.session.commit()
        flash("Senha redefinida com sucesso! Você pode fazer login agora.", "success")
        return redirect(url_for("auth.login"))
    except Exception as e:
        db.session.rollback()
        flash("Erro ao redefinir senha. Tente novamente.", "danger")
        return redirect(url_for("auth.reset_password", token=token))
