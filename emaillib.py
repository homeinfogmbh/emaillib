"""Library for e-mailing."""

from __future__ import annotations
from configparser import ConfigParser, SectionProxy
from email.charset import Charset, QP
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from functools import cache
from logging import getLogger
from smtplib import SMTPException, SMTP
from typing import Iterable, Optional
from warnings import warn


__all__ = ['EMail', 'Mailer']


LOGGER = getLogger('emaillib')


class MIMEQPText(MIMENonMultipart):
    """A quoted-printable encoded text."""

    def __init__(self, payload: str, subtype: str = 'plain',
                 charset: str = 'utf-8'):
        super().__init__('text', subtype, charset=charset)
        self.set_payload(payload, charset=get_qp_charset(charset))


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

    def __init__(
            self,
            smtp_server: str,
            smtp_port: int,
            login_name: str,
            passwd: str,
            *,
            ssl: Optional[bool] = None,
            tls: Optional[bool] = None
    ):
        """Initializes the email with basic content."""
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.login_name = login_name
        self._passwd = passwd

        if ssl is not None:
            warn('Option "ssl" is deprecated. Use "tls" instead.',
                 DeprecationWarning)

        self.ssl = ssl
        self.tls = tls

    def __call__(self, emails: Iterable[EMail]):
        """Alias to self.send()."""
        return self.send(emails)

    def __str__(self):
        return f'{self.login_name}:*****@{self.smtp_server}:{self.smtp_port}'

    @classmethod
    def from_section(cls, section: SectionProxy) -> Mailer:
        """Returns a new mailer instance from the provided config section."""

        if (smtp_server := section.get(
                'smtp_server', section.get('host')
        )) is None:
            raise ValueError('No SMTP server specified.')

        if (port := section.getint(
                'smtp_port', section.getint('port')
        )) is None:
            raise ValueError('No SMTP port specified.')

        if (login_name := section.get(
                'login_name', section.get('user')
        )) is None:
            raise ValueError('No login nane specified.')

        if (passwd := section.get('passwd', section.get('password'))) is None:
            raise ValueError('No password specified.')

        return cls(
            smtp_server, port, login_name, passwd,
            ssl=section.getboolean('ssl'), tls=section.getboolean('tls')
        )

    @classmethod
    def from_config(cls, config: ConfigParser) -> Mailer:
        """Returns a new mailer instance from the provided config."""
        return cls.from_section(config['email'])

    def _start_tls(self, smtp: SMTP) -> bool:
        """Start TLS connection."""
        try:
            smtp.starttls()
        except (SMTPException, RuntimeError, ValueError) as error:
            LOGGER.error('Error during STARTTLS: %s', error)

            # If TLS was explicitly requested, re-raise
            # the exception and fail.
            if self.ssl or self.tls:
                raise

            # If TLS was not explicitly requested, return False
            # to make the caller issue a warning.
            return False

        return True

    def _start_tls_if_requested(self, smtp: SMTP) -> bool:
        """Start a TLS connection if requested."""
        if self.ssl or self.tls or self.ssl is None or self.tls is None:
            return self._start_tls(smtp)

        return False

    def _login(self, smtp: SMTP) -> bool:
        """Attempt to log in at the server."""
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
            if not self._start_tls_if_requested(smtp):
                LOGGER.warning('Connecting without SSL/TLS encryption.')

            if not self._login(smtp):
                return False

            return send_emails(smtp, emails)


def send_email(smtp: SMTP, email: EMail) -> bool:
    """Sends an email via the given SMTP connection."""

    try:
        smtp.send_message(email)
    except SMTPException as error:
        LOGGER.warning('Could not send email: %s', email)
        LOGGER.error(str(error))
        return False

    return True


def send_emails(smtp: SMTP, emails: Iterable[EMail]) -> bool:
    """Sends emails via the given SMTP connection."""

    return all({send_email(smtp, email) for email in emails})


@cache
def get_qp_charset(charset: str) -> Charset:
    """Returns a quoted printable charset."""

    qp_charset = Charset(charset)
    qp_charset.body_encoding = QP
    return qp_charset
