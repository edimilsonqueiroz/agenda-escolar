"""
Testes dos helpers de chat e eventos Socket.IO (app/chat/socket_events.py).

Cobre:
- parse_recipient_id: inteiro válido, string não numérica, None, negativo
- build_dm_room_name: ordenação correta dos IDs
- get_active_recipient: destinatário existente, inexistente, inativo
"""
import pytest

from app.chat.socket_events import build_dm_room_name, get_active_recipient, parse_recipient_id
from tests.conftest import make_user


# ---------------------------------------------------------------------------
# parse_recipient_id
# ---------------------------------------------------------------------------

class TestParseRecipientId:
    def test_valid_integer_string(self):
        assert parse_recipient_id("42") == 42

    def test_valid_integer(self):
        assert parse_recipient_id(42) == 42

    def test_none_returns_none(self):
        assert parse_recipient_id(None) is None

    def test_empty_string_returns_none(self):
        assert parse_recipient_id("") is None

    def test_non_numeric_string_returns_none(self):
        assert parse_recipient_id("abc") is None

    def test_float_string_returns_none(self):
        assert parse_recipient_id("1.5") is None

    def test_negative_number(self):
        # Negativo é um inteiro válido no contexto do parsing
        assert parse_recipient_id("-1") == -1

    def test_zero(self):
        assert parse_recipient_id("0") == 0

    def test_whitespace_string_returns_none(self):
        assert parse_recipient_id("   ") is None


# ---------------------------------------------------------------------------
# build_dm_room_name
# ---------------------------------------------------------------------------

class TestBuildDmRoomName:
    def test_smaller_id_first(self):
        assert build_dm_room_name(9, 2) == "dm_2_9"

    def test_already_ordered(self):
        assert build_dm_room_name(1, 5) == "dm_1_5"

    def test_same_id(self):
        assert build_dm_room_name(3, 3) == "dm_3_3"

    def test_string_ids_work(self):
        assert build_dm_room_name("10", "3") == "dm_3_10"

    def test_commutative(self):
        """build_dm_room_name(a, b) deve ser igual a build_dm_room_name(b, a)."""
        assert build_dm_room_name(7, 4) == build_dm_room_name(4, 7)


# ---------------------------------------------------------------------------
# get_active_recipient
# ---------------------------------------------------------------------------

class TestGetActiveRecipient:
    def test_valid_active_user_returns_user(self, app):
        with app.app_context():
            user = make_user("aluno", "recv.ok@test.com")
            raw_id = str(user.id)

            recipient_id, recipient = get_active_recipient(raw_id)
            assert recipient_id == user.id
            assert recipient is not None
            assert recipient.email == "recv.ok@test.com"

    def test_inactive_user_returns_none_recipient(self, app):
        with app.app_context():
            user = make_user("aluno", "recv.inactive@test.com",
                             is_active_user=False)
            raw_id = str(user.id)

            recipient_id, recipient = get_active_recipient(raw_id)
            assert recipient_id == user.id
            assert recipient is None

    def test_nonexistent_user_returns_none_both(self, app):
        with app.app_context():
            recipient_id, recipient = get_active_recipient("999999")
            assert recipient_id == 999999
            assert recipient is None

    def test_invalid_string_returns_none_none(self, app):
        with app.app_context():
            recipient_id, recipient = get_active_recipient("naoexiste")
            assert recipient_id is None
            assert recipient is None

    def test_none_input_returns_none_none(self, app):
        with app.app_context():
            recipient_id, recipient = get_active_recipient(None)
            assert recipient_id is None
            assert recipient is None
