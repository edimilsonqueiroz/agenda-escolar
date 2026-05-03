#!/usr/bin/env bash
# =============================================================================
#  deploy.sh — Implantação do Agenda Escolar em VPS Ubuntu 22.04 / 24.04
#
#  USO:
#    1. No VPS, clone o repositório:
#         git clone https://github.com/edimilsonqueiroz/agenda-escolar.git
#         cd agenda-escolar
#    2. Edite deploy.conf com seu domínio/IP e configurações
#    3. Execute como root:
#         sudo bash deploy.sh
#
#  Para atualizar o app no futuro, basta rodar deploy.sh novamente.
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# Cores e helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${NC} $*"; }
die()     { echo -e "${RED}[ERRO]${NC}  $*" >&2; exit 1; }
section() { echo -e "\n${BOLD}━━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# ---------------------------------------------------------------------------
# Verificação de root
# ---------------------------------------------------------------------------
[[ $EUID -eq 0 ]] || die "Execute como root: sudo bash deploy.sh"

# =============================================================================
#  LEITURA DA CONFIGURAÇÃO
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF_FILE="${SCRIPT_DIR}/deploy.conf"
[[ -f "$CONF_FILE" ]] || die "Arquivo deploy.conf não encontrado em ${SCRIPT_DIR}/"

# shellcheck source=/dev/null
source "$CONF_FILE"

# Validações
[[ -n "${GIT_REPO:-}"    ]] || die "GIT_REPO não definido no deploy.conf"
[[ -n "${SERVER_NAME:-}" ]] || die "SERVER_NAME não definido no deploy.conf"
[[ "$SERVER_NAME" != "SEU_DOMINIO_AQUI" ]] || \
    die "Edite SERVER_NAME no deploy.conf com seu domínio ou IP antes de continuar."

USE_SSL="${USE_SSL,,}"

# Gera SECRET_KEY se não definida
if [[ -z "${SECRET_KEY:-}" ]]; then
    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
fi

section "Configuração"
info "Repositório : ${GIT_REPO}"
info "Domínio/IP  : ${SERVER_NAME}"
info "Diretório   : ${APP_DIR}"
info "Usuário     : ${APP_USER}"
info "Banco       : PostgreSQL"
info "SSL         : ${USE_SSL}"

# =============================================================================
#  1. DEPENDÊNCIAS DO SISTEMA
# =============================================================================
section "1. Dependências do sistema"

apt-get update -q
apt-get install -y -q \
    python3 python3-pip python3-venv python3-dev \
    nginx git curl build-essential \
    libpq-dev libssl-dev libffi-dev \
    postgresql postgresql-contrib

ok "Pacotes instalados"

if [[ "$USE_SSL" == "sim" ]]; then
    apt-get install -y -q certbot python3-certbot-nginx
    ok "Certbot instalado"
fi

# =============================================================================
#  2. USUÁRIO DO SISTEMA
# =============================================================================
section "2. Usuário do sistema"

if ! id "$APP_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
    ok "Usuário '${APP_USER}' criado"
else
    warn "Usuário '${APP_USER}' já existe — mantido"
fi

# =============================================================================
#  3. POSTGRESQL
# =============================================================================
section "3. PostgreSQL"

systemctl enable postgresql
systemctl start postgresql
ok "Serviço PostgreSQL iniciado"

if [[ -z "${DATABASE_URL:-}" ]]; then
    # Banco local — criar usuário e banco automaticamente
    DB_NAME="${DB_NAME:-agenda_escolar}"
    DB_USER="${DB_USER:-agenda_db}"

    if [[ -z "${DB_PASS:-}" ]]; then
        DB_PASS="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
        warn "DB_PASS não definida — gerada automaticamente (salve-a!)"
        warn "DB_PASS=${DB_PASS}"
    fi

    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
        sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"
        ok "Usuário PostgreSQL '${DB_USER}' criado"
    else
        sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"
        warn "Usuário '${DB_USER}' já existe — senha atualizada"
    fi

    if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
        sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
        ok "Banco '${DB_NAME}' criado"
    else
        warn "Banco '${DB_NAME}' já existe — mantido"
    fi

    DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@localhost/${DB_NAME}"
    ok "DATABASE_URL configurada: postgresql://${DB_USER}:***@localhost/${DB_NAME}"
else
    ok "DATABASE_URL externa — banco local ignorado"
fi

# =============================================================================
#  4. CÓDIGO-FONTE
# =============================================================================
section "4. Código-fonte"

if [[ -d "${APP_DIR}/.git" ]]; then
    warn "Repositório já existe — atualizando..."
    git -C "$APP_DIR" pull --rebase origin main
    ok "Código atualizado"
else
    git clone "$GIT_REPO" "$APP_DIR"
    ok "Repositório clonado"
fi

chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"

# =============================================================================
#  5. AMBIENTE VIRTUAL PYTHON
# =============================================================================
section "5. Ambiente virtual Python"

VENV_DIR="${APP_DIR}/venv"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    ok "Virtualenv criado"
fi

"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt" --quiet
ok "Dependências Python instaladas"

# =============================================================================
#  6. ARQUIVO .env DE PRODUÇÃO
# =============================================================================
section "6. Arquivo .env"

ENV_FILE="${APP_DIR}/.env"

# Preserva SECRET_KEY se o .env já existir (evita invalidar sessões)
if [[ -f "$ENV_FILE" ]]; then
    EXISTING_KEY="$(grep '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2 || true)"
    [[ -n "$EXISTING_KEY" ]] && SECRET_KEY="$EXISTING_KEY"
fi

DB_BLOCK="DATABASE_URL=${DATABASE_URL}
PRODUCTION_DATABASE_URL=${DATABASE_URL}"

cat > "$ENV_FILE" <<EOF
# Gerado por deploy.sh em $(date '+%Y-%m-%d %H:%M')
FLASK_ENV=production
SECRET_KEY=${SECRET_KEY}

# Banco de dados
${DB_BLOCK}

# E-mail (opcional)
MAIL_SERVER=${MAIL_SERVER:-}
MAIL_PORT=${MAIL_PORT:-587}
MAIL_USERNAME=${MAIL_USERNAME:-}
MAIL_PASSWORD=${MAIL_PASSWORD:-}
MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER:-}

# WebSocket — origens permitidas
ALLOWED_SOCKET_ORIGINS=https://${SERVER_NAME},http://${SERVER_NAME}
EOF

chmod 600 "$ENV_FILE"
chown "${APP_USER}:${APP_USER}" "$ENV_FILE"
ok ".env criado em ${ENV_FILE}"

# =============================================================================
#  7. BANCO DE DADOS — MIGRAÇÕES E SEED
# =============================================================================
section "7. Banco de dados"

cd "$APP_DIR"

run_flask() {
    sudo -u "$APP_USER" \
        env $(grep -v '^#' "$ENV_FILE" | grep '=' | xargs) \
        FLASK_APP=run.py \
        "${VENV_DIR}/bin/flask" "$@"
}

run_python() {
    sudo -u "$APP_USER" \
        env $(grep -v '^#' "$ENV_FILE" | grep '=' | xargs) \
        "${VENV_DIR}/bin/python" "$@"
}

info "Aplicando migrações..."
run_flask db upgrade
ok "Migrações aplicadas"

ADMIN_EXISTS=$(run_python -c "
from app import create_app; from app.models import User
app = create_app()
with app.app_context():
    print('1' if User.query.filter_by(role='admin').first() else '0')
" 2>/dev/null || echo "0")

if [[ "$ADMIN_EXISTS" == "0" ]]; then
    info "Executando seed inicial..."
    run_flask seed
    ok "Seed executado"
    echo ""
    warn "┌─────────────────────────────────────────────────────┐"
    warn "│ Usuários criados — TROQUE AS SENHAS APÓS O LOGIN    │"
    warn "│                                                     │"
    warn "│  admin@escola.local  →  123456  (administrador)     │"
    warn "│  prof@escola.local   →  123456  (professor)         │"
    warn "│  aluno@escola.local  →  123456  (aluno)             │"
    warn "│  psi@escola.local    →  123456  (psicólogo)         │"
    warn "└─────────────────────────────────────────────────────┘"
else
    info "Banco já tem usuários — seed ignorado"
fi

# =============================================================================
#  8. SERVIÇO SYSTEMD (GUNICORN)
# =============================================================================
section "8. Serviço systemd"

mkdir -p /var/log/agenda_escolar
chown "${APP_USER}:${APP_USER}" /var/log/agenda_escolar

cat > /etc/systemd/system/agenda_escolar.service <<EOF
[Unit]
Description=Agenda Escolar — Gunicorn + Gevent
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment=FLASK_APP=run.py
ExecStart=${VENV_DIR}/bin/gunicorn \\
    --worker-class gevent \\
    --workers 1 \\
    --threads 1000 \\
    --bind 127.0.0.1:${GUNICORN_PORT} \\
    --timeout 120 \\
    --keep-alive 5 \\
    --access-logfile /var/log/agenda_escolar/access.log \\
    --error-logfile  /var/log/agenda_escolar/error.log \\
    wsgi:app
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable agenda_escolar
systemctl restart agenda_escolar
ok "Serviço agenda_escolar ativo"

# =============================================================================
#  9. NGINX — PROXY REVERSO
# =============================================================================
section "9. Nginx"

NGINX_CONF="/etc/nginx/sites-available/agenda_escolar"

cat > "$NGINX_CONF" <<EOF
upstream agenda_app {
    server 127.0.0.1:${GUNICORN_PORT};
}

server {
    listen 80;
    server_name ${SERVER_NAME};

    client_max_body_size 16M;

    # Estáticos servidos diretamente pelo Nginx (mais rápido)
    location /static/ {
        alias ${APP_DIR}/app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /static/uploads/ {
        alias ${APP_DIR}/app/static/uploads/;
        expires 7d;
    }

    location /static/submissions/ {
        alias ${APP_DIR}/app/static/submissions/;
        expires 7d;
    }

    # WebSocket — Socket.IO precisa de upgrade HTTP
    location /socket.io/ {
        proxy_pass         http://agenda_app;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Aplicação Flask
    location / {
        proxy_pass         http://agenda_app;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/agenda_escolar
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx
ok "Nginx configurado"

# =============================================================================
#  10. HTTPS COM CERTBOT (opcional)
# =============================================================================
if [[ "$USE_SSL" == "sim" ]]; then
    section "10. Certificado SSL (Let's Encrypt)"

    if [[ "$SERVER_NAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        warn "SSL pulado — Certbot exige domínio, não IP."
    elif [[ -z "${CERTBOT_EMAIL:-}" ]]; then
        warn "SSL pulado — defina CERTBOT_EMAIL no deploy.conf."
    else
        certbot --nginx \
            -d "$SERVER_NAME" \
            --email "$CERTBOT_EMAIL" \
            --agree-tos --non-interactive --redirect

        # Renovação automática
        systemctl enable certbot.timer 2>/dev/null || \
            { crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet"; } | crontab -

        ok "Certificado SSL instalado; renovação automática configurada"
    fi
fi

# =============================================================================
#  RESUMO
# =============================================================================
section "Deploy concluído"

echo ""
ok "Agenda Escolar está no ar!"
echo ""
echo -e "  ${BOLD}URL:${NC}      http://${SERVER_NAME}$( [[ "$USE_SSL" == "sim" ]] && echo "  +  https://${SERVER_NAME}" || echo "" )"
echo -e "  ${BOLD}App:${NC}      ${APP_DIR}"
echo -e "  ${BOLD}Logs:${NC}     /var/log/agenda_escolar/"
echo -e "  ${BOLD}Config:${NC}   ${ENV_FILE}"
echo ""
echo -e "  ${BOLD}Comandos úteis:${NC}"
echo -e "    Ver status:  ${YELLOW}systemctl status agenda_escolar${NC}"
echo -e "    Ver logs:    ${YELLOW}journalctl -u agenda_escolar -f${NC}"
echo -e "    Reiniciar:   ${YELLOW}systemctl restart agenda_escolar${NC}"
echo -e "    Atualizar:   ${YELLOW}cd ${APP_DIR} && git pull && systemctl restart agenda_escolar${NC}"
echo ""
if [[ "$USE_SSL" != "sim" ]]; then
    echo -e "  ${YELLOW}Quando o domínio estiver apontando para este servidor:${NC}"
    echo -e "    1. Edite ${BOLD}deploy.conf${NC}: mude USE_SSL=\"sim\" e preencha CERTBOT_EMAIL"
    echo -e "    2. Execute novamente: ${YELLOW}sudo bash deploy.sh${NC}"
fi
