"""
Serviço de envio de mensagens WhatsApp via Twilio.

Variáveis de ambiente necessárias:
  TWILIO_ACCOUNT_SID       — Account SID (começa com AC...)
  TWILIO_AUTH_TOKEN        — Auth Token
  TWILIO_WHATSAPP_FROM     — Número remetente (ex: +14155238886)
  TWILIO_WHATSAPP_ENABLED  — Defina como 1 para ativar os envios

Uso:
    from app.whatsapp import notify_cadastro_aprovado
    notify_cadastro_aprovado(nome="João", phone="11999998888")
"""

import logging
import os
import re

logger = logging.getLogger(__name__)


def _normalize_phone(phone: str) -> str:
    """Normaliza telefone para formato E.164 (ex: +5511999998888)."""
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if digits.startswith("55") and len(digits) >= 12:
        return "+" + digits
    if len(digits) in (10, 11):
        return "+55" + digits
    return "+" + digits


def _phone_candidates(phone: str) -> list[str]:
    """
    Gera candidatos de numero em E.164.

    Para Brasil, tenta tambem a variacao sem o 9 apos DDD quando houver
    divergencia de cadastro/join no sandbox Twilio.
    """
    normalized = _normalize_phone(phone)
    if not normalized:
        return []

    candidates = [normalized]

    # Exemplo: +55 63 9 9244-8880 -> alternativa +55 63 9244-8880
    if re.fullmatch(r"\+55\d{2}9\d{8}", normalized):
        alt = normalized[:5] + normalized[6:]
        if alt not in candidates:
            candidates.append(alt)

    return candidates


def send_whatsapp(phone: str, message: str) -> tuple[bool, str]:
    """
    Envia mensagem WhatsApp via Twilio.

    Retorna (True, message_sid) em sucesso ou (False, motivo) em falha.
    """
    if os.getenv("TWILIO_WHATSAPP_ENABLED", "0") != "1":
        logger.debug("Envio WhatsApp desabilitado (TWILIO_WHATSAPP_ENABLED != 1).")
        return False, "WhatsApp desabilitado"

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()

    if not account_sid or not auth_token or not from_number:
        logger.error(
            "Credenciais Twilio ausentes. Verifique TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN e TWILIO_WHATSAPP_FROM."
        )
        return False, "Credenciais Twilio ausentes"

    phone_candidates = _phone_candidates(phone)
    if not phone_candidates:
        logger.warning("Número inválido para WhatsApp: %r", phone)
        return False, "Número de telefone inválido"

    try:
        from twilio.rest import Client  # import tardio: não quebra se twilio não estiver instalado
        from twilio.base.exceptions import TwilioRestException

        client = Client(account_sid, auth_token)
        last_error = ""

        for candidate in phone_candidates:
            try:
                msg = client.messages.create(
                    from_=f"whatsapp:{from_number}",
                    to=f"whatsapp:{candidate}",
                    body=message,
                )
                logger.info("WhatsApp enviado para %s — SID: %s", candidate, msg.sid)
                return True, msg.sid
            except TwilioRestException as exc:
                last_error = f"Twilio {exc.code}: {exc.msg}"
                logger.warning("Falha Twilio ao enviar para %s: %s", candidate, last_error)

                # 63015 costuma indicar que o numero nao esta vinculado ao sandbox.
                # Se houver outro candidato de formato, tenta o proximo.
                if exc.code == 63015:
                    continue
                break

        return False, last_error or "Falha no envio WhatsApp"

    except ImportError:
        logger.error("Pacote 'twilio' não instalado. Execute: pip install twilio")
        return False, "Pacote twilio não instalado"
    except Exception as exc:  # noqa: BLE001
        logger.error("Erro ao enviar WhatsApp para %s: %s", to_normalized, exc)
        return False, str(exc)


# ---------------------------------------------------------------------------
# Funções públicas de alto nível
# ---------------------------------------------------------------------------

def notify_cadastro_aprovado(nome: str, phone: str) -> bool:
    """Notifica o aluno que seu cadastro foi aprovado."""
    message = (
        f"Olá, {nome}! 🎓 Seu cadastro na Agenda Escolar foi aprovado. "
        "Você já pode acessar a plataforma com seu e-mail e senha."
    )
    ok, info = send_whatsapp(phone, message)
    if not ok:
        logger.warning("notify_cadastro_aprovado falhou para %s: %s", phone, info)
    return ok


def notify_cadastro_reprovado(nome: str, phone: str) -> bool:
    """Notifica o aluno que seu cadastro foi recusado."""
    message = (
        f"Olá, {nome}. Infelizmente seu cadastro na Agenda Escolar não foi aprovado. "
        "Em caso de dúvidas, entre em contato com a escola."
    )
    ok, info = send_whatsapp(phone, message)
    if not ok:
        logger.warning("notify_cadastro_reprovado falhou para %s: %s", phone, info)
    return ok


def notify_lembrete_agendamento(nome: str, phone: str, horario: str) -> bool:
    """Envia lembrete de agendamento com a psicóloga."""
    message = (
        f"Olá, {nome}! 📅 Lembrete: você tem um atendimento com a psicóloga "
        f"amanhã às {horario}. Acesse a plataforma para mais detalhes."
    )
    ok, info = send_whatsapp(phone, message)
    if not ok:
        logger.warning("notify_lembrete_agendamento falhou para %s: %s", phone, info)
    return ok


def notify_novo_trabalho(
    nome: str,
    phone: str,
    titulo: str,
    disciplina: str | None,
    turma: str,
    prazo: str,
    professor: str,
) -> bool:
    """Notifica o aluno sobre um novo trabalho cadastrado pelo professor."""
    disciplina_info = f" ({disciplina})" if disciplina else ""
    message = (
        f"Olá, {nome}! 📚 Um novo trabalho foi cadastrado na Agenda Escolar.\n"
        f"*{titulo}*{disciplina_info}\n"
        f"Turma: {turma}\n"
        f"Professor(a): {professor}\n"
        f"Prazo de entrega: {prazo}\n"
        "Acesse a plataforma para ver os detalhes."
    )
    ok, info = send_whatsapp(phone, message)
    if not ok:
        logger.warning("notify_novo_trabalho falhou para %s: %s", phone, info)
    return ok


def notify_entrega_trabalho(
    nome_professor: str,
    phone: str,
    nome_aluno: str,
    titulo: str,
    acao: str = "entregou",
) -> bool:
    """Notifica o professor que um aluno entregou ou reenviou um trabalho."""
    message = (
        f"Olá, {nome_professor}! 📬 O(a) aluno(a) *{nome_aluno}* {acao} o trabalho:\n"
        f"*{titulo}*\n"
        "Acesse a plataforma para revisar a entrega."
    )
    ok, info = send_whatsapp(phone, message)
    if not ok:
        logger.warning("notify_entrega_trabalho falhou para %s: %s", phone, info)
    return ok


def notify_avaliacao_trabalho(
    nome: str,
    phone: str,
    titulo: str,
    status: str,
    feedback: str | None = None,
    nota: str | None = None,
) -> bool:
    """Notifica o aluno que seu trabalho foi aprovado ou devolvido pelo professor."""
    if status == "aprovado":
        emoji = "✅"
        acao = "aprovado"
    else:
        emoji = "🔄"
        acao = "devolvido para revisão"

    message = (
        f"Olá, {nome}! {emoji} O seu trabalho *{titulo}* foi {acao}.\n"
    )
    if nota:
        message += f"Nota: {nota}\n"
    if feedback:
        message += f"Comentário: {feedback}\n"
    message += "Acesse a plataforma para mais detalhes."

    ok, info = send_whatsapp(phone, message)
    if not ok:
        logger.warning("notify_avaliacao_trabalho falhou para %s: %s", phone, info)
    return ok
