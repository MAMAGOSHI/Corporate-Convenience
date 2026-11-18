from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class Employee(UserMixin, db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    employee_number = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False, default="employee")
    department = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now)

    submitted_tickets = db.relationship(
        "Ticket",
        foreign_keys="Ticket.employee_id",
        back_populates="employee"
    )


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now)


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(30), unique=True, nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)

    employee_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False
    )

    employee = db.relationship(
        "Employee",
        foreign_keys=[employee_id],
        back_populates="submitted_tickets"
    )

    department = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    priority_reason = db.Column(db.Text)
    ai_suggested_priority = db.Column(db.String(20))
    ai_suggested_department = db.Column(db.String(50))

    status = db.Column(db.String(30), nullable=False, default="Open")

    assigned_to_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id")
    )

    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now,
        onupdate=now
    )

    # Added for real response-time and resolution analytics.
    first_response_at = db.Column(db.DateTime(timezone=True))
    resolved_at = db.Column(db.DateTime(timezone=True))
    escalated_at = db.Column(db.DateTime(timezone=True))

    messages = db.relationship(
        "TicketMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketMessage.created_at"
    )


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)

    ticket_id = db.Column(
        db.Integer,
        db.ForeignKey("tickets.id"),
        nullable=False
    )

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id"),
        nullable=False
    )

    body = db.Column(db.Text, nullable=False)

    # AI drafts are never automatically sent.
    is_ai_assisted = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=now)

    ticket = db.relationship("Ticket", back_populates="messages")
    sender = db.relationship("Employee")


class TicketHistory(db.Model):
    __tablename__ = "ticket_history"

    id = db.Column(db.Integer, primary_key=True)

    ticket_id = db.Column(
        db.Integer,
        db.ForeignKey("tickets.id"),
        nullable=False
    )

    changed_by_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id")
    )

    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now)

    changed_by = db.relationship("Employee")


class PriorityDecision(db.Model):
    __tablename__ = "priority_decisions"

    id = db.Column(db.Integer, primary_key=True)

    ticket_id = db.Column(
        db.Integer,
        db.ForeignKey("tickets.id"),
        nullable=False
    )

    suggested_priority = db.Column(db.String(20), nullable=False)
    final_priority = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    decision_source = db.Column(db.String(30), nullable=False)

    decided_by_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id")
    )

    created_at = db.Column(db.DateTime(timezone=True), default=now)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("employees.id")
    )

    action = db.Column(db.String(120), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime(timezone=True), default=now)

    user = db.relationship("Employee")


class EmailNotification(db.Model):
    __tablename__ = "email_notifications"

    id = db.Column(db.Integer, primary_key=True)

    ticket_id = db.Column(
        db.Integer,
        db.ForeignKey("tickets.id")
    )

    recipient = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(30), default="Pending")
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now)
