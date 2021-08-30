"""Library for e-mailing."""

from __future__ import annotations
from configparser import ConfigParser, SectionProxy
from email.charset import Charset, QP
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from logging import getLogger
from smtplib import SMTPException, SMTP
from typing import Iterable


__all__ = ['EMail', 'Mailer']


LOGGER = getLogger('emaillib')


def send_email(smtp: SMTP, email: EMail):
    """Sends an email via the given SMTP connection."""

    try:
        smtp.send_message(email)
    except SMTPException as error:
        LOGGER.warning('Could not send email: %s', email)
        LOGGER.error(str(error))
        return False

    return True


def send_emails(smtp: SMTP, emails: Iterable[EMail]):
    """Sends emails via the given SMTP connection."""

    return all(send_email(smtp, email) for email in emails)


class MIMEQPText(MIMENonMultipart):
    """A quoted-printable encoded text."""

    def __init__(self, payload: str, subtype: str = 'plain',
                 charset: str = 'utf-8'):
        super().__init__('text', subtype, charset=charset)
        utf8qp = Charset(charset)
        utf8qp.body_encoding = QP
        self.set_payload(payload, charset=utf8qp)


class EMail(MIMEMultipart):
    """Email data for Mailer."""

    def __init__(self, subject: str, sender: str, recipient: str, *,
                 plain: str = None, html: str = None, charset: str = 'utf-8',
                 quoted_printable: bool = False):
        """Creates a new EMail."""
        super().__init__(self, subtype='alternative')
        self['Subject'] = subject
        self['From'] = sender
        self['To'] = recipient
        self['Date'] = formatdate(localtime=True, usegmt=True)
        text_type = MIMEQPText if quoted_printable else MIMEText

        if plain is not None:
            self.attach(text_type(plain, 'plain', charset))

        if html is not None:
            self.attach(text_type(html, 'html', charset))

    def __str__(self):
        """Converts the EMail to a string."""
        return self.as_string()

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

    def __init__(self, smtp_server: str, smtp_port: int, login_name: str,
                 passwd: str, *, ssl: bool = False):
        """Initializes the email with basic content."""
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.login_name = login_name
        self._passwd = passwd
        self.ssl = ssl

    def __call__(self, emails: Iterable[EMail]):
        """Alias to self.send()."""
        return self.send(emails)

    def __str__(self):
        return f'{self.login_name}:*****@{self.smtp_server}:{self.smtp_port}'

    @classmethod
    def from_section(cls, section: SectionProxy) -> Mailer:
        """Returns a new mailer instance from the provided config section."""
        smtp_server = section.get('smtp_server', section.get('host'))

        if smtp_server is None:
            raise ValueError('No SMTP server specified.')

        port = section.getint('smtp_port', fallback=section.getint('port'))

        if port is None:
            raise ValueError('No SMTP port specified.')

        login_name = section.get('login_name', section.get('user'))

        if login_name is None:
            raise ValueError('No login nane specified.')

        passwd = section.get('passwd', section.get('password'))

        if passwd is None:
            raise ValueError('No password specified.')

        ssl = section.getboolean('ssl', fallback=False)
        return cls(smtp_server, port, login_name, passwd, ssl=ssl)

    @classmethod
    def from_config(cls, config: ConfigParser) -> Mailer:
        """Returns a new mailer instance from the provided config."""
        return cls.from_section(config['email'])

    def _starttls(self, smtp: SMTP) -> bool:
        """Start TLS connection if desired."""
        if self.ssl:
            try:
                smtp.starttls()
            except (SMTPException, RuntimeError, ValueError) as error:
                LOGGER.error(str(error))
                return False

            return True

        LOGGER.warning('Connecting without SSL/TLS encryption.')
        return True

    def _handshake(self, smtp: SMTP) -> bool:
        """Perform SMTP handshake."""
        try:
            smtp.ehlo()
            smtp.login(self.login_name, self._passwd)
        except SMTPException as error:
            LOGGER.error(str(error))
            return False

        return True

    def send(self, emails: Iterable[EMail]) -> bool:
        """Sends emails."""
        with SMTP(host=self.smtp_server, port=self.smtp_port) as smtp:
            if not self._starttls(smtp) or not self._handshake(smtp):
                return False

            return send_emails(smtp, emails)
