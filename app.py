import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, abort, jsonify, current_app
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_wtf.csrf import CSRFProtect

from backend.config import Config
from backend.database import (
    db, Employee, Department, Ticket, TicketMessage,
    TicketHistory, PriorityDecision, AuditLog, EmailNotification
)
from backend.classifier import classify_ticket
from backend.email_service import send_notification


def utc_now():
    return datetime.now(timezone.utc)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    csrf = CSRFProtect()
    csrf.init_app(app)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is missing. Check your .env file.")

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(Employee, int(user_id))
        except (TypeError, ValueError):
            return None

    def is_main_admin():
        return current_user.is_authenticated and current_user.role == "admin"

    def is_department_admin():
        return current_user.is_authenticated and current_user.role == "support"

    def is_employee():
        return current_user.is_authenticated and current_user.role == "employee"

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

    def can_view_ticket(ticket):
        if not current_user.is_authenticated:
            return False
        if is_main_admin():
            return True
        if is_employee():
            return ticket.employee_id == current_user.id
        if is_department_admin():
            return ticket.department == current_user.department
        return False

    def record_audit(action, entity_type=None, entity_id=None, details=None):
        entry = AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr)
        )
        db.session.add(entry)

    def add_history(ticket, action, details):
        db.session.add(TicketHistory(
            ticket_id=ticket.id,
            changed_by_id=current_user.id,
            action=action,
            details=details
        ))

    def notify(recipient, subject, body, ticket=None, notification_type="General"):
        log = EmailNotification(
            ticket_id=ticket.id if ticket else None,
            recipient=recipient,
            subject=subject,
            notification_type=notification_type,
            status="Pending"
        )
        db.session.add(log)
        db.session.flush()

        success, error = send_notification(recipient, subject, body)
        log.status = "Sent" if success else "Failed"
        log.error_message = error
        return success

    def notify_department(ticket):
        administrators = Employee.query.filter_by(
            role="support",
            department=ticket.department,
            is_active=True
        ).all()

        for administrator in administrators:
            notify(
                administrator.email,
                "New ticket assigned to " + ticket.department,
                "A new ticket has been submitted.\n\n"
                "Reference: " + ticket.ticket_number + "\n"
                "Subject: " + ticket.subject + "\n"
                "Priority: " + ticket.priority + "\n\n"
                "Please sign in to Corporate Convenience to review it.",
                ticket,
                "Department Alert"
            )

    def get_ticket_or_404(ticket_id):
        ticket = db.session.get(Ticket, ticket_id)
        if ticket is None:
            abort(404)
        if not can_view_ticket(ticket):
            abort(403)
        return ticket

    @app.route("/")
    @login_required
    def index():
        query = Ticket.query.filter_by(is_archived=False)

        if is_employee():
            query = query.filter_by(employee_id=current_user.id)
        elif is_department_admin():
            query = query.filter_by(department=current_user.department)

        tickets = query.order_by(Ticket.created_at.desc()).all()
        departments = Department.query.filter_by(is_active=True).order_by(
            Department.name
        ).all()

        return render_template(
            "index.html",
            tickets=tickets,
            departments=departments,
            is_main_admin=is_main_admin(),
            is_department_admin=is_department_admin()
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            identity = request.form.get("employee_number", "").strip()
            password = request.form.get("password", "")

            employee = Employee.query.filter(
                db.or_(
                    Employee.employee_number == identity,
                    Employee.email == identity
                )
            ).first()

            if (
                employee
                and employee.is_active
                and check_password_hash(employee.password_hash, password)
            ):
                login_user(employee)
                record_audit("User signed in", "Employee", employee.id)
                db.session.commit()
                return redirect(url_for("index"))

            flash("The sign-in details were not recognised.", "error")

        return render_template("login.html")

    @app.route("/logout", methods=["GET", "POST"])
    @login_required
    def logout():
        record_audit("User signed out", "Employee", current_user.id)
        db.session.commit()
        logout_user()
        return redirect(url_for("login"))

    @app.route("/tickets/new", methods=["POST"])
    @role_required("employee")
    def create_ticket():
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()

        if not subject or not description:
            flash("Please provide both a subject and a description.", "error")
            return redirect(url_for("index"))

        classification = classify_ticket(subject, description)
        department = classification["department"]
        priority = classification["priority"]

        ticket = Ticket(
            ticket_number="CC-" + datetime.now().strftime("%Y%m%d") + "-"
                          + secrets.token_hex(3).upper(),
            subject=subject,
            description=description,
            employee_id=current_user.id,
            department=department,
            priority=priority,
            priority_reason=classification["priority_reason"],
            ai_suggested_priority=priority,
            ai_suggested_department=department,
            status="Open"
        )

        db.session.add(ticket)
        db.session.flush()

        add_history(
            ticket,
            "Ticket submitted",
            "Initial department suggestion: " + department
            + ". Priority suggestion: " + priority
        )

        db.session.add(PriorityDecision(
            ticket_id=ticket.id,
            suggested_priority=priority,
            final_priority=priority,
            reason=classification["priority_reason"],
            decision_source="Keyword baseline"
        ))

        record_audit(
            "Ticket submitted",
            "Ticket",
            ticket.id,
            "Submitted by " + current_user.employee_number
        )

        notify(
            current_user.email,
            "We received your request: " + ticket.ticket_number,
            "Hello " + current_user.full_name + ",\n\n"
            "Your request has been received.\n"
            "Reference: " + ticket.ticket_number + "\n"
            "Subject: " + ticket.subject + "\n"
            "Suggested department: " + ticket.department + "\n"
            "Priority: " + ticket.priority + "\n\n"
            "You can sign in to Corporate Convenience to track progress.",
            ticket,
            "Employee Acknowledgement"
        )

        notify_department(ticket)
        db.session.commit()

        flash("Your ticket was submitted successfully.", "success")
        return redirect(url_for("index"))

    @app.route("/tickets/<int:ticket_id>")
    @login_required
    def ticket_detail(ticket_id):
        ticket = get_ticket_or_404(ticket_id)
        history = TicketHistory.query.filter_by(
            ticket_id=ticket.id
        ).order_by(TicketHistory.created_at.desc()).all()

        messages = TicketMessage.query.filter_by(
            ticket_id=ticket.id
        ).order_by(TicketMessage.created_at.asc()).all()

        return render_template(
            "ticket.html",
            ticket=ticket,
            history=history,
            messages=messages,
            departments=Department.query.filter_by(is_active=True).order_by(Department.name).all(),
            can_manage=(is_main_admin() or is_department_admin()),
            is_main_admin=is_main_admin()
        )

    @app.route("/tickets/<int:ticket_id>/reply", methods=["POST"])
    @login_required
    def reply_to_ticket(ticket_id):
        ticket = get_ticket_or_404(ticket_id)
        body = request.form.get("body", "").strip()

        if not body:
            flash("Please enter a message before sending.", "error")
            return redirect(url_for("ticket_detail", ticket_id=ticket.id))

        if ticket.is_archived:
            abort(403)

        message = TicketMessage(
            ticket_id=ticket.id,
            sender_id=current_user.id,
            body=body,
            is_ai_assisted=request.form.get("is_ai_assisted") == "true"
        )
        db.session.add(message)

        if current_user.id != ticket.employee_id and not ticket.first_response_at:
            ticket.first_response_at = utc_now()

        add_history(ticket, "Message sent", current_user.full_name + " sent a message.")
        record_audit("Ticket message sent", "Ticket", ticket.id)

        if current_user.id == ticket.employee_id:
            recipients = Employee.query.filter_by(
                role="support",
                department=ticket.department,
                is_active=True
            ).all()
            for recipient in recipients:
                notify(
                    recipient.email,
                    "Employee replied: " + ticket.ticket_number,
                    "The employee has added a message to ticket "
                    + ticket.ticket_number + ". Please sign in to respond.",
                    ticket,
                    "Ticket Reply"
                )
        else:
            notify(
                ticket.employee.email,
                "An update on your request: " + ticket.ticket_number,
                "Hello " + ticket.employee.full_name + ",\n\n"
                "A response has been added to your ticket "
                + ticket.ticket_number + ". Please sign in to view it.",
                ticket,
                "Employee Update"
            )

        db.session.commit()
        flash("Your message has been sent.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    @app.route("/tickets/<int:ticket_id>/draft-response", methods=["POST"])
    @role_required("admin", "support")
    def draft_response(ticket_id):
        ticket = get_ticket_or_404(ticket_id)

        if ticket.is_archived:
            abort(403)

        prompt = (
            "Draft a concise, professional and empathetic internal service "
            "desk response. Do not claim that work has been completed unless "
            "the ticket says so. Do not invent facts. The draft will be "
            "reviewed by a human before sending.\n\n"
            "Ticket subject: " + ticket.subject + "\n"
            "Ticket description: " + ticket.description + "\n"
            "Department: " + ticket.department + "\n"
            "Priority: " + ticket.priority + "\n"
            "Current status: " + ticket.status
        )

        api_key = app.config.get("GEMINI_API_KEY", "")

        if api_key:
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                draft = response.text.strip()
                return jsonify({"draft": draft, "source": "Gemini AI"})
            except Exception:
                current_app.logger.exception("AI response drafting failed.")

        draft = (
            "Hello " + ticket.employee.full_name + ",\n\n"
            "Thank you for contacting " + ticket.department + ". "
            "We have received your request regarding \"" + ticket.subject
            + "\" and are reviewing the information provided. "
            "We will share an update as soon as we have more information.\n\n"
            "Kind regards,\n" + ticket.department + " Team"
        )

        return jsonify({
            "draft": draft,
            "source": "Suggested response template",
            "notice": "AI drafting is unavailable until a valid Gemini API key is configured."
        })

    @app.route("/tickets/<int:ticket_id>/update", methods=["POST"])
    @role_required("admin", "support")
    def update_ticket(ticket_id):
        ticket = get_ticket_or_404(ticket_id)

        if ticket.is_archived:
            abort(403)

        old_status = ticket.status
        old_priority = ticket.priority
        old_department = ticket.department

        new_status = request.form.get("status", ticket.status).strip()
        new_priority = request.form.get("priority", ticket.priority).strip()
        new_department = request.form.get("department", ticket.department).strip()
        reason = request.form.get("reason", "").strip()

        valid_statuses = ["Open", "In Progress", "Awaiting Employee", "Resolved"]
        valid_priorities = ["Low", "Medium", "High"]

        if new_status not in valid_statuses or new_priority not in valid_priorities:
            flash("Invalid status or priority selection.", "error")
            return redirect(url_for("ticket_detail", ticket_id=ticket.id))

        if is_department_admin() and new_department != ticket.department:
            abort(403)

        if is_main_admin():
            department_exists = Department.query.filter_by(
                name=new_department,
                is_active=True
            ).first()
            if not department_exists:
                flash("Please select an active department.", "error")
                return redirect(url_for("ticket_detail", ticket_id=ticket.id))
        else:
            new_department = ticket.department

        changed = (
            new_status != old_status
            or new_priority != old_priority
            or new_department != old_department
        )

        if changed and not reason:
            flash("Please provide a reason for your ticket changes.", "error")
            return redirect(url_for("ticket_detail", ticket_id=ticket.id))

        if new_status != old_status:
            ticket.status = new_status
            add_history(ticket, "Status changed", old_status + " → " + new_status + ". " + reason)

            if new_status == "Resolved":
                ticket.resolved_at = utc_now()
                ticket.is_archived = True
            else:
                ticket.resolved_at = None
                ticket.is_archived = False

        if new_priority != old_priority:
            ticket.priority = new_priority
            ticket.priority_reason = reason
            db.session.add(PriorityDecision(
                ticket_id=ticket.id,
                suggested_priority=ticket.ai_suggested_priority or old_priority,
                final_priority=new_priority,
                reason=reason,
                decision_source="Administrator override" if is_main_admin()
                                 else "Department administrator"
            ))
            add_history(ticket, "Priority changed", old_priority + " → " + new_priority + ". " + reason)

        if new_department != old_department:
            ticket.department = new_department
            add_history(ticket, "Department reassigned", old_department + " → " + new_department + ". " + reason)
            notify_department(ticket)

        if new_status != old_status or new_priority != old_priority or new_department != old_department:
            record_audit("Ticket updated", "Ticket", ticket.id, reason)

        ticket.updated_at = utc_now()
        db.session.commit()

        flash("Ticket updated successfully.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket.id))

    @app.route("/archive")
    @role_required("admin", "support")
    def archive():
        query = Ticket.query.filter_by(is_archived=True)

        if is_department_admin():
            query = query.filter_by(department=current_user.department)

        tickets = query.order_by(Ticket.resolved_at.desc()).all()
        return render_template("archive.html", tickets=tickets)

    @app.route("/analytics")
    @role_required("admin", "support")
    def analytics():
        period = request.args.get("period", "month")
        today = datetime.now().date()

        if period == "quarter":
            start_date = today - timedelta(days=90)
        elif period == "year":
            start_date = today - timedelta(days=365)
        elif period == "last_month":
            first_this_month = today.replace(day=1)
            last_month_end = first_this_month - timedelta(days=1)
            start_date = last_month_end.replace(day=1)
            today = first_this_month - timedelta(days=1)
        else:
            start_date = today.replace(day=1)
            period = "month"

        query = Ticket.query
        if is_department_admin():
            query = query.filter_by(department=current_user.department)

        all_tickets = query.all()

        def within_period(ticket):
            return ticket.created_at and ticket.created_at.date() >= start_date and ticket.created_at.date() <= today

        tickets = [ticket for ticket in all_tickets if within_period(ticket)]

        total = len(tickets)
        resolved = sum(1 for ticket in tickets if ticket.status == "Resolved")
        open_count = sum(1 for ticket in tickets if not ticket.is_archived)
        overdue = sum(
            1 for ticket in tickets
            if not ticket.is_archived
            and ticket.created_at
            and (utc_now().replace(tzinfo=None) - ticket.created_at.replace(tzinfo=None)).days > 7
        )

        resolution_hours = []
        response_hours = []

        for ticket in tickets:
            if ticket.resolved_at and ticket.created_at:
                resolution_hours.append(
                    (ticket.resolved_at.replace(tzinfo=None)
                     - ticket.created_at.replace(tzinfo=None)).total_seconds() / 3600
                )
            if ticket.first_response_at and ticket.created_at:
                response_hours.append(
                    (ticket.first_response_at.replace(tzinfo=None)
                     - ticket.created_at.replace(tzinfo=None)).total_seconds() / 3600
                )

        department_stats = []
        department_names = (
            [current_user.department]
            if is_department_admin()
            else [item.name for item in Department.query.filter_by(is_active=True).all()]
        )

        for name in department_names:
            department_tickets = [ticket for ticket in tickets if ticket.department == name]
            department_stats.append({
                "name": name,
                "received": len(department_tickets),
                "resolved": sum(1 for ticket in department_tickets if ticket.status == "Resolved"),
                "backlog": sum(1 for ticket in department_tickets if not ticket.is_archived)
            })

        monthly = {}
        for ticket in tickets:
            label = ticket.created_at.strftime("%Y-%m")
            monthly[label] = monthly.get(label, 0) + 1

        priority_stats = {
            level: sum(1 for ticket in tickets if ticket.priority == level)
            for level in ["High", "Medium", "Low"]
        }

        status_stats = {}
        for ticket in tickets:
            status_stats[ticket.status] = status_stats.get(ticket.status, 0) + 1

        average_resolution = (
            round(sum(resolution_hours) / len(resolution_hours), 1)
            if resolution_hours else None
        )
        average_response = (
            round(sum(response_hours) / len(response_hours), 1)
            if response_hours else None
        )

        resolution_rate = round((resolved / total) * 100, 1) if total else 0
        high_priority = priority_stats["High"]

        return render_template(
            "analytics.html",
            period=period,
            total=total,
            resolved=resolved,
            open_count=open_count,
            overdue=overdue,
            resolution_rate=resolution_rate,
            average_resolution=average_resolution,
            average_response=average_response,
            department_stats=department_stats,
            monthly_labels=json.dumps(list(monthly.keys())),
            monthly_values=json.dumps(list(monthly.values())),
            priority_labels=json.dumps(list(priority_stats.keys())),
            priority_values=json.dumps(list(priority_stats.values())),
            status_labels=json.dumps(list(status_stats.keys())),
            status_values=json.dumps(list(status_stats.values())),
            high_priority=high_priority
        )

    @app.route("/admin")
    @role_required("admin")
    def admin():
        employees = Employee.query.order_by(Employee.created_at.desc()).all()
        recent_tickets = Ticket.query.order_by(Ticket.created_at.desc()).limit(15).all()
        audit_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(25).all()
        departments = Department.query.order_by(Department.name).all()

        return render_template(
            "admin.html",
            employees=employees,
            recent_tickets=recent_tickets,
            audit_logs=audit_logs,
            departments=departments
        )

    @app.route("/admin/accounts", methods=["POST"])
    @role_required("admin")
    def create_account():
        full_name = request.form.get("full_name", "").strip()
        employee_number = request.form.get("employee_number", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "employee").strip()
        department = request.form.get("department", "").strip()

        if not full_name or not employee_number or not email or not password:
            flash("Please complete all required account fields.", "error")
            return redirect(url_for("admin"))

        if role not in ["employee", "support", "admin"]:
            flash("Invalid account role.", "error")
            return redirect(url_for("admin"))

        if len(password) < 12:
            flash("Passwords must contain at least 12 characters.", "error")
            return redirect(url_for("admin"))

        if Employee.query.filter(
            db.or_(
                Employee.employee_number == employee_number,
                Employee.email == email
            )
        ).first():
            flash("That employee number or email address is already registered.", "error")
            return redirect(url_for("admin"))

        if role == "support":
            if not Department.query.filter_by(name=department, is_active=True).first():
                flash("Choose a valid active department for the department administrator.", "error")
                return redirect(url_for("admin"))
        else:
            department = None

        employee = Employee(
            full_name=full_name,
            employee_number=employee_number,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            department=department
        )

        db.session.add(employee)
        db.session.flush()
        record_audit("Account created", "Employee", employee.id, "Role: " + role)
        db.session.commit()

        flash("Account created successfully.", "success")
        return redirect(url_for("admin"))

    @app.route("/admin/accounts/<int:employee_id>/toggle", methods=["POST"])
    @role_required("admin")
    def toggle_account(employee_id):
        employee = db.session.get(Employee, employee_id)

        if employee is None:
            abort(404)
        if employee.id == current_user.id:
            flash("You cannot deactivate your own administrator account.", "error")
            return redirect(url_for("admin"))

        employee.is_active = not employee.is_active
        record_audit(
            "Account status changed",
            "Employee",
            employee.id,
            "Active" if employee.is_active else "Deactivated"
        )
        db.session.commit()
        flash("Account status updated.", "success")
        return redirect(url_for("admin"))

    @app.errorhandler(403)
    def forbidden(error):
        return render_template(
            "error.html",
            code=403,
            message="You do not have permission to access this page."
        ), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template(
            "error.html",
            code=404,
            message="The page or record you requested could not be found."
        ), 404

    with app.app_context():
        db.create_all()

        starter_departments = [
            ("HR", "Human Resources and employee relations"),
            ("IT", "Technical support and information technology"),
            ("Finance", "Financial administration and payments"),
            ("Operations", "Daily operations and business processes"),
            ("Facilities & Maintenance", "Buildings, facilities and maintenance"),
            ("General Administration", "General administrative services")
        ]

        for name, description in starter_departments:
            if not Department.query.filter_by(name=name).first():
                db.session.add(Department(name=name, description=description))

        db.session.commit()

    # Optional first administrator setup for Render.
    bootstrap_number = os.getenv("BOOTSTRAP_ADMIN_EMPLOYEE_NUMBER", "").strip()
    bootstrap_name = os.getenv("BOOTSTRAP_ADMIN_NAME", "").strip()
    bootstrap_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    bootstrap_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")

    if all((bootstrap_number, bootstrap_name, bootstrap_email, bootstrap_password)):
        if len(bootstrap_password) < 12:
            raise RuntimeError("Bootstrap administrator password must be at least 12 characters.")

        existing_admin = Employee.query.filter(
            db.or_(
                Employee.employee_number == bootstrap_number,
                Employee.email == bootstrap_email
            )
        ).first()

        if existing_admin is None:
            administrator = Employee(
                employee_number=bootstrap_number,
                full_name=bootstrap_name,
                email=bootstrap_email,
                password_hash=generate_password_hash(bootstrap_password),
                role="admin"
            )
            db.session.add(administrator)
            db.session.commit()
            print("Initial Render administrator created successfully.")
        else:
            print("Bootstrap administrator already exists; no duplicate created.")

    @app.cli.command("create-admin")
    def create_admin():
        import getpass

        employee_number = input("Administrator employee number: ").strip()
        full_name = input("Administrator full name: ").strip()
        email = input("Administrator email: ").strip().lower()
        password = getpass.getpass("Administrator password (minimum 12 characters): ")

        if len(password) < 12:
            print("Password must contain at least 12 characters.")
            return

        if Employee.query.filter(
            db.or_(
                Employee.employee_number == employee_number,
                Employee.email == email
            )
        ).first():
            print("An account with that employee number or email already exists.")
            return

        employee = Employee(
            employee_number=employee_number,
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            role="admin"
        )

        db.session.add(employee)
        db.session.commit()
        print("Administrator account created successfully.")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=False)
