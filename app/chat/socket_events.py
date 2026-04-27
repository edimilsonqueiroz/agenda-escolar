from collections import defaultdict
from datetime import datetime

from flask_login import current_user
from flask_socketio import emit, join_room

from ..extensions import db
from ..models import ChatMessage, ChatRoom, User

online_users = {}
connections_per_user = defaultdict(int)


def register_socket_events(socketio):
    @socketio.on("connect")
    def handle_connect():
        if not current_user.is_authenticated:
            return False

        user_id = str(current_user.id)
        connections_per_user[user_id] += 1
        online_users[user_id] = {
            "id": current_user.id,
            "name": current_user.full_name,
            "role": current_user.role,
            "avatar": current_user.avatar or "",
            "connected_at": datetime.utcnow().isoformat(),
        }
        join_room("Geral")
        # Sala pessoal para notificações DM (sempre ativa, independente de abrir DM)
        join_room(f"user_{current_user.id}")
        emit_online_users()

    @socketio.on("disconnect")
    def handle_disconnect():
        if not current_user.is_authenticated:
            return

        user_id = str(current_user.id)
        connections_per_user[user_id] -= 1
        if connections_per_user[user_id] <= 0:
            connections_per_user.pop(user_id, None)
            online_users.pop(user_id, None)
        emit_online_users()

    @socketio.on("chat:join_dm")
    def handle_join_dm(payload):
        if not current_user.is_authenticated:
            return

        recipient_id = (payload or {}).get("recipient_id")
        if not recipient_id:
            return

        # Cria nome de sala consistente
        user_ids = sorted([current_user.id, recipient_id])
        room_name = f"dm_{user_ids[0]}_{user_ids[1]}"
        join_room(room_name)
        emit("chat:dm_joined", {"room": room_name})

    @socketio.on("chat:send")
    def handle_send_message(payload):
        if not current_user.is_authenticated:
            return

        content = (payload or {}).get("content", "").strip()
        room_name = (payload or {}).get("room", "Geral")
        recipient_id = (payload or {}).get("recipient_id")

        if not content:
            return
        if len(content) > 1000:
            emit("chat:error", {"message": "Mensagem excede limite de 1000 caracteres."})
            return

        if not current_user.can_chat:
            emit("chat:error", {"message": "Voce foi bloqueado pelo administrador e nao pode enviar mensagens."})
            return

        # Suporte a mensagens diretas
        if recipient_id:
            recipient = User.query.get(recipient_id)
            if not recipient or not recipient.is_active_user:
                emit("chat:error", {"message": "Destinatario nao encontrado."})
                return
            # Cria nome de sala privada consistente (dm_menor_id_maior_id)
            user_ids = sorted([current_user.id, recipient_id])
            room_name = f"dm_{user_ids[0]}_{user_ids[1]}"

        room = ChatRoom.query.filter_by(name=room_name).first()
        if not room:
            room = ChatRoom(name=room_name)
            db.session.add(room)
            db.session.flush()

        message = ChatMessage(content=content, room_id=room.id, sender_id=current_user.id)
        db.session.add(message)
        db.session.commit()

        msg_payload = {
            "id": message.id,
            "sender_id": current_user.id,
            "sender": current_user.full_name,
            "avatar": current_user.avatar or "",
            "content": message.content,
            "created_at": message.created_at.isoformat(),
            "room": room_name,
        }

        # Confirmar mensagem diretamente ao remetente (garante que ele vê a própria msg)
        emit("chat:new", msg_payload)
        # Broadcast para os demais na sala (excluindo o remetente para evitar duplicata)
        emit("chat:new", msg_payload, room=room_name, include_self=False)

        # Para DMs: notificação para a sala pessoal do destinatário
        # (caso ele não esteja na sala DM, recebe badge de notificação)
        if recipient_id and recipient_id != current_user.id:
            notify_payload = {**msg_payload, "is_dm_notify": True}
            emit("chat:dm_notify", notify_payload, room=f"user_{recipient_id}")


def emit_online_users():
    emit("presence:update", {"online": list(online_users.values())}, broadcast=True)
