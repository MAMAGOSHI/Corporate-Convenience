#!/bin/bash

set -e

echo "=========================================="
echo " CORPORATE CONVENIENCE - FRESH REBUILD"
echo "=========================================="

# Protect the existing environment and secrets.
mkdir -p backend templates static tests data instance

# Create requirements.
cat > requirements.txt <<'EOF'
Flask
Flask-SQLAlchemy
Flask-Login
Flask-WTF
python-dotenv
Werkzeug
email-validator
google-genai
gunicorn
EOF

# Create Git ignore rules.
cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.py[cod]
.env
.env.*
!.env.example
instance/
*.db
*.sqlite
*.sqlite3
.DS_Store
*.log
EOF

# Create environment template.
cat > .env.example <<'EOF'
SECRET_KEY=replace-with-a-secure-key
GEMINI_API_KEY=
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=
EOF

# Application configuration.
cat > backend/config.py <<'EOF'
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = (
        "sqlite:///" + str(INSTANCE_DIR / "corporate_convenience.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "")
EOF

# Database models.
cat > backend/database.py <<'EOF'
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now():
    return datetime.now(timezone.utc)


class Employee(db.Model):
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


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(30), unique=True, nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="Medium")
    priority_reason = db.Column(db.Text)
    ai_suggested_priority = db.Column(db.String(20))
    ai_suggested_department = db.Column(db.String(50))
    status = db.Column(db.String(30), nullable=False, default="Open")
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now)
    updated_at = db.Column(db.DateTime(timezone=True), default=now, onupdate=now)


class TicketHistory(db.Model):
    __tablename__ = "ticket_history"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now)


class PriorityDecision(db.Model):
    __tablename__ = "priority_decisions"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    suggested_priority = db.Column(db.String(20), nullable=False)
    final_priority = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    decision_source = db.Column(db.String(30), nullable=False)
    decided_by_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=now)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    action = db.Column(db.String(120), nullable=False)
    entity_type = db.Column(db.String(50))
    entity_id = db.Column(db.Integer)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime(timezone=True), default=now)


class EmailNotification(db.Model):
    __tablename__ = "email_notifications"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"))
    recipient = db.Column(db.String(150), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(30), default="Pending")
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=now)
EOF

# Explainable first-stage classifier.
cat > backend/classifier.py <<'EOF'
DEPARTMENTS = ("HR", "IT", "Finance", "Operations")


def classify_ticket(subject, description):
    """
    Transparent baseline classifier.
    These are suggestions, not final decisions.
    A staff member can change the department or priority.
    """
    text = f"{subject} {description}".lower()

    department_terms = {
        "HR": ["leave", "salary", "harassment", "manager", "workplace",
               "payslip", "recruitment", "benefit", "disciplinary"],
        "IT": ["laptop", "computer", "email", "password", "network",
               "software", "system", "printer", "internet", "access"],
        "Finance": ["invoice", "payment", "reimbursement", "expense",
                    "budget", "purchase order", "claim"],
        "Operations": ["building", "office", "cleaning", "security",
                       "equipment", "maintenance", "facility"]
    }

    scores = {
        department: sum(1 for word in terms if word in text)
        for department, terms in department_terms.items()
    }

    best_department = max(scores, key=scores.get)
    if scores[best_department] == 0:
        best_department = "Operations"
        department_reason = "No strong department indicators; routed to Operations for review."
    else:
        department_reason = (
            f"Suggested from matching terms for {best_department}."
        )

    high_terms = [
        "unsafe", "danger", "threat", "injury", "harassment",
        "data breach", "security breach", "urgent", "emergency"
    ]
    medium_terms = [
        "unable", "blocked", "cannot work", "not working",
        "overdue", "missing", "incorrect", "complaint"
    ]

    if any(term in text for term in high_terms):
        priority = "High"
        priority_reason = "Potential safety, security or urgent risk indicator."
    elif any(term in text for term in medium_terms):
        priority = "Medium"
        priority_reason = "Service disruption or complaint indicator."
    else:
        priority = "Low"
        priority_reason = "No high-risk or service-disruption indicator detected."

    return {
        "department": best_department,
        "department_reason": department_reason,
        "priority": priority,
        "priority_reason": priority_reason
    }
EOF

# Email notification service.
cat > backend/email_service.py <<'EOF'
import smtplib
from email.message import EmailMessage
from flask import current_app


def send_notification(recipient, subject, body):
    username = current_app.config.get("MAIL_USERNAME")
    password = current_app.config.get("MAIL_PASSWORD")
    sender = current_app.config.get("MAIL_DEFAULT_SENDER") or username

    if not username or not password or not sender:
        return False, "Email credentials are not configured."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    try:
        with smtplib.SMTP(
            current_app.config["MAIL_SERVER"],
            current_app.config["MAIL_PORT"],
            timeout=20
        ) as server:
            if current_app.config["MAIL_USE_TLS"]:
                server.starttls()
            server.login(username, password)
            server.send_message(message)
        return True, None
    except Exception as error:
        current_app.logger.exception("Email delivery failed")
        return False, str(error)
EOF

# Main Flask application.
cat > app.py <<'EOF'
import secrets
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, abort
)
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

from backend.config import Config
from backend.database import (
    db, Employee, Ticket, TicketHistory,
    PriorityDecision, AuditLog, EmailNotification
)
from backend.classifier import classify_ticket
from backend.email_service import send_notification


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is missing. Check your .env file.")

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Employee, int(user_id))

    def role_required(*roles):
        def decorator(function):
            @wraps(function)
            @login_required
            def wrapped(*args, **kwargs):
                if current_user.role not in roles:
                    abort(403)
                return function(*args, **kwargs)
            return wrapped
        return decorator

    def record_audit(action, entity_type=None, entity_id=None, details=None):
        db.session.add(AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=request.remote_addr
        ))

    def can_view_ticket(ticket):
        if current_user.role == "admin":
            return True
        if current_user.role == "employee":
            return ticket.employee_id == current_user.id
        return ticket.department == current_user.department

    def notify(recipient, subject, body, ticket_id, kind):
        success, error = send_notification(recipient, subject, body)
        db.session.add(EmailNotification(
            ticket_id=ticket_id,
            recipient=recipient,
            subject=subject,
            notification_type=kind,
            status="Sent" if success else "Failed",
            error_message=error
        ))

    @app.route("/")
    @login_required
    def index():
        query = Ticket.query.filter_by(is_archived=False)

        if current_user.role == "employee":
            query = query.filter_by(employee_id=current_user.id)
        elif current_user.role != "admin":
            query = query.filter_by(department=current_user.department)

        tickets = query.order_by(Ticket.created_at.desc()).all()
        return render_template("index.html", tickets=tickets)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip()
            password = request.form.get("password", "")

            employee = Employee.query.filter(
                db.or_(
                    Employee.employee_number == identifier,
                    Employee.email == identifier.lower()
                )
            ).first()

            if (
                employee
                and employee.is_active
                and check_password_hash(employee.password_hash, password)
            ):
                login_user(employee)
                record_audit("User signed in")
                db.session.commit()
                return redirect(url_for("index"))

            flash("The sign-in details are incorrect.", "error")

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        record_audit("User signed out")
        db.session.commit()
        logout_user()
        return redirect(url_for("login"))

    @app.route("/tickets/new", methods=["POST"])
    @role_required("employee")
    def create_ticket():
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()

        if not subject or not description:
            flash("Please provide a subject and description.", "error")
            return redirect(url_for("index"))

        suggestion = classify_ticket(subject, description)
        ticket_number = "CC-" + secrets.token_hex(4).upper()

        ticket = Ticket(
            ticket_number=ticket_number,
            subject=subject,
            description=description,
            employee_id=current_user.id,
            department=suggestion["department"],
            priority=suggestion["priority"],
            priority_reason=suggestion["priority_reason"],
            ai_suggested_priority=suggestion["priority"],
            ai_suggested_department=suggestion["department"],
            status="Open"
        )
        db.session.add(ticket)
        db.session.flush()

        db.session.add(TicketHistory(
            ticket_id=ticket.id,
            changed_by_id=current_user.id,
            action="Ticket submitted",
            details="Ticket created and classification suggestions recorded."
        ))

        db.session.add(PriorityDecision(
            ticket_id=ticket.id,
            suggested_priority=suggestion["priority"],
            final_priority=suggestion["priority"],
            reason=suggestion["priority_reason"],
            decision_source="Automated suggestion"
        ))

        record_audit(
            "Ticket created", "Ticket", ticket.id, ticket_number
        )

        # Notify the employee and department support accounts.
        notify(
            current_user.email,
            f"Complaint received: {ticket_number}",
            f"Your complaint has been received. Reference: {ticket_number}.",
            ticket.id,
            "Employee acknowledgement"
        )

        staff = Employee.query.filter_by(
            role="support",
            department=ticket.department,
            is_active=True
        ).all()

        for person in staff:
            notify(
                person.email,
                f"New department ticket: {ticket_number}",
                f"A new ticket has been assigned to {ticket.department}. "
                f"Subject: {subject}. Priority suggestion: {ticket.priority}.",
                ticket.id,
                "Department notification"
            )

        db.session.commit()
        flash(f"Your ticket {ticket_number} has been submitted.", "success")
        return redirect(url_for("index"))

    @app.route("/tickets/<int:ticket_id>", methods=["GET", "POST"])
    @login_required
    def ticket_detail(ticket_id):
        ticket = db.get_or_404(Ticket, ticket_id)

        if not can_view_ticket(ticket):
            abort(403)

        if request.method == "POST":
            if current_user.role == "employee":
                abort(403)

            old_status = ticket.status
            old_priority = ticket.priority
            old_department = ticket.department

            status = request.form.get("status", ticket.status)
            priority = request.form.get("priority", ticket.priority)
            department = request.form.get("department", ticket.department)

            if status not in ("Open", "In Progress", "Resolved"):
                abort(400)
            if priority not in ("Low", "Medium", "High"):
                abort(400)
            if department not in ("HR", "IT", "Finance", "Operations"):
                abort(400)

            ticket.status = status
            ticket.priority = priority
            ticket.department = department

            changes = []
            if old_status != status:
                changes.append(f"Status: {old_status} → {status}")
            if old_priority != priority:
                changes.append(f"Priority: {old_priority} → {priority}")
            if old_department != department:
                changes.append(f"Department: {old_department} → {department}")

            if changes:
                reason = request.form.get("reason", "").strip()
                if (old_priority != priority or old_department != department) and not reason:
                    db.session.rollback()
                    flash("Please provide a reason for changing priority or department.", "error")
                    return redirect(url_for("ticket_detail", ticket_id=ticket.id))

                details = "; ".join(changes)
                if reason:
                    details += f". Reason: {reason}"

                db.session.add(TicketHistory(
                    ticket_id=ticket.id,
                    changed_by_id=current_user.id,
                    action="Ticket updated",
                    details=details
                ))

                if old_priority != priority:
                    db.session.add(PriorityDecision(
                        ticket_id=ticket.id,
                        suggested_priority=ticket.ai_suggested_priority or old_priority,
                        final_priority=priority,
                        reason=reason,
                        decision_source="Human review",
                        decided_by_id=current_user.id
                    ))

                record_audit("Ticket updated", "Ticket", ticket.id, details)

            if status == "Resolved":
                ticket.is_archived = True
            elif old_status == "Resolved":
                ticket.is_archived = False

            db.session.commit()
            flash("Ticket updated successfully.", "success")
            return redirect(url_for("index"))

        history = TicketHistory.query.filter_by(
            ticket_id=ticket.id
        ).order_by(TicketHistory.created_at.desc()).all()

        return render_template(
            "ticket.html", ticket=ticket, history=history
        )

    @app.route("/archive")
    @role_required("admin")
    def archive():
        tickets = Ticket.query.filter_by(
            is_archived=True
        ).order_by(Ticket.updated_at.desc()).all()
        return render_template("archive.html", tickets=tickets)

    @app.route("/admin")
    @role_required("admin")
    def admin():
        employees = Employee.query.order_by(Employee.full_name).all()
        tickets = Ticket.query.order_by(Ticket.created_at.desc()).limit(50).all()
        audit_logs = AuditLog.query.order_by(
            AuditLog.created_at.desc()
        ).limit(30).all()

        return render_template(
            "admin.html",
            employees=employees,
            tickets=tickets,
            audit_logs=audit_logs
        )

    @app.route("/admin/accounts", methods=["POST"])
    @role_required("admin")
    def create_account():
        employee_number = request.form.get("employee_number", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "employee")
        department = request.form.get("department", "")

        if role not in ("employee", "support", "admin"):
            abort(400)

        if role == "support" and department not in (
            "HR", "IT", "Finance", "Operations"
        ):
            flash("Support accounts need a valid department.", "error")
            return redirect(url_for("admin"))

        if role == "employee":
            department = department or None

        if not all((employee_number, full_name, email, password)):
            flash("Please complete all required account fields.", "error")
            return redirect(url_for("admin"))

        if len(password) < 12:
            flash("Passwords must be at least 12 characters.", "error")
            return redirect(url_for("admin"))

        duplicate = Employee.query.filter(
            db.or_(
                Employee.employee_number == employee_number,
                Employee.email == email
            )
        ).first()

        if duplicate:
            flash("That employee number or email already exists.", "error")
            return redirect(url_for("admin"))

        employee = Employee(
            employee_number=employee_number,
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            department=department
        )
        db.session.add(employee)
        db.session.flush()
        record_audit("Account created", "Employee", employee.id, role)
        db.session.commit()

        flash("Account created successfully.", "success")
        return redirect(url_for("admin"))

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("error.html", message="You do not have permission to access this page."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", message="The requested page could not be found."), 404

    with app.app_context():
        db.create_all()

    return app


app = create_app()


@app.cli.command("create-admin")
def create_admin():
    """Create the first administrator interactively."""
    import getpass

    if Employee.query.filter_by(role="admin").first():
        print("An administrator already exists.")
        return

    number = input("Administrator employee number: ").strip()
    name = input("Full name: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password (minimum 12 characters): ")

    if not all((number, name, email)) or len(password) < 12:
        print("Please provide all details and a password of at least 12 characters.")
        return

    if Employee.query.filter(
        db.or_(Employee.employee_number == number, Employee.email == email)
    ).first():
        print("That employee number or email is already registered.")
        return

    admin_user = Employee(
        employee_number=number,
        full_name=name,
        email=email,
        password_hash=generate_password_hash(password),
        role="admin"
    )
    db.session.add(admin_user)
    db.session.commit()
    print("Administrator account created.")


if __name__ == "__main__":
    app.run(debug=True)
EOF

# Login page.
cat > templates/login.html <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in | Corporate Convenience</title>
<link rel="stylesheet" href="{{ url_for('static', filename='stylesheet.css') }}">
</head>
<body class="login-page">
<div class="login-shell">
    <section class="login-brand">
        <div class="brand-mark">CC</div>
        <p class="eyebrow">CORPORATE CONVENIENCE</p>
        <h1>A better way<br>to be heard.</h1>
        <p class="brand-copy">One place for employee concerns, support and meaningful resolutions.</p>
        <div class="brand-footer">People matter. Every voice counts.</div>
    </section>
    <section class="login-panel">
        <div class="login-content">
            <p class="eyebrow orange">WELCOME BACK</p>
            <h2>Sign in to your account</h2>
            <p class="muted">Use the employee credentials provided by your administrator.</p>
            {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, message in messages %}
            <div class="notice {{ category }}">{{ message }}</div>
            {% endfor %}
            {% endwith %}
            <form method="POST">
                <label>Employee number or email</label>
                <input name="identifier" required autocomplete="username" placeholder="Enter your employee ID or email">
                <label>Password</label>
                <input type="password" name="password" required autocomplete="current-password" placeholder="Enter your password">
                <button class="primary full">Sign in <span>→</span></button>
            </form>
            <p class="small muted">Need access? Contact your system administrator.</p>
        </div>
    </section>
</div>
</body>
</html>
EOF

# Main dashboard.
cat > templates/index.html <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard | Corporate Convenience</title>
<link rel="stylesheet" href="{{ url_for('static', filename='stylesheet.css') }}">
</head>
<body>
<header class="topbar">
    <a class="wordmark" href="{{ url_for('index') }}"><span class="brand-mark small-mark">CC</span> Corporate Convenience</a>
    <nav>
        <span>{{ current_user.full_name }} · {{ current_user.role|title }}</span>
        {% if current_user.role == 'admin' %}<a href="{{ url_for('admin') }}">Administration</a>{% endif %}
        {% if current_user.role == 'admin' %}<a href="{{ url_for('archive') }}">Archive</a>{% endif %}
        <a href="{{ url_for('logout') }}">Sign out</a>
    </nav>
</header>
<main class="container">
    <div class="page-heading">
        <div>
            <p class="eyebrow orange">YOUR WORKSPACE</p>
            <h1>{% if current_user.role == 'employee' %}Your requests{% else %}Department requests{% endif %}</h1>
            <p class="muted">Track concerns, updates and resolutions in one place.</p>
        </div>
    </div>
    {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}<div class="notice {{ category }}">{{ message }}</div>{% endfor %}
    {% endwith %}
    {% if current_user.role == 'employee' %}
    <section class="panel new-ticket">
        <h2>Submit a concern</h2>
        <p class="muted">Describe what happened. The system will suggest a department and priority for review.</p>
        <form method="POST" action="{{ url_for('create_ticket') }}">
            <label>Subject</label>
            <input name="subject" maxlength="200" required placeholder="Briefly describe your concern">
            <label>What would you like us to know?</label>
            <textarea name="description" rows="5" required placeholder="Provide the details of your concern..."></textarea>
            <button class="primary">Submit concern →</button>
        </form>
    </section>
    {% endif %}
    <section class="panel">
        <div class="section-heading"><h2>{% if current_user.role == 'employee' %}Your submitted tickets{% else %}Active department tickets{% endif %}</h2><span class="count">{{ tickets|length }} records</span></div>
        {% if tickets %}
        <div class="table-wrap"><table>
            <thead><tr><th>Reference</th><th>Subject</th><th>Department</th><th>Priority</th><th>Status</th><th></th></tr></thead>
            <tbody>
            {% for ticket in tickets %}
            <tr>
                <td class="reference">{{ ticket.ticket_number }}</td>
                <td>{{ ticket.subject }}</td>
                <td>{{ ticket.department }}</td>
                <td><span class="priority {{ ticket.priority|lower }}">{{ ticket.priority }}</span></td>
                <td>{{ ticket.status }}</td>
                <td><a class="table-link" href="{{ url_for('ticket_detail', ticket_id=ticket.id) }}">View →</a></td>
            </tr>
            {% endfor %}
            </tbody>
        </table></div>
        {% else %}<div class="empty-state"><h3>No active tickets</h3><p class="muted">New requests will appear here.</p></div>{% endif %}
    </section>
</main>
</body>
</html>
EOF

# Ticket details and human review.
cat > templates/ticket.html <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ ticket.ticket_number }} | Corporate Convenience</title>
<link rel="stylesheet" href="{{ url_for('static', filename='stylesheet.css') }}">
</head>
<body>
<header class="topbar"><a class="wordmark" href="{{ url_for('index') }}">Corporate Convenience</a><nav><a href="{{ url_for('index') }}">Dashboard</a><a href="{{ url_for('logout') }}">Sign out</a></nav></header>
<main class="container narrow">
    <a class="back-link" href="{{ url_for('index') }}">← Back to dashboard</a>
    <section class="panel">
        <p class="eyebrow orange">{{ ticket.ticket_number }}</p>
        <h1>{{ ticket.subject }}</h1>
        <p class="muted">Submitted by {{ ticket.employee.full_name }} · {{ ticket.department }}</p>
        <div class="ticket-description">{{ ticket.description }}</div>
        <div class="detail-grid">
            <div><span class="muted">Current priority</span><strong>{{ ticket.priority }}</strong></div>
            <div><span class="muted">Status</span><strong>{{ ticket.status }}</strong></div>
            <div><span class="muted">AI priority suggestion</span><strong>{{ ticket.ai_suggested_priority or 'Not available' }}</strong></div>
            <div><span class="muted">AI department suggestion</span><strong>{{ ticket.ai_suggested_department or 'Not available' }}</strong></div>
        </div>
        <p class="muted">{{ ticket.priority_reason }}</p>
    </section>
    {% if current_user.role != 'employee' %}
    <section class="panel">
        <h2>Review and update ticket</h2>
        <p class="muted">Changes to priority or department require a reason and are recorded.</p>
        <form method="POST">
            <label>Status</label>
            <select name="status">{% for value in ['Open','In Progress','Resolved'] %}<option {% if ticket.status == value %}selected{% endif %}>{{ value }}</option>{% endfor %}</select>
            <label>Priority</label>
            <select name="priority">{% for value in ['Low','Medium','High'] %}<option {% if ticket.priority == value %}selected{% endif %}>{{ value }}</option>{% endfor %}</select>
            <label>Department</label>
            <select name="department">{% for value in ['HR','IT','Finance','Operations'] %}<option {% if ticket.department == value %}selected{% endif %}>{{ value }}</option>{% endfor %}</select>
            <label>Reason for changes</label>
            <textarea name="reason" rows="3" placeholder="Explain any priority or department change"></textarea>
            <button class="primary">Save ticket update</button>
        </form>
    </section>
    {% endif %}
    <section class="panel">
        <h2>Ticket history</h2>
        {% for item in history %}
        <div class="history-item"><strong>{{ item.action }}</strong><p>{{ item.details }}</p><small>{{ item.created_at }}</small></div>
        {% else %}<p class="muted">No history entries yet.</p>{% endfor %}
    </section>
</main>
</body>
</html>
EOF

# Admin dashboard.
cat > templates/admin.html <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Administration | Corporate Convenience</title>
<link rel="stylesheet" href="{{ url_for('static', filename='stylesheet.css') }}">
</head>
<body>
<header class="topbar"><a class="wordmark" href="{{ url_for('index') }}">Corporate Convenience</a><nav><a href="{{ url_for('index') }}">Dashboard</a><a href="{{ url_for('archive') }}">Archive</a><a href="{{ url_for('logout') }}">Sign out</a></nav></header>
<main class="container">
    <p class="eyebrow orange">SYSTEM CONTROL</p>
    <h1>Administration</h1>
    {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}<div class="notice {{ category }}">{{ message }}</div>{% endfor %}
    {% endwith %}
    <section class="panel">
        <h2>Create an account</h2>
        <p class="muted">Only administrators can create accounts. There is no public registration.</p>
        <form method="POST" action="{{ url_for('create_account') }}" class="form-grid">
            <div><label>Employee number</label><input name="employee_number" required></div>
            <div><label>Full name</label><input name="full_name" required></div>
            <div><label>Email</label><input type="email" name="email" required></div>
            <div><label>Temporary password</label><input type="password" name="password" minlength="12" required></div>
            <div><label>Role</label><select name="role"><option value="employee">Employee</option><option value="support">Department support</option><option value="admin">Administrator</option></select></div>
            <div><label>Department</label><select name="department"><option value="">Not applicable</option><option>HR</option><option>IT</option><option>Finance</option><option>Operations</option></select></div>
            <div class="full-row"><button class="primary">Create account</button></div>
        </form>
    </section>
    <section class="panel">
        <h2>Accounts</h2>
        <div class="table-wrap"><table><thead><tr><th>Employee</th><th>Email</th><th>Role</th><th>Department</th><th>Active</th></tr></thead><tbody>
        {% for person in employees %}<tr><td>{{ person.full_name }}<br><small>{{ person.employee_number }}</small></td><td>{{ person.email }}</td><td>{{ person.role }}</td><td>{{ person.department or '—' }}</td><td>{{ 'Yes' if person.is_active else 'No' }}</td></tr>{% endfor %}
        </tbody></table></div>
    </section>
    <section class="panel">
        <h2>Recent tickets</h2>
        <div class="table-wrap"><table><thead><tr><th>Reference</th><th>Subject</th><th>Department</th><th>Status</th></tr></thead><tbody>
        {% for ticket in tickets %}<tr><td><a href="{{ url_for('ticket_detail', ticket_id=ticket.id) }}">{{ ticket.ticket_number }}</a></td><td>{{ ticket.subject }}</td><td>{{ ticket.department }}</td><td>{{ ticket.status }}</td></tr>{% endfor %}
        </tbody></table></div>
    </section>
    <section class="panel">
        <h2>Recent audit activity</h2>
        {% for log in audit_logs %}<div class="history-item"><strong>{{ log.action }}</strong><p>{{ log.details or '' }}</p><small>{{ log.created_at }}</small></div>{% else %}<p class="muted">No audit activity yet.</p>{% endfor %}
    </section>
</main>
</body>
</html>
EOF

# Archived tickets.
cat > templates/archive.html <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Archive | Corporate Convenience</title><link rel="stylesheet" href="{{ url_for('static', filename='stylesheet.css') }}"></head>
<body>
<header class="topbar"><a class="wordmark" href="{{ url_for('index') }}">Corporate Convenience</a><nav><a href="{{ url_for('admin') }}">Administration</a><a href="{{ url_for('logout') }}">Sign out</a></nav></header>
<main class="container"><p class="eyebrow orange">RECORDS</p><h1>Resolved ticket archive</h1><section class="panel">
{% if tickets %}<div class="table-wrap"><table><thead><tr><th>Reference</th><th>Subject</th><th>Department</th><th>Priority</th><th>Status</th></tr></thead><tbody>
{% for ticket in tickets %}<tr><td><a href="{{ url_for('ticket_detail', ticket_id=ticket.id) }}">{{ ticket.ticket_number }}</a></td><td>{{ ticket.subject }}</td><td>{{ ticket.department }}</td><td>{{ ticket.priority }}</td><td>{{ ticket.status }}</td></tr>{% endfor %}
</tbody></table></div>{% else %}<p class="muted">No archived tickets yet.</p>{% endif %}
</section></main></body></html>
EOF

# Error page.
cat > templates/error.html <<'EOF'
<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Notice | Corporate Convenience</title><link rel="stylesheet" href="{{ url_for('static', filename='stylesheet.css') }}"></head>
<body><main class="container narrow"><section class="panel"><p class="eyebrow orange">CORPORATE CONVENIENCE</p><h1>Something went wrong.</h1><p>{{ message }}</p><a class="primary button-link" href="{{ url_for('index') }}">Return to dashboard</a></section></main></body></html>
EOF

# Styling.
cat > static/stylesheet.css <<'EOF'
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');

:root {
  --navy: #172B45;
  --navy-deep: #101F33;
  --orange: #E47736;
  --cream: #F6F4EF;
  --white: #FFFFFF;
  --ink: #1D2938;
  --muted: #788391;
  --line: #E7E9EC;
  --green: #247A57;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--cream); color: var(--ink); font-family: 'DM Sans', sans-serif; }
h1,h2,h3 { font-family: 'Manrope', sans-serif; color: var(--navy); }
h1 { font-size: clamp(2rem,4vw,3rem); letter-spacing: -1.5px; margin: 8px 0; }
h2 { font-size: 1.25rem; margin-top: 0; }
p { line-height: 1.65; }
a { color: var(--navy); text-decoration: none; }
.topbar { min-height: 76px; background: var(--white); border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; align-items: center; padding: 14px 5vw; gap: 20px; }
.wordmark { display: flex; align-items: center; gap: 12px; font-weight: 800; font-family: 'Manrope',sans-serif; }
.topbar nav { display: flex; align-items: center; gap: 22px; flex-wrap: wrap; font-size: .9rem; }
.topbar nav a { font-weight: 600; }
.brand-mark { width: 58px; height: 58px; border-radius: 17px; display: grid; place-items: center; background: var(--orange); color: white; font: 800 1.2rem 'Manrope',sans-serif; letter-spacing: -1px; }
.small-mark { width: 36px; height: 36px; border-radius: 11px; font-size: .85rem; }
.container { max-width: 1180px; margin: 48px auto; padding: 0 28px; }
.narrow { max-width: 850px; }
.page-heading { display: flex; justify-content: space-between; margin-bottom: 30px; }
.eyebrow { font-size: .72rem; letter-spacing: 2px; font-weight: 800; color: #AAB4C0; }
.orange { color: var(--orange); }
.muted { color: var(--muted); }
.small { font-size: .82rem; }
.panel { background: white; border: 1px solid var(--line); border-radius: 17px; padding: 28px; margin: 22px 0; box-shadow: 0 8px 30px rgba(20,40,65,.035); }
.new-ticket { border-top: 4px solid var(--orange); }
label { display: block; font-weight: 700; font-size: .87rem; margin: 17px 0 8px; }
input,textarea,select { display: block; width: 100%; border: 1px solid #DDE1E6; border-radius: 9px; padding: 13px 14px; background: white; color: var(--ink); font: inherit; outline: none; }
input:focus,textarea:focus,select:focus { border-color: var(--orange); box-shadow: 0 0 0 3px rgba(228,119,54,.12); }
textarea { resize: vertical; }
.primary { display: inline-flex; justify-content: center; align-items: center; gap: 18px; border: 0; border-radius: 9px; background: var(--navy); color: white; font: 700 .92rem 'DM Sans',sans-serif; padding: 14px 20px; cursor: pointer; margin-top: 20px; }
.primary:hover { background: var(--navy-deep); }
.full { width: 100%; }
.button-link { display: inline-flex; }
.section-heading { display: flex; justify-content: space-between; align-items: center; gap: 15px; }
.count { color: var(--muted); font-size: .8rem; }
.table-wrap { width: 100%; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 650px; text-align: left; }
th { color: var(--muted); text-transform: uppercase; font-size: .7rem; letter-spacing: 1px; padding: 15px 12px; border-bottom: 1px solid var(--line); }
td { padding: 17px 12px; border-bottom: 1px solid #F0F1F3; font-size: .88rem; }
.reference { font-weight: 800; color: var(--navy); }
.table-link { color: var(--orange); font-weight: 700; }
.priority { padding: 5px 9px; border-radius: 30px; font-size: .75rem; font-weight: 700; background: #F0F1F3; }
.priority.high { background: #FCE9E5; color: #B23A2A; }
.priority.medium { background: #FFF1DD; color: #A66A16; }
.priority.low { background: #E6F3EB; color: #247A57; }
.empty-state { text-align: center; padding: 35px 10px; }
.notice { padding: 13px 16px; border-radius: 9px; margin: 14px 0; background: #E8F3ED; color: #236B4D; }
.notice.error { background: #FCE9E5; color: #A2382A; }
.ticket-description { white-space: pre-wrap; padding: 20px; background: #F8F9FA; border-radius: 10px; margin: 24px 0; line-height: 1.7; }
.detail-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 20px; margin: 24px 0; }
.detail-grid div { display: grid; gap: 6px; }
.history-item { border-bottom: 1px solid var(--line); padding: 13px 0; }
.history-item p { margin: 5px 0; }
.history-item small { color: var(--muted); }
.back-link { display: inline-block; margin-bottom: 16px; font-weight: 700; }
.form-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 18px; }
.full-row { grid-column: 1/-1; }
.login-page { min-height: 100vh; background: var(--navy-deep); display: grid; place-items: center; padding: 30px; }
.login-shell { width: min(1050px,100%); min-height: 610px; display: grid; grid-template-columns: 1fr 1fr; overflow: hidden; border-radius: 22px; background: white; box-shadow: 0 30px 90px rgba(0,0,0,.25); }
.login-brand { padding: 65px 55px; background: linear-gradient(145deg,#172B45,#203D5D); color: white; display: flex; flex-direction: column; align-items: flex-start; }
.login-brand h1 { color: white; font-size: clamp(2.6rem,5vw,4rem); line-height: 1.08; margin-top: 25px; }
.login-brand .eyebrow { margin-top: 35px; color: #E9A16F; }
.brand-copy { color: #D0D9E2; max-width: 330px; }
.brand-footer { margin-top: auto; color: #E9A16F; font-size: .85rem; }
.login-panel { display: grid; place-items: center; padding: 45px; }
.login-content { width: 100%; max-width: 370px; }
.login-content h2 { font-size: 1.8rem; margin-bottom: 5px; }
.login-content .muted { font-size: .9rem; }
.login-content form { margin-top: 30px; }
@media(max-width:760px) {
 .login-shell { grid-template-columns: 1fr; }
 .login-brand { padding: 35px; min-height: 310px; }
 .login-brand h1 { font-size: 2.5rem; }
 .brand-footer { margin-top: 25px; }
 .login-panel { padding: 35px 25px; }
 .topbar { align-items: flex-start; flex-direction: column; }
 .container { margin-top: 28px; padding: 0 16px; }
 .panel { padding: 20px; }
 .form-grid,.detail-grid { grid-template-columns: 1fr; }
}
EOF

# Small JavaScript enhancement.
cat > static/script.js <<'EOF'
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = form.querySelector('button[type="submit"], button:not([type])');
            if (button) {
                button.disabled = true;
                button.dataset.originalText = button.textContent;
                button.textContent = "Please wait...";
            }
        });
    });
});
EOF

# Add JavaScript to pages that need it.
for file in templates/login.html templates/index.html templates/admin.html templates/ticket.html templates/archive.html; do
    sed -i '' 's#</body>#<script src="{{ url_for('\''static'\'', filename='\''script.js'\'') }}"></script></body>#' "$file"
done

# README.
cat > README.md <<'EOF'
# Corporate Convenience

Internal employee concerns and ticket management platform.

## Features
- Admin-created accounts; no public registration.
- Employee, support and administrator roles.
- Department queues for HR, IT, Finance and Operations.
- Explainable baseline classification suggestions.
- Human priority and department review with recorded reasons.
- Ticket history, audit records and resolved-ticket archive.
- SMTP notification integration.

## Local setup

Activate the virtual environment:

    source .venv/bin/activate

Install dependencies:

    pip install -r requirements.txt

Create the first administrator:

    flask --app app create-admin

Run the application:

    flask --app app run --debug

Open http://127.0.0.1:5000

Configure secrets and email settings in .env.
Never commit .env or the instance database.

The initial classifier is a transparent baseline, not a trained machine-learning model.
Email delivery requires valid SMTP credentials.
EOF

# Ensure backend is importable.
cat > backend/__init__.py <<'EOF'
"""Corporate Convenience backend package."""
EOF

echo ""
echo "=========================================="
echo " REBUILD FILES CREATED"
echo "=========================================="
echo "Your .env and .venv were preserved."
echo "Next: install requirements and run checks."
