"""Alert delivery. Configure with env:

TORUB_NOTIFY=console,webhook,smtp         (default: console)
TORUB_WEBHOOK_URL=https://...             POST JSON {event, contact, text, price, target, ...}
                                          (point it at an SMS gateway / Telegram bot / n8n / etc.)
TORUB_SMTP_HOST / _PORT / _USER / _PASSWORD / _FROM / _TLS(=1)
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

import httpx

from .airports import NAMES
from .models import Alert

log = logging.getLogger("torobticket.notify")


MODE_FA = {"flight": "هواپیما", "train": "قطار", "bus": "اتوبوس"}


def alert_text(a: Alert, price: int) -> str:
    o, d = NAMES.get(a.origin, a.origin), NAMES.get(a.destination, a.destination)
    return (f"کاهش قیمت بلیط {MODE_FA.get(a.mode, '')} {o} به {d} ({a.date}): قیمت اکنون {price:,} تومان است "
            f"(قیمت هدف شما {a.target_price:,} تومان).")


class Notifier:
    name = "base"

    def accepts(self, contact: str) -> bool:
        return True

    async def send(self, alert: Alert, price: int) -> None:
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    name = "console"

    async def send(self, alert, price):
        log.info("NOTIFY %s: %s", alert.contact, alert_text(alert, price))


class WebhookNotifier(Notifier):
    name = "webhook"

    def __init__(self, url: str, client: httpx.AsyncClient | None = None):
        self.url, self.client = url, client

    async def send(self, alert, price):
        body = {"event": "price_alert", "alert_id": alert.id, "contact": alert.contact,
                "origin": alert.origin, "destination": alert.destination, "date": alert.date,
                "price": price, "target": alert.target_price, "text": alert_text(alert, price)}
        c = self.client or httpx.AsyncClient(timeout=8)
        try:
            (await c.post(self.url, json=body)).raise_for_status()
        finally:
            if not self.client:
                await c.aclose()


class SmtpNotifier(Notifier):
    name = "smtp"

    def __init__(self, host, port=587, user=None, password=None, sender=None, tls=True):
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.tls = sender or user or "noreply@localhost", tls

    def accepts(self, contact: str) -> bool:
        return "@" in contact

    def _send(self, alert: Alert, price: int):
        m = EmailMessage()
        m["Subject"], m["From"], m["To"] = "ترب تیکت: کاهش قیمت بلیط", self.sender, alert.contact
        m.set_content(alert_text(alert, price))
        with smtplib.SMTP(self.host, self.port, timeout=10) as s:
            if self.tls:
                s.starttls()
            if self.user:
                s.login(self.user, self.password or "")
            s.send_message(m)

    async def send(self, alert, price):
        await asyncio.to_thread(self._send, alert, price)


def build_notifiers() -> list[Notifier]:
    out: list[Notifier] = []
    for kind in [k.strip() for k in os.getenv("TORUB_NOTIFY", "console").split(",") if k.strip()]:
        if kind == "console":
            out.append(ConsoleNotifier())
        elif kind == "webhook":
            out.append(WebhookNotifier(os.environ["TORUB_WEBHOOK_URL"]))
        elif kind == "smtp":
            out.append(SmtpNotifier(
                os.environ["TORUB_SMTP_HOST"], int(os.getenv("TORUB_SMTP_PORT", "587")),
                os.getenv("TORUB_SMTP_USER"), os.getenv("TORUB_SMTP_PASSWORD"),
                os.getenv("TORUB_SMTP_FROM"), os.getenv("TORUB_SMTP_TLS", "1") != "0"))
        else:
            raise ValueError(f"unknown notifier {kind!r}")
    return out
