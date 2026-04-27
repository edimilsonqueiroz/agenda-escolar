from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import limiter
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

    login_user(user)
    return redirect(url_for("core.dashboard"))


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
