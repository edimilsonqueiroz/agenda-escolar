import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect


db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
limiter = Limiter(key_func=get_remote_address)
mail = Mail()

# Em produção, defina ALLOWED_SOCKET_ORIGINS para restringir origens WebSocket.
# Ex: ALLOWED_SOCKET_ORIGINS="https://meusite.com,https://www.meusite.com"
_cors_origins_raw = os.getenv("ALLOWED_SOCKET_ORIGINS", "*")
if _cors_origins_raw == "*":
    _cors_allowed_origins = "*"
else:
    _cors_allowed_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

# Em produção (FLASK_ENV=production) usa gevent para suporte real a WebSocket.
# Em desenvolvimento usa threading (sem dependências extras).
_async_mode = "gevent" if os.getenv("FLASK_ENV") == "production" else "threading"

socketio = SocketIO(
    async_mode=_async_mode,
    cors_allowed_origins=_cors_allowed_origins,
    ping_timeout=60,
    ping_interval=25,
    logger=False,
    engineio_logger=False
)
