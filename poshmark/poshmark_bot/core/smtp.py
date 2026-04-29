import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from ..config import _STARTTLS_ONLY, _SSL_ONLY
from ..utils.helpers import get_smtp_server

class SMTPMailSender:
    def __init__(self, email: str, password: str):
        self.email    = email
        self.password = password
        self.server   = get_smtp_server(email)

    def _make_msg(self, to_email, subject, html_content, sender_name):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((sender_name.strip(), self.email)) if sender_name else self.email
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html", "utf-8"))
        return msg

    def _try_ssl(self, msg) -> tuple:
        try:
            with smtplib.SMTP_SSL(self.server, 465, timeout=30) as srv:
                srv.ehlo()
                srv.login(self.email, self.password)
                srv.send_message(msg)
            return True, f"OK (SSL/465 via {self.server})"
        except smtplib.SMTPAuthenticationError as e:
            return None, f"Авторизация SSL/465: {e}"
        except Exception as e:
            return False, f"SSL/465 {type(e).__name__}: {e}"

    def _try_starttls(self, msg) -> tuple:
        try:
            with smtplib.SMTP(self.server, 587, timeout=30) as srv:
                srv.ehlo()
                srv.starttls()
                srv.ehlo()
                srv.login(self.email, self.password)
                srv.send_message(msg)
            return True, f"OK (STARTTLS/587 via {self.server})"
        except smtplib.SMTPAuthenticationError as e:
            return None, f"Авторизация STARTTLS/587: {e}"
        except Exception as e:
            return False, f"STARTTLS/587 {type(e).__name__}: {e}"

    def send_email(self, to_email: str, subject: str,
                   html_content: str, sender_name: str = "") -> tuple:
        msg = self._make_msg(to_email, subject, html_content, sender_name)
        errors = []

        if self.server in _STARTTLS_ONLY:
            ok, info = self._try_starttls(msg)
            if ok is True: return True, info
            return False, info

        if self.server in _SSL_ONLY:
            ok, info = self._try_ssl(msg)
            if ok is True: return True, info
            return False, info

        ok, info = self._try_ssl(msg)
        if ok is True: return True, info
        if ok is None: return False, info
        errors.append(info)

        ok, info = self._try_starttls(msg)
        if ok is True: return True, info
        if ok is None: return False, info
        errors.append(info)

        return False, " | ".join(errors)

    @staticmethod
    def test(email: str, password: str) -> tuple:
        server = get_smtp_server(email)
        errors = []

        if server in _STARTTLS_ONLY:
            try:
                with smtplib.SMTP(server, 587, timeout=15) as srv:
                    srv.ehlo(); srv.starttls(); srv.ehlo()
                    srv.login(email, password)
                return True, f"STARTTLS/587 via {server} — OK"
            except smtplib.SMTPAuthenticationError as e:
                return False, f"STARTTLS/587 — неверный логин/пароль ({e})"
            except Exception as e:
                return False, f"STARTTLS/587: {type(e).__name__}: {e}"

        if server in _SSL_ONLY:
            try:
                with smtplib.SMTP_SSL(server, 465, timeout=15) as srv:
                    srv.ehlo(); srv.login(email, password)
                return True, f"SSL/465 via {server} — OK"
            except smtplib.SMTPAuthenticationError as e:
                return False, f"SSL/465 — неверный логин/пароль ({e})"
            except Exception as e:
                return False, f"SSL/465: {type(e).__name__}: {e}"

        try:
            with smtplib.SMTP_SSL(server, 465, timeout=15) as srv:
                srv.ehlo(); srv.login(email, password)
            return True, f"SSL/465 via {server} — OK"
        except smtplib.SMTPAuthenticationError as e:
            return False, f"SSL/465 — неверный логин/пароль ({e})"
        except Exception as e:
            errors.append(f"SSL/465: {type(e).__name__}: {e}")

        try:
            with smtplib.SMTP(server, 587, timeout=15) as srv:
                srv.ehlo(); srv.starttls(); srv.ehlo()
                srv.login(email, password)
            return True, f"STARTTLS/587 via {server} — OK"
        except smtplib.SMTPAuthenticationError as e:
            return False, f"STARTTLS/587 — неверный логин/пароль ({e})"
        except Exception as e:
            errors.append(f"STARTTLS/587: {type(e).__name__}: {e}")

        return False, "Оба метода не сработали: " + " | ".join(errors)
