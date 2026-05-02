#!/usr/bin/env bash
# =============================================================================
#  deploy.sh — Implantação do Agenda Escolar em VPS Ubuntu 22.04 / 24.04
#
#  USO:
#    1. Faça upload deste arquivo para o VPS:
#         scp deploy.sh usuario@ip-do-vps:~/
#    2. Execute como root (ou com sudo):
#         sudo bash deploy.sh
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# --- Cores ----------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[AVISO]${NC} $*"; }
die()     { echo -e "${RED}[ERRO]${NC}  $*" >&2; exit 1; }
section() { echo -e "\n${BOLD}━━━ $* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

# --- Verificação de root --------------------------------------------------
[[ $EUID -eq 0 ]] || die "Execute como root: sudo bash deploy.sh"

# =============================================================================
#  CONFIGURAÇÃO INTERATIVA
# =============================================================================
section "Configuração do deploy"

# Repositório Git
read -rp "$(echo -e "${BOLD}URL do repositório Git${NC} (ex: https://github.com/usuario/agenda-escolar.git): ")" GIT_REPO
[[ -n "$GIT_REPO" ]] || die "Repositório obrigatório."

# Diretório de destino
read -rp "$(echo -e "${BOLD}Diretório de instalação${NC} [/opt/agenda_escolar]: ")" APP_DIR
APP_DIR="${APP_DIR:-/opt/agenda_escolar}"

# Usuário do sistema que vai rodar a app
read -rp "$(echo -e "${BOLD}Usuário do sistema para a app${NC} [agenda]: ")" APP_USER
APP_USER="${APP_USER:-agenda}"

# Domínio / IP público
read -rp "$(echo -e "${BOLD}Domínio ou IP do servidor${NC} (ex: escola.com.br ou 203.0.113.10): ")" SERVER_NAME
[[ -n "$SERVER_NAME" ]] || die "Domínio/IP obrigatório."

# Porta interna do Gunicorn
read -rp "$(echo -e "${BOLD}Porta interna do Gunicorn${NC} [8000]: ")" GUNICORN_PORT
GUNICORN_PORT="${GUNICORN_PORT:-8000}"

# Banco de dados (deixe em branco para usar SQLite)
echo ""
echo "Banco de dados:"
echo "  • Deixe em BRANCO para usar SQLite (simples, recomendado para começo)"
echo "  • Ou informe uma URL PostgreSQL: postgresql://usuario:senha@host/banco"
read -rp "$(echo -e "${BOLD}DATABASE_URL${NC} [SQLite]: ")" DATABASE_URL

# Chave secreta Flask
echo ""
info "Gerando SECRET_KEY aleatória..."
SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
echo -e "  SECRET_KEY gerada: ${YELLOW}${SECRET_KEY}${NC}"
echo "  (Guarde esta chave — ela protege as sessões de usuário)"

# E-mail para notificações (opcional)
read -rp "$(echo -e "\n${BOLD}E-mail SMTP — servidor${NC} [deixe em branco para desabilitar]: ")" MAIL_SERVER
if [[ -n "$MAIL_SERVER" ]]; then
    read -rp "$(echo -e "${BOLD}E-mail SMTP — porta${NC} [587]: ")" MAIL_PORT
    MAIL_PORT="${MAIL_PORT:-587}"
    read -rp "$(echo -e "${BOLD}E-mail SMTP — usuário${NC}: ")" MAIL_USERNAME
    read -rsp "$(echo -e "${BOLD}E-mail SMTP — senha${NC}: ")" MAIL_PASSWORD; echo
    read -rp "$(echo -e "${BOLD}E-mail SMTP — remetente${NC} (ex: noreply@escola.com.br): ")" MAIL_DEFAULT_SENDER
fi

# HTTPS com Certbot?
read -rp "$(echo -e "\n${BOLD}Instalar certificado SSL/HTTPS com Certbot?${NC} (s/N): ")" USE_SSL
USE_SSL="${USE_SSL,,}"

# =============================================================================
#  1. DEPENDÊNCIAS DO SISTEMA
# =============================================================================
section "1. Dependências do sistema"

apt-get update -q
apt-get install -y -q \
    python3 python3-pip python3-venv python3-dev \
    nginx git curl build-essential \
    libpq-dev libssl-dev libffi-dev \
    supervisor

ok "Dependências instaladas"

# Certbot (se pedido)
if [[ "$USE_SSL" == "s" ]]; then
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
#  3. DIRETÓRIO E CÓDIGO-FONTE
# =============================================================================
section "3. Código-fonte"

if [[ -d "$APP_DIR/.git" ]]; then
    warn "Repositório já existe — atualizando com git pull..."
    sudo -u "$APP_USER" git -C "$APP_DIR" pull --rebase origin main || \
        git -C "$APP_DIR" pull --rebase origin main
    ok "Código atualizado"
else
    info "Clonando repositório em ${APP_DIR}..."
    git clone "$GIT_REPO" "$APP_DIR"
    chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
    ok "Repositório clonado"
fi

chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

# =============================================================================
#  4. AMBIENTE VIRTUAL PYTHON
# =============================================================================
section "4. Ambiente virtual Python"

VENV_DIR="${APP_DIR}/venv"

if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    ok "Virtualenv criado"
fi

"${VENV_DIR}/bin/pip" install --upgrade pip --quiet
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt" --quiet
ok "Dependências Python instaladas"

# =============================================================================
#  5. ARQUIVO .env DE PRODUÇÃO
# =============================================================================
section "5. Configuração de ambiente (.env)"

ENV_FILE="${APP_DIR}/.env"

# Determina a URL do banco
if [[ -z "$DATABASE_URL" ]]; then
    DB_LINE="# DATABASE_URL não definida — usando SQLite"
    DB_URI_LINE=""
else
    DB_LINE="DATABASE_URL=${DATABASE_URL}"
    DB_URI_LINE="PRODUCTION_DATABASE_URL=${DATABASE_URL}"
fi

cat > "$ENV_FILE" <<EOF
# Gerado automaticamente por deploy.sh — $(date)
FLASK_ENV=production
SECRET_KEY=${SECRET_KEY}

# Banco de dados
${DB_LINE}
${DB_URI_LINE}

# E-mail (opcional)
MAIL_SERVER=${MAIL_SERVER:-}
MAIL_PORT=${MAIL_PORT:-587}
MAIL_USERNAME=${MAIL_USERNAME:-}
MAIL_PASSWORD=${MAIL_PASSWORD:-}
MAIL_DEFAULT_SENDER=${MAIL_DEFAULT_SENDER:-}

# WebSocket — restrinja em produção se quiser
ALLOWED_SOCKET_ORIGINS=*
EOF

chmod 600 "$ENV_FILE"
chown "$APP_USER":"$APP_USER" "$ENV_FILE"
ok ".env criado em ${ENV_FILE}"

# =============================================================================
#  6. BANCO DE DADOS — MIGRAÇÕES E SEED
# =============================================================================
section "6. Banco de dados"

FLASK="${VENV_DIR}/bin/flask"
cd "$APP_DIR"

info "Aplicando migrações..."
sudo -u "$APP_USER" env $(grep -v '^#' "$ENV_FILE" | xargs) \
    FLASK_APP=run.py "$FLASK" db upgrade
ok "Migrações aplicadas"

# Seed apenas na primeira instalação (sem usuário admin)
ADMIN_EXISTS=$(sudo -u "$APP_USER" env $(grep -v '^#' "$ENV_FILE" | xargs) \
    "${VENV_DIR}/bin/python" -c "
from app import create_app
from app.models import User
app = create_app()
with app.app_context():
    print('1' if User.query.filter_by(role='admin').first() else '0')
" 2>/dev/null || echo "0")

if [[ "$ADMIN_EXISTS" == "0" ]]; then
    info "Executando seed inicial (usuários de demonstração)..."
    sudo -u "$APP_USER" env $(grep -v '^#' "$ENV_FILE" | xargs) \
        FLASK_APP=run.py "$FLASK" seed
    ok "Seed executado"
    echo ""
    warn "Usuários criados:"
    warn "  admin@escola.local   senha: 123456  (TROQUE A SENHA APÓS O PRIMEIRO LOGIN)"
    warn "  prof@escola.local    senha: 123456"
    warn "  aluno@escola.local   senha: 123456"
    warn "  psi@escola.local     senha: 123456"
else
    info "Banco já possui usuários — seed ignorado"
fi

# =============================================================================
#  7. GUNICORN — SERVIÇO SYSTEMD
# =============================================================================
section "7. Serviço systemd (Gunicorn)"

SERVICE_FILE="/etc/systemd/system/agenda_escolar.service"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Agenda Escolar — Gunicorn/Gevent
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
Environment="FLASK_APP=run.py"
ExecStart=${VENV_DIR}/bin/gunicorn \
    --worker-class gevent \
    --workers 1 \
    --threads 1000 \
    --bind 127.0.0.1:${GUNICORN_PORT} \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile /var/log/agenda_escolar/access.log \
    --error-logfile /var/log/agenda_escolar/error.log \
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

mkdir -p /var/log/agenda_escolar
chown "$APP_USER":"$APP_USER" /var/log/agenda_escolar

systemctl daemon-reload
systemctl enable agenda_escolar
systemctl restart agenda_escolar
ok "Serviço agenda_escolar iniciado"

# =============================================================================
#  8. NGINX — PROXY REVERSO
# =============================================================================
section "8. Nginx"

NGINX_CONF="/etc/nginx/sites-available/agenda_escolar"

cat > "$NGINX_CONF" <<EOF
upstream agenda_app {
    server 127.0.0.1:${GUNICORN_PORT};
}

server {
    listen 80;
    server_name ${SERVER_NAME};

    # Tamanho máximo de upload (avatares, anexos)
    client_max_body_size 16M;

    # Arquivos estáticos diretamente pelo Nginx
    location /static/ {
        alias ${APP_DIR}/app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Uploads de usuários
    location /uploads/ {
        alias ${APP_DIR}/app/static/uploads/;
        expires 7d;
    }

    # WebSocket — Socket.IO
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

# Ativa o site e remove default se existir
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/agenda_escolar
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl reload nginx
ok "Nginx configurado e recarregado"

# =============================================================================
#  9. SSL COM CERTBOT (opcional)
# =============================================================================
if [[ "$USE_SSL" == "s" ]]; then
    section "9. Certificado SSL"

    # Precisa de domínio real (não funciona com IP)
    if [[ "$SERVER_NAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        warn "SSL ignorado — informe um domínio real (não IP) para usar Certbot."
    else
        read -rp "$(echo -e "${BOLD}E-mail para o Certbot${NC}: ")" CERTBOT_EMAIL
        [[ -n "$CERTBOT_EMAIL" ]] || die "E-mail obrigatório para Certbot."

        certbot --nginx \
            -d "$SERVER_NAME" \
            --email "$CERTBOT_EMAIL" \
            --agree-tos --non-interactive --redirect

        # Renovação automática
        systemctl enable certbot.timer 2>/dev/null || \
            (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet") | crontab -

        ok "Certificado SSL instalado e renovação automática configurada"
    fi
fi

# =============================================================================
#  RESUMO FINAL
# =============================================================================
section "Deploy concluído"

echo ""
ok "Agenda Escolar está no ar!"
echo ""
echo -e "  ${BOLD}URL:${NC}       http://${SERVER_NAME}$( [[ "$USE_SSL" == "s" ]] && echo " (e https://)" || true )"
echo -e "  ${BOLD}App dir:${NC}   ${APP_DIR}"
echo -e "  ${BOLD}Logs:${NC}      /var/log/agenda_escolar/"
echo -e "  ${BOLD}Serviço:${NC}   systemctl status agenda_escolar"
echo ""
echo -e "  ${BOLD}Comandos úteis:${NC}"
echo -e "    Reiniciar app:   ${YELLOW}systemctl restart agenda_escolar${NC}"
echo -e "    Ver logs:        ${YELLOW}journalctl -u agenda_escolar -f${NC}"
echo -e "    Atualizar app:   ${YELLOW}cd ${APP_DIR} && git pull && systemctl restart agenda_escolar${NC}"
echo ""
if [[ "$ADMIN_EXISTS" == "0" ]]; then
    warn "IMPORTANTE: Faça login com admin@escola.local / 123456 e troque a senha imediatamente!"
fi
