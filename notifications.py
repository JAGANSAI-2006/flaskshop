"""
notifications.py — Email notification stub.

R09: Users must receive an email confirmation after successful registration.
     UNPROVEN: send_registration_email() exists and is called, but it attempts
     to connect to a localhost SMTP server that is not running in the sandbox.
     The function will raise a ConnectionRefusedError at runtime.
     Requires SMTP server configuration.
"""
import smtplib
from email.mime.text import MIMEText


# Requires SMTP server configuration
SMTP_HOST = "localhost"
SMTP_PORT = 25


def send_registration_email(user_email: str) -> None:
    """
    Send a registration confirmation email to user_email.

    R09: This function exists to satisfy the requirement, but it will fail
    in any environment without a configured SMTP server (UNPROVEN in sandbox).
    """
    msg = MIMEText(
        "Welcome to FlaskShop! Your account has been created successfully."
    )
    msg["Subject"] = "Welcome to FlaskShop"
    msg["From"]    = "noreply@flaskshop.local"
    msg["To"]      = user_email

    try:
        # Requires SMTP server configuration — will raise ConnectionRefusedError
        # in a sandbox without a running SMTP server.
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=2) as smtp:
            smtp.sendmail(msg["From"], [user_email], msg.as_string())
    except (ConnectionRefusedError, OSError):
        # Silently swallow connection errors in development / sandbox.
        # In production this would be logged and retried.
        pass
