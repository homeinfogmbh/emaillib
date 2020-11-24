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
from threading import Thread
from typing import Iterable


__all__ = ['EMail', 'Mailer']


LOGGER = getLogger('emaillib')


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

    def add_plain(self, plain: str):
        """Adds a plain text body."""
        if self.quoted_printable:
            attachment = MIMEQPText(plain, 'plain', self.charset)
        else:
            attachment = MIMEText(plain, 'plain', self.charset)

        self.attach(attachment)

    def add_html(self, html: str):
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

    def __init__(self, smtp_server: str, smtp_port: int, login_name: str,
                 passwd: str, ssl: bool = False):
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

        smtp_port = section.getint('smtp_port', section.getint('port'))

        if smtp_port is None:
            raise ValueError('No SMTP port specified.')

        login_name = section.get('login_name', section.get('user'))

        if login_name is None:
            raise ValueError('No login nane specified.')

        passwd = section.get('passwd', section.get('password'))

        if passwd is None:
            raise ValueError('No password specified.')

        ssl = section.getboolean('ssl', False)
        return cls(smtp_server, smtp_port, login_name, passwd, ssl=ssl)

    @classmethod
    def from_config(cls, config: ConfigParser) -> Mailer:
        """Returns a new mailer instance from the provided config."""
        return cls.from_section(config['email'])

    def _send(self, emails: Iterable[EMail]) -> bool:
        """Sends emails."""
        result = True

        with SMTP(host=self.smtp_server, port=self.smtp_port) as smtp:
            if self.ssl:
                smtp.starttls()
            else:
                LOGGER.warning('Connecting without SSL/TLS encryption.')

            smtp.ehlo()
            smtp.login(self.login_name, self._passwd)

            # Actually send emails.
            for email in emails:
                try:
                    smtp.send_message(email)
                except SMTPException as error:
                    LOGGER.error(str(error))
                    result = False

            smtp.quit()

        return result

    def send(self, emails: Iterable[EMail], background: bool = True) -> bool:
        """Sends email in a sub thread to not block the system."""
        if background:
            sending = Thread(target=self._send, args=[emails])
            sending.start()
            return sending

        return self._send(emails)
