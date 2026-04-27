# Agenda Escolar - Plataforma de Acompanhamento

Plataforma web para escola publica com os perfis:
- Administrador
- Professor
- Aluno
- Psicologa(o)

## Funcionalidades
- Cadastro e login com controle de acesso por perfil.
- Gestao de trabalhos semanais por turma.
- Agendamento de acompanhamento psicologico.
- Chat em tempo real com lista de usuarios online.

## Stack
- Backend: Flask + SQLAlchemy + Flask-Login
- Realtime: Flask-SocketIO
- Frontend: HTML + CSS + JavaScript
- Banco: SQLite (dev), compativel com PostgreSQL (prod)

## Banco por ambiente
- Desenvolvimento:
   - `FLASK_ENV=development`
   - `DEVELOPMENT_DATABASE_URL=sqlite:///agenda_escolar.db`
- Producao:
   - `FLASK_ENV=production`
   - `PRODUCTION_DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/agenda_escolar`

Observacao: se `DATABASE_URL` estiver definido, ele tem prioridade em ambos os ambientes.

## Como executar
1. Crie e ative um ambiente virtual.
2. Instale dependencias:
   - `pip install -r requirements.txt`
3. Copie `.env.example` para `.env` e ajuste as variaveis.
4. Inicialize o banco:
   - `flask --app run.py db init`
   - `flask --app run.py db migrate -m "init"`
   - `flask --app run.py db upgrade`
5. Crie dados iniciais:
   - `flask --app run.py seed`
6. Rode o servidor:
   - `python run.py`

## Seguranca aplicada
- Hash de senha com Werkzeug.
- CSRF em formularios.
- Sessao segura e cookies com protecao.
- Rate limit por IP e por endpoint critico.
- Validacao de entrada no backend.

## Arquitetura
- `app/` com application factory e blueprints.
- `app/auth` para autenticacao.
- `app/core` para dashboards e paginas principais.
- `app/api` para endpoints de dados.
- `app/chat` para eventos de websocket.
- `app/templates` e `app/static` para frontend.

## Producao
- Use PostgreSQL, Redis (socketio message queue) e Gunicorn/Uvicorn workers adequados.
- Configure HTTPS, reverse proxy e rotacao de logs.
