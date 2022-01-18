"""Library for e-mailing."""

from __future__ import annotations
from configparser import ConfigParser, SectionProxy
from dataclasses import dataclass
from email.charset import Charset, QP
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from functools import cache
from logging import getLogger
from smtplib import SMTPException, SMTP
from typing import Iterable, Iterator, Optional
from warnings import warn


__all__ = ['EMailsNotSent', 'EMail', 'Mailer', 'email_template']


LOGGER = getLogger('emaillib')


class MIMEQPText(MIMENonMultipart):
    """A quoted-printable encoded text."""

    def __init__(self, payload: str, subtype: str = 'plain',
                 charset: str = 'utf-8'):
        super().__init__('text', subtype, charset=charset)
        self.set_payload(payload, charset=get_qp_charset(charset))


@dataclass
class EMail:
    """Email data for Mailer."""

    subject: str
    sender: str
    recipient: str
    plain: Optional[str] = None
    html: Optional[str] = None
    charset: str = 'utf-8'
    quoted_printable: bool = False

    def to_mime_multipart(self) -> MIMEMultipart:
        """Returns a MIMEMultipart object for sending."""
        mime_multipart = MIMEMultipart(subtype='alternative')
        mime_multipart['Subject'] = self.subject
        mime_multipart['From'] = self.sender
        mime_multipart['To'] = self.recipient
        mime_multipart['Date'] = formatdate(localtime=True, usegmt=True)
        text_type = MIMEQPText if self.quoted_printable else MIMEText

        if self.plain is not None:
            mime_multipart.attach(text_type(self.plain, 'plain', self.charset))

        if self.html is not None:
            mime_multipart.attach(text_type(self.html, 'html', self.charset))

        return mime_multipart


class EMailsNotSent(Exception):
    """Indicates that some emails could not be sent."""

    def __init__(self, emails: Iterable[EMail]):
        super().__init__('E-Mails not sent:', emails)
        self.emails = emails


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

    def _login(self, smtp: SMTP) -> None:
        """Attempt to log in at the server."""
        try:
            smtp.ehlo()
        except SMTPException as error:
            LOGGER.error('Error during EHLO: %s', error)
            raise

        try:
            smtp.login(self.login_name, self._passwd)
        except SMTPException as error:
            LOGGER.error('Error during login: %s', error)
            raise

    def send(self, emails: Iterable[EMail]) -> None:
        """Sends emails."""
        with SMTP(host=self.smtp_server, port=self.smtp_port) as smtp:
            if not self._start_tls_if_requested(smtp):
                LOGGER.warning('Connecting without SSL/TLS encryption.')

            self._login(smtp)
            send_emails(smtp, emails)


def send_email(smtp: SMTP, email: EMail) -> bool:
    """Sends an email via the given SMTP connection."""

    try:
        smtp.send_message(email.to_mime_multipart())
    except SMTPException as error:
        LOGGER.warning('Could not send email: %s', email)
        LOGGER.error(str(error))
        return False

    return True


def send_emails(smtp: SMTP, emails: Iterable[EMail]) -> None:
    """Sends emails via the given SMTP connection."""

    not_sent = []

    for email in emails:
        if not send_email(smtp, email):
            not_sent.append(email)

    if not_sent:
        raise EMailsNotSent(not_sent)


@cache
def get_qp_charset(charset: str) -> Charset:
    """Returns a quoted printable charset."""

    qp_charset = Charset(charset)
    qp_charset.body_encoding = QP
    return qp_charset


def email_template(
        subject: str,
        sender: str,
        *,
        plain: str = None,
        html: str = None,
        charset: str = 'utf-8',
        quoted_printable: bool = False
):
    """Generate a closure for an email template."""

    def generate_emails(recipients: Iterable[str]) -> Iterator[EMail]:
        """Yield generated emails."""

        for recipient in recipients:
            yield EMail(
                subject, sender, recipient, plain=plain, html=html,
                charset=charset, quoted_printable=quoted_printable
            )

    return generate_emails
