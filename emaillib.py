"""Library for e-mailing."""

from threading import Thread
from smtplib import SMTPException, SMTP
from email.charset import Charset
from email.charset import QP
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from ssl import SSLError

from timelib import rfc_2822
from fancylog import Logger, LogLevel

__all__ = [
    'MailerError',
    'Mailer',
    'EMail',
    'ErrMail',
    'IssuerSnapshot',
    'AdminMailer']


class MailerError(Exception):
    """Indicates errors during sending mails"""

    def __init__(self, exceptions):
        super().__init__(str(exceptions))
        self.exceptions = exceptions


class MIMEQPText(MIMENonMultipart):
    """A quoted-printable encoded text"""

    def __init__(self, payload, subtype='plain', charset='utf-8'):
        super().__init__('text', subtype, charset=charset)
        utf8qp = Charset(charset)
        utf8qp.body_encoding = QP
        self.set_payload(payload, charset=utf8qp)


class EMail(MIMEMultipart):
    """Email data for Mailer"""

    def __init__(self, subject, sender, recipient, plain=None, html=None,
                 charset='utf-8', qp=False):
        """Creates a new EMail"""
        super().__init__(self, subtype='alternative')
        self['Subject'] = subject
        self['From'] = sender
        self['To'] = recipient
        self['Date'] = rfc_2822()

        # Set bodies
        if plain is not None:
            if qp:
                attachment = MIMEQPText(plain, 'plain', charset)
            else:
                attachment = MIMEText(plain, 'plain', charset)

            self.attach(attachment)

        if html is not None:
            if qp:
                attachment = MIMEQPText(html, 'html', charset)
            else:
                attachment = MIMEText(html, 'html', charset)

            self.attach(attachment)

    def __str__(self):
        """Converts the EMail to a string"""
        return self.as_string()

    @property
    def subject(self):
        """Returns the Email's subject"""
        self['Subject']

    @property
    def sender(self):
        """Returns the Email's sender"""
        return self['From']

    @property
    def recipient(self):
        """Returns the Email's recipient"""
        return self['To']


class Mailer():
    """A simple SMTP mailer"""

    def __init__(self, smtp_server, smtp_port, login_name, passwd,
                 ssl=None, logger=None):
        """Initializes the email with basic content"""
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.login_name = login_name
        self._passwd = passwd
        self.ssl = ssl

        if logger is None:
            self.logger = Logger(self.__class__.__name__)
        else:
            self.logger = logger.inherit(self.__class__.__name__)

    def __call__(self, emails):
        """Alias to self.send()"""
        return self.send(emails)

    def __str__(self):
        return '{}:*****@{}:{}'.format(
            self.login_name, self.smtp_server, self._smtp_port)

    def send(self, emails, fg=False):
        """Sends email in a sub thread to not block the system"""
        if fg:
            return self._send(emails)
        else:
            sending = Thread(target=self._send, args=[emails])
            sending.start()

    def _send(self, emails):
        """Sends email"""
        failures = []

        with SMTP(self.smtp_server, self.smtp_port) as smtp:
            if self.ssl is not False:
                try:
                    smtp.starttls()
                except (SSLError, SMTPException):
                    if self.ssl is True:
                        raise
                    else:
                        self.logger.warning(
                            'Connecting without SSL/TLS encryption')

            smtp.ehlo()
            smtp.login(self.login_name, self._passwd)

            # Actually send emails
            for email in emails:
                try:
                    smtp.send_message(email)
                except Exception as e:
                    failures.append((email, e))

            smtp.quit()

        for email, exception in failures:
            self.logger.error('Could not send: {}\nReason: {}'.format(
                email, exception))

        return not failures


class ErrMail():
    """Error mail factory"""

    ERRLVLS = {
        LogLevel.WARNING: 'WARNING',
        LogLevel.ERROR: 'ERROR',
        LogLevel.CRITICAL: 'CRITICAL ERROR'}
    SUBJECT_TEMPLATE = '{application}: {error} in {issuer}'
    BODY_TEMPLATE = (
        'Dear {name},\n\n'
        '{application} has encountered the following {error}:\n\n'
        'Issuer:   {issuer}\n'
        '{info}\n'
        'Message:  {message}\n')

    def __init__(self, application, sender, subject_template=None,
                 body_template=None, html=False, charset='utf-8'):
        """Generate mail"""
        self.application = application
        self.sender = sender
        self.subject_template = subject_template
        self.body_template = body_template
        self.html = html
        self.charset = charset

    def __call__(self, admin, issuer, message, errlvl, stacktrace=None):
        """Returns the appropriate email object"""
        email, admin_name, wants_stacktrace = admin
        error = self.ERRLVLS.get(errlvl, 'UNKNOWN ERROR LEVEL')
        subject = self.subject_template.format(
            application=self.application, error=error, issuer=issuer.name)
        body = self.body_template.format(
            name=admin_name, application=self.application, error=error,
            issuer=issuer.name, info=issuer.info, message=message)

        if stacktrace is not None and wants_stacktrace:
            body = '\n'.join((body, stacktrace))

        return EMail(
            subject, self.sender, email,
            plain=body if self.plain else None,
            html=body if self.html else None,
            charset=self.charset)

    @property
    def subject_template(self):
        """Returns the subject template"""
        if self._subject_template is None:
            return self.SUBJECT_TEMPLATE
        else:
            return self._subject_template

    @subject_template.setter
    def subject_template(self, subject_template):
        """Sets the subject template"""
        self._subject_template = subject_template

    @property
    def body_template(self):
        """Returns the body template"""
        if self._body_template is None:
            return self.BODY_TEMPLATE
        else:
            return self._body_template

    @body_template.setter
    def body_template(self, body_template):
        """Sets the body template"""
        self._body_template = body_template

    @property
    def html(self):
        """Determines whether the body is HTML"""
        return self._html

    @html.setter
    def html(self, html):
        """Sets flag for HTML body"""
        self._html = html

    @property
    def plain(self):
        """Determines whether the body is plain text"""
        return not self._html

    @plain.setter
    def plain(self, plain):
        """Sets flag for plain text body"""
        self._html = not plain


class IssuerSnapshot():
    """Wrapper for issuers to snapshot volatile data"""

    def __init__(self, issuer):
        """Snapshots volatile data"""
        self.issuer = issuer
        self.str = str(issuer)
        self.repr = repr(issuer)
        self.name = str(issuer.name)

        try:
            self.info = issuer.info()
        except AttributeError:
            self.info = ''
        except Exception:
            self.info = 'ERROR: Could not determine issuer info.'

    def __str__(self):
        return self.str

    def __repr__(self):
        return self.repr


class AdminMailer():
    """A mailer wrapper to easily send emails to admins"""

    def __init__(self, issuer, admins, mailer, err_mail):
        """Initializes the admin mailer with an issuer"""
        self.issuer = issuer
        self.admins = list(admins)
        self.mailer = mailer
        self.err_mail = err_mail
        self.issuer_snapshot = IssuerSnapshot(issuer)

    def mails(self, message, errlvl, stacktrace):
        """Generate admin emails"""
        for admin in self.admins:
            yield self.err_mail(
                admin, self.issuer_snapshot, message, errlvl,
                stacktrace=stacktrace)

    def send(self, message, errlvl, stacktrace=None):
        """Send emails to administrators"""
        self.issuer_snapshot = IssuerSnapshot(self.issuer)
        self.mailer.send(self.mails(message, errlvl, stacktrace))
