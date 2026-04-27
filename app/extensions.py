import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address)

# Em produção, defina ALLOWED_SOCKET_ORIGINS para restringir origens WebSocket.
# Ex: ALLOWED_SOCKET_ORIGINS="https://meusite.com,https://www.meusite.com"
_cors_origins_raw = os.getenv("ALLOWED_SOCKET_ORIGINS", "*")
if _cors_origins_raw == "*":
    _cors_allowed_origins = "*"
else:
    _cors_allowed_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

socketio = SocketIO(async_mode="threading", cors_allowed_origins=_cors_allowed_origins)
