import smtplib
from email.mime.text import MIMEText

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel,
    QMessageBox, QHBoxLayout,
)

from config import load_config, save_config


def build_report_text(name: str, start_time_str: str, duration_str: str, summary: dict) -> str:
    """
    Formatirani tekstualni sazetak po uzoru na dashboard ekran.
    `summary` ocekuje kljuceve: power, cadence, hr, balance_l, balance_r,
    seated_pct, standing_pct (bilo koji moze biti None ako nije dostupno).
    """
    def fmt(value, unit=""):
        return f"{value:.0f}{unit}" if value is not None else "--"

    lines = [
        "CYCLING DYNAMICS - SESSION REPORT",
        "=" * 34,
        f"Analyzed: {name or '(not specified)'}",
        f"Started:  {start_time_str}",
        f"Duration: {duration_str}",
        "",
        "-- Averages --",
        f"Power:          {fmt(summary.get('power'), ' W')}",
        f"Cadence:        {fmt(summary.get('cadence'), ' rpm')}",
        f"Heart rate:     {fmt(summary.get('hr'), ' bpm')}",
    ]

    bl, br = summary.get("balance_l"), summary.get("balance_r")
    if bl is not None and br is not None:
        lines.append(f"Power balance:  {bl:.0f}% / {br:.0f}%")
    else:
        lines.append("Power balance:  -- (not available from this power source)")

    seated_pct, standing_pct = summary.get("seated_pct"), summary.get("standing_pct")
    if seated_pct is not None:
        lines.append(f"Seated/standing: {seated_pct:.0f}% / {standing_pct:.0f}%")
    else:
        lines.append("Seated/standing: -- (not available from this power source)")

    return "\n".join(lines)


class ReportDialog(QDialog):
    def __init__(self, start_time_str: str, duration_str: str, summary: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Send report")
        self.setMinimumWidth(360)
        self.summary = summary
        self.start_time_str = start_time_str
        self.duration_str = duration_str

        cfg = load_config()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_input = QLineEdit()
        form.addRow("Analyzed (name):", self.name_input)

        form.addRow("Started:", QLabel(start_time_str))
        form.addRow("Duration:", QLabel(duration_str))

        self.recipient_input = QLineEdit(cfg.get("recipient_email", ""))
        form.addRow("Send to:", self.recipient_input)

        layout.addLayout(form)

        # sender setup - prikazano samo ako jos nije konfigurirano
        self.sender_form = QFormLayout()
        self.needs_sender_setup = not cfg.get("sender_email") or not cfg.get("sender_app_password")
        if self.needs_sender_setup:
            layout.addWidget(QLabel("One-time email setup (saved locally, not synced to GitHub):"))
            self.sender_email_input = QLineEdit(cfg.get("sender_email", ""))
            self.sender_password_input = QLineEdit(cfg.get("sender_app_password", ""))
            self.sender_password_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.smtp_host_input = QLineEdit(cfg.get("smtp_host", "smtp.gmail.com"))
            self.smtp_port_input = QLineEdit(str(cfg.get("smtp_port", 587)))
            self.sender_form.addRow("From (email):", self.sender_email_input)
            self.sender_form.addRow("App password:", self.sender_password_input)
            self.sender_form.addRow("SMTP server:", self.smtp_host_input)
            self.sender_form.addRow("SMTP port:", self.smtp_port_input)
            layout.addLayout(self.sender_form)

        button_row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._on_send)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.send_button)
        layout.addLayout(button_row)

    def _on_send(self):
        recipient = self.recipient_input.text().strip()
        if not recipient:
            QMessageBox.warning(self, "Missing recipient", "Enter a recipient email address.")
            return

        if self.needs_sender_setup:
            sender_email = self.sender_email_input.text().strip()
            sender_password = self.sender_password_input.text().strip()
            smtp_host = self.smtp_host_input.text().strip() or "smtp.gmail.com"
            try:
                smtp_port = int(self.smtp_port_input.text().strip() or "587")
            except ValueError:
                smtp_port = 587
            if not sender_email or not sender_password:
                QMessageBox.warning(self, "Missing sender info", "Fill in the From email and app password.")
                return
        else:
            cfg = load_config()
            sender_email = cfg["sender_email"]
            sender_password = cfg["sender_app_password"]
            smtp_host = cfg.get("smtp_host", "smtp.gmail.com")
            smtp_port = cfg.get("smtp_port", 587)

        body = build_report_text(self.name_input.text().strip(), self.start_time_str, self.duration_str, self.summary)
        msg = MIMEText(body)
        msg["Subject"] = f"Cycling Dynamics report - {self.name_input.text().strip() or 'session'}"
        msg["From"] = sender_email
        msg["To"] = recipient

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg)
        except Exception as e:
            QMessageBox.critical(self, "Send failed", f"Could not send email:\n{type(e).__name__}: {e}")
            return

        # spremi kao defaulte za sljedeci put
        save_config({
            "recipient_email": recipient,
            "sender_email": sender_email,
            "sender_app_password": sender_password,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
        })

        QMessageBox.information(self, "Sent", "Report sent.")
        self.accept()
