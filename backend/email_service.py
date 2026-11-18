import smtplib
from email.message import EmailMessage
from flask import current_app


def send_notification(recipient, subject, body):
    username = current_app.config.get("MAIL_USERNAME", "")
    password = current_app.config.get("MAIL_PASSWORD", "")
    sender = current_app.config.get("MAIL_DEFAULT_SENDER", "") or username

    if not username or not password or not sender:
        return False, "Email credentials are not configured."

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        server_name = current_app.config.get("MAIL_SERVER", "smtp.gmail.com")
        server_port = current_app.config.get("MAIL_PORT", 587)
        use_tls = current_app.config.get("MAIL_USE_TLS", True)

        with smtplib.SMTP(server_name, server_port, timeout=20) as server:
            if use_tls:
                server.starttls()
            server.login(username, password)
            server.send_message(message)

        return True, None

    except Exception as error:
        current_app.logger.exception("Email delivery failed.")
        return False, str(error)
