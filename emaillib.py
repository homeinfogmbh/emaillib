"""Library for e-mailing."""

from email.charset import Charset, QP
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from logging import CRITICAL, ERROR, WARNING, getLogger
from smtplib import SMTPException, SMTP
from ssl import SSLError
from threading import Thread

from timelib import rfc_2822


__all__ = [
    'MailerError',
    'load_admins',
    'Mailer',
    'EMail',
    'ErrMail',
    'IssuerSnapshot',
    'AdminMailer']


class MailerError(Exception):
    """Indicates errors during sending mails."""

    def __init__(self, exceptions):
        super().__init__(str(exceptions))
        self.exceptions = exceptions


def load_admins(admins_string, wants_stacktrace=True):
    """Yields admin data from configuration file string.

    admins_string = <admin>[,<admin>...]
    admin = <email>[:<name>[:<wants_stacktrace>]]
    """

    for admin in admins_string.split(','):
        admin_fields = admin.split(':')

        try:
            email, name, stacktrace_flag = admin_fields
        except ValueError:
            try:
                email, name = admin_fields
            except ValueError:
                email = admin
                name = 'Administrator'
        else:
            if stacktrace_flag.strip().lower() in ('yes', 'y', 'true', '1'):
                wants_stacktrace = True
            elif stacktrace_flag.strip().lower() in ('no', 'n', 'false', '0'):
                wants_stacktrace = False

        yield (email, name, wants_stacktrace)


class MIMEQPText(MIMENonMultipart):
    """A quoted-printable encoded text."""

    def __init__(self, payload, subtype='plain', charset='utf-8'):
        super().__init__('text', subtype, charset=charset)
        utf8qp = Charset(charset)
        utf8qp.body_encoding = QP
        self.set_payload(payload, charset=utf8qp)


class EMail(MIMEMultipart):
    """Email data for Mailer."""

    def __init__(self, subject, sender, recipient, plain=None, html=None,
                 charset='utf-8', quoted_printable=False):
        """Creates a new EMail."""
        super().__init__(self, subtype='alternative')
        self['Subject'] = subject
        self['From'] = sender
        self['To'] = recipient
        self['Date'] = rfc_2822()
        self.charset = charset
        self.quoted_printable = quoted_printable
        # Set bodies after setting charset and quoted_printable.
        if plain is not None:
            self.add_plain(plain)

        if html is not None:
            self.add_html(html)

    def __str__(self):
        """Converts the EMail to a string."""
        return self.as_string()

    def add_plain(self, plain):
        """Adds a plain text body."""
        if self.quoted_printable:
            attachment = MIMEQPText(plain, 'plain', self.charset)
        else:
            attachment = MIMEText(plain, 'plain', self.charset)

        self.attach(attachment)

    def add_html(self, html):
        """Add an HTML body."""
        if self.quoted_printable:
            attachment = MIMEQPText(html, 'html', self.charset)
        else:
            attachment = MIMEText(html, 'html', self.charset)

        self.attach(attachment)

    @property
    def subject(self):
        """Returns the Email's subject."""
        return self['Subject']

    @property
    def sender(self):
        """Returns the Email's sender."""
        return self['From']

    @property
    def recipient(self):
        """Returns the Email's recipient."""
        return self['To']


class Mailer:
    """A simple SMTP mailer."""

    def __init__(self, smtp_server, smtp_port, login_name, passwd,
                 ssl=None, logger=None):
        """Initializes the email with basic content."""
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.login_name = login_name
        self._passwd = passwd
        self.ssl = ssl

        if logger is None:
            self.logger = getLogger(self.__class__.__name__)
        else:
            self.logger = logger.getChild(self.__class__.__name__)

    def __call__(self, emails):
        """Alias to self.send()."""
        return self.send(emails)

    def __str__(self):
        return '{}:*****@{}:{}'.format(
            self.login_name, self.smtp_server, self.smtp_port)

    @classmethod
    def from_config(cls, config, logger=None):
        """Returns a new mailer instance from the provided configuration."""
        smtp_server = config.get('smtp_server', config.get('host'))

        if smtp_server is None:
            raise ValueError('No SMTP server specified.')

        smtp_port = int(config.get('smtp_port', config.get('port')))

        if smtp_port is None:
            raise ValueError('No SMTP port specified.')

        login_name = config.get('login_name', config.get('user'))

        if login_name is None:
            raise ValueError('No login nane specified.')

        passwd = config.get('passwd', config.get('password'))

        if passwd is None:
            raise ValueError('No password specified.')

        ssl = config.getboolean('ssl', False)
        return cls(smtp_server, smtp_port, login_name, passwd, ssl=ssl,
                   logger=logger)

    def send(self, emails, background=True):
        """Sends email in a sub thread to not block the system."""
        if background:
            sending = Thread(target=self._send, args=[emails])
            sending.start()
            return sending

        return self._send(emails)

    def _send(self, emails):
        """Sends emails."""
        result = True
        print('DEBUG:', self.smtp_server, self.login_name, self._passwd,
              self.smtp_port, flush=True)

        with SMTP(host=self.smtp_server, port=self.smtp_port) as smtp:
            if self.ssl is None or self.ssl:
                try:
                    smtp.starttls()
                except (SSLError, SMTPException):
                    if self.ssl:
                        raise

                    self.logger.warning(
                        'Connecting without SSL/TLS encryption.')

            #smtp.ehlo()
            smtp.login(self.login_name, self._passwd)

            # Actually send emails.
            for email in emails:
                try:
                    smtp.send_message(email)
                except Exception as exception:
                    result = False
                    self.logger.error('Caught exception: %s.', exception)

            smtp.quit()

        return result


class ErrMail:
    """Error mail factory."""

    ERRLVLS = {
        WARNING: 'WARNING',
        ERROR: 'ERROR',
        CRITICAL: 'CRITICAL ERROR'}
    SUBJECT_TEMPLATE = '{application}: {error} in {issuer}'
    BODY_TEMPLATE = (
        'Dear {name},\n\n'
        '{application} has encountered the following {error}:\n\n'
        'Issuer:   {issuer}\n'
        '{info}\n'
        'Message:  {message}\n')

    def __init__(self, application, sender, subject_template=None,
                 body_template=None, html=False, charset='utf-8'):
        """Generate mail."""
        self.application = application
        self.sender = sender
        self._subject_template = subject_template
        self._body_template = body_template
        self.html = html
        self.charset = charset

    def __call__(self, admin, issuer, message, errlvl, stacktrace=None):
        """Returns the appropriate email object."""
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
        """Returns the subject template."""
        if self._subject_template is None:
            return self.SUBJECT_TEMPLATE

        return self._subject_template

    @subject_template.setter
    def subject_template(self, subject_template):
        """Sets the subject template."""
        self._subject_template = subject_template

    @property
    def body_template(self):
        """Returns the body template."""
        if self._body_template is None:
            return self.BODY_TEMPLATE

        return self._body_template

    @body_template.setter
    def body_template(self, body_template):
        """Sets the body template."""
        self._body_template = body_template

    @property
    def plain(self):
        """Determines whether the body is plain text."""
        return not self.html

    @plain.setter
    def plain(self, plain):
        """Sets flag for plain text body."""
        self.html = not plain


class IssuerSnapshot:
    """Wrapper for issuers to snapshot volatile data."""

    def __init__(self, issuer):
        """Snapshots volatile data."""
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


class AdminMailer:
    """A mailer wrapper to easily send emails to admins."""

    def __init__(self, issuer, admins, mailer, err_mail):
        """Initializes the admin mailer with an issuer."""
        self.issuer = issuer
        self.admins = admins
        self.mailer = mailer
        self.err_mail = err_mail
        self.issuer_snapshot = IssuerSnapshot(issuer)

    def mails(self, message, errlvl, stacktrace):
        """Generate admin emails."""
        for admin in self.admins:
            yield self.err_mail(
                admin, self.issuer_snapshot, message, errlvl,
                stacktrace=stacktrace)

    def send(self, message, errlvl, stacktrace=None):
        """Send emails to administrators."""
        self.issuer_snapshot = IssuerSnapshot(self.issuer)
        self.mailer.send(self.mails(message, errlvl, stacktrace))
