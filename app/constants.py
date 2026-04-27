"""Constantes centralizadas para roles, status e configurações de negócio."""


class UserRole:
    ADMIN = "admin"
    PROFESSOR = "professor"
    ALUNO = "aluno"
    PSICOLOGO = "psicologo"

    ALL = {ADMIN, PROFESSOR, ALUNO, PSICOLOGO}


class SubmissionStatus:
    PENDENTE = "pendente"
    APROVADO = "aprovado"
    DEVOLVIDO = "devolvido"

    ALL = {PENDENTE, APROVADO, DEVOLVIDO}


class AppointmentStatus:
    PENDENTE = "pendente"
    CONFIRMADO = "confirmado"
    REALIZADO = "realizado"
    CANCELADO = "cancelado"

    ALL = {PENDENTE, CONFIRMADO, REALIZADO, CANCELADO}


class WorkType:
    INDIVIDUAL = "individual"
    GROUP = "group"

    ALL = {INDIVIDUAL, GROUP}


APPOINTMENT_SLOT_MINUTES = 40
