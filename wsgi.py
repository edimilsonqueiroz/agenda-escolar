"""
Ponto de entrada para o servidor de produção (Gunicorn + Gevent).

Uso:
    gunicorn --worker-class gevent --workers 1 --bind unix:/run/agenda_escolar.sock wsgi:app
"""
from app import create_app

app = create_app()
