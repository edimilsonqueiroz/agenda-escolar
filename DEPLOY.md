# Deploy — Agenda Escolar

Guia completo para implantar o sistema em um VPS com **Ubuntu 22.04 / 24.04**.
O processo é automatizado pelo script `deploy.sh` + arquivo de configuração `deploy.conf`.

---

## Pré-requisitos

| Requisito | Detalhes |
|-----------|----------|
| Servidor  | VPS Ubuntu 22.04 ou 24.04 com acesso root |
| Python    | 3.10+ (instalado automaticamente pelo script) |
| Domínio *(opcional)* | Necessário apenas para HTTPS com Let's Encrypt |
| Porta 80  | Aberta no firewall do provedor |
| Porta 443 | Aberta apenas se for usar HTTPS |

---

## Passo a passo

### 1. Clonar o repositório no servidor

```bash
git clone https://github.com/edimilsonqueiroz/agenda-escolar.git
cd agenda-escolar
```

### 2. Editar o `deploy.conf`

Abra o arquivo e preencha os campos obrigatórios:

```bash
nano deploy.conf
```

| Campo | Obrigatório | Descrição |
|-------|-------------|-----------|
| `GIT_REPO` | Sim | URL do repositório Git |
| `SERVER_NAME` | Sim | Domínio ou IP público do servidor |
| `APP_DIR` | Não | Diretório de instalação (padrão: `/opt/agenda_escolar`) |
| `APP_USER` | Não | Usuário de sistema criado para a app (padrão: `agenda`) |
| `GUNICORN_PORT` | Não | Porta interna do Gunicorn (padrão: `8000`) |
| `DB_NAME` | Não | Nome do banco local criado pelo deploy (padrão: `agenda_escolar`) |
| `DB_USER` | Não | Usuário PostgreSQL local criado pelo deploy (padrão: `agenda_db`) |
| `DB_PASS` | Não | Senha do usuário PostgreSQL local; gerada automaticamente se vazia |
| `DATABASE_URL` | Não | URL de banco **externo**; deixe vazio para usar o banco local provisionado |
| `SECRET_KEY` | Não | Chave secreta Flask; gerada automaticamente se omitida |
| `USE_SSL` | Não | `"sim"` para instalar certificado Let's Encrypt |
| `CERTBOT_EMAIL` | Sim (se SSL) | E-mail para o Certbot |
| `MAIL_SERVER` | Não | Servidor SMTP para envio de e-mails |

**Exemplo mínimo:**

```ini
GIT_REPO="https://github.com/edimilsonqueiroz/agenda-escolar.git"
SERVER_NAME="203.0.113.10"   # ou "agenda.minhaescola.com.br"
DB_NAME="agenda_escolar"
DB_USER="agenda_db"
DB_PASS="minha_senha_forte"
USE_SSL="nao"
```

### 3. Executar o script de deploy

```bash
sudo bash deploy.sh
```

O script realiza automaticamente:

1. **Instalação de dependências** — Nginx, Python 3, pip, venv, libpq, PostgreSQL, etc.
2. **Criação do usuário de sistema** — usuário sem shell `agenda` (ou o definido em `APP_USER`)
3. **PostgreSQL** — inicia o serviço e, se `DATABASE_URL` estiver vazio, cria o banco e o usuário localmente
4. **Clone / atualização do código-fonte**
5. **Ambiente virtual Python** — cria o `venv` e instala o `requirements.txt`
6. **Arquivo `.env` de produção** — gerado com `FLASK_ENV=production`, `SECRET_KEY`, banco de dados e e-mail
7. **Migrações do banco** — executa `flask db upgrade`
8. **Seed inicial** — cria usuários padrão se o banco estiver vazio (ver abaixo)
9. **Serviço systemd** — Gunicorn + Gevent gerenciado pelo systemd, com reinicio automático
10. **Nginx** — proxy reverso com suporte a WebSocket (Socket.IO)
11. **HTTPS** *(opcional)* — certificado Let's Encrypt via Certbot com renovação automática

---

## Usuários criados no seed inicial

> **Troque as senhas imediatamente após o primeiro login.**

| E-mail | Senha | Perfil |
|--------|-------|--------|
| `admin@escola.local` | `123456` | Administrador |
| `prof@escola.local` | `123456` | Professor |
| `aluno@escola.local` | `123456` | Aluno |
| `psi@escola.local` | `123456` | Psicólogo |

O seed só é executado se não existir nenhum usuário administrador no banco.

---

## Configuração de banco de dados

> **SQLite não deve ser usado em produção.** O sistema requer PostgreSQL em ambiente produtivo.

O script instala o PostgreSQL automaticamente no VPS.

### Opção A — banco local (padrão, recomendado)

Deixe `DATABASE_URL` vazio no `deploy.conf` e preencha as variáveis de banco local. O script cria o usuário e o banco automaticamente:

```ini
DATABASE_URL=""            # vazio = banco local
DB_NAME="agenda_escolar"   # nome do banco
DB_USER="agenda_db"        # usuário PostgreSQL
DB_PASS="senha_forte"      # deixe vazio para gerar automaticamente
```

> Se `DB_PASS` for deixado vazio, uma senha aleatória é gerada e exibida na saída do script — **salve-a**.

### Opção B — banco externo (PostgreSQL já provisionado)

Defina `DATABASE_URL` diretamente e o provisionamento local é ignorado:

```ini
DATABASE_URL="postgresql://usuario:senha@host:5432/agenda"
```

### PostgreSQL (obrigatório em produção)

Se preferir configurar manualmente (Opção B), crie o banco antes e defina `DATABASE_URL` no `deploy.conf`:

```bash
sudo apt install postgresql postgresql-contrib   # já instalado pelo deploy.sh
sudo -u postgres createuser agenda_db
sudo -u postgres createdb agenda_escolar -O agenda_db
sudo -u postgres psql -c "ALTER USER agenda_db PASSWORD 'senha_forte';"
```

---

## Habilitando HTTPS (após apontar o domínio)

1. Certifique-se de que o DNS do domínio já aponta para o IP do servidor.
2. Edite `deploy.conf`:
   ```ini
   SERVER_NAME="agenda.minhaescola.com.br"
   USE_SSL="sim"
   CERTBOT_EMAIL="seu@email.com"
   ```
3. Execute o deploy novamente:
   ```bash
   sudo bash deploy.sh
   ```

O Certbot instala o certificado e configura a renovação automática.

---

## Atualizando o sistema

Para aplicar novas versões do código:

```bash
cd /opt/agenda_escolar
git pull
sudo bash deploy.sh
```

O script detecta que o repositório já existe, faz `git pull --rebase` e reinicia o serviço automaticamente.

---

## Comandos úteis pós-deploy

```bash
# Status do serviço
systemctl status agenda_escolar

# Logs em tempo real
journalctl -u agenda_escolar -f

# Logs de acesso / erro do Gunicorn
tail -f /var/log/agenda_escolar/access.log
tail -f /var/log/agenda_escolar/error.log

# Reiniciar o serviço
systemctl restart agenda_escolar

# Recarregar sem downtime (após mudança de config)
systemctl reload agenda_escolar

# Status do Nginx
systemctl status nginx
nginx -t   # testa a configuração
```

---

## Estrutura de arquivos no servidor

```
/opt/agenda_escolar/       ← código-fonte (APP_DIR)
  venv/                    ← ambiente virtual Python
  .env                     ← variáveis de ambiente (chmod 600)

/etc/nginx/sites-available/agenda_escolar   ← config do Nginx
/etc/systemd/system/agenda_escolar.service  ← serviço systemd
/var/log/agenda_escolar/                    ← logs do Gunicorn
```

---

## Variáveis de ambiente (`.env`)

O arquivo `.env` é gerado automaticamente pelo `deploy.sh`. Em caso de necessidade de edição manual:

```bash
sudo nano /opt/agenda_escolar/.env
sudo systemctl restart agenda_escolar
```

| Variável | Descrição |
|----------|-----------|
| `FLASK_ENV` | Deve ser `production` em produção |
| `SECRET_KEY` | Chave secreta do Flask; não altere após o deploy inicial |
| `DATABASE_URL` | URI do PostgreSQL externo — deixe vazio para usar o banco local provisionado pelo script |
| `MAIL_SERVER` | Servidor SMTP (deixe vazio para desabilitar e-mails) |
| `MAIL_PORT` | Porta SMTP (padrão: `587`) |
| `MAIL_USERNAME` | Usuário SMTP |
| `MAIL_PASSWORD` | Senha SMTP |
| `MAIL_DEFAULT_SENDER` | Remetente padrão dos e-mails |
| `ALLOWED_SOCKET_ORIGINS` | Origens permitidas para WebSocket |
| `RATE_LIMIT_DEFAULT` | Limite de requisições (padrão: `200/day;50/hour`) |

---

## Solução de problemas

**Serviço não inicia:**
```bash
journalctl -u agenda_escolar -n 50 --no-pager
```

**Erro 502 Bad Gateway no Nginx:**
```bash
systemctl status agenda_escolar   # verifique se o Gunicorn está rodando
journalctl -u agenda_escolar -n 20 --no-pager
```

**Erro de migração no banco:**
```bash
cd /opt/agenda_escolar
sudo -u agenda FLASK_APP=run.py FLASK_ENV=production venv/bin/flask db upgrade
```

**Resetar o banco (⚠ apaga todos os dados):**
```bash
sudo -u agenda FLASK_APP=run.py FLASK_ENV=production venv/bin/flask db downgrade base
sudo -u agenda FLASK_APP=run.py FLASK_ENV=production venv/bin/flask db upgrade
sudo -u agenda FLASK_APP=run.py FLASK_ENV=production venv/bin/flask seed
```

**Permissões nos uploads:**
```bash
chown -R agenda:agenda /opt/agenda_escolar/app/static/uploads
chown -R agenda:agenda /opt/agenda_escolar/app/static/submissions
chmod -R 755 /opt/agenda_escolar/app/static/uploads
```
