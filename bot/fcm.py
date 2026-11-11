"""Тихі пуші на Android-віджет «Київ» через Firebase Cloud Messaging (HTTP v1).

Шлемо data-повідомлення на тему «kyiv»: {"k": "red|yellow|green", "t": unix, "x": текст як у Telegram (HTML)}.
Високий пріоритет — лише коли колір змінився (щоб розбудити телефон у сні).
Решта — звичайним пріоритетом при кожному оновленні тексту (раз на хвилину чи рідше): поки телефон спить,
Android тримає лише останнє (collapse_key), тож батарея не страждає, а при відкритті застосунку текст свіжий.
Раз на HEARTBEAT_S — підтвердження високим пріоритетом: звичайні пуші в глибокому сні Android притримує
годинами, і віджет сірів би вночі. Інтервал іде в пуші («h»), застосунок сіріє після 2,5 інтервалу без пушів.

Потрібен секрет FCM_SERVICE_ACCOUNT (JSON ключа сервісного акаунта Firebase)
і пакет google-auth (pip install google-auth requests).
"""
from __future__ import annotations

import json
import time
import urllib.request

TOPIC = "kyiv"
HEARTBEAT_S = 30 * 60  # підтвердження «без змін» — високим пріоритетом, щоб будило телефон у Doze


def kyiv_color(state: dict) -> str:
    """red — тривога в Києві; yellow — тривоги нема, але шахеди чи ракети курсом на Київ; green — спокійно."""
    c = state["c"][0]
    if c[0]:
        return "red"
    if c[2] > 0 or c[4] > 0:
        return "yellow"
    return "green"


class Fcm:
    def __init__(self, service_account_json: str, log):
        from google.oauth2 import service_account  # лише якщо пуші ввімкнені

        info = json.loads(service_account_json)
        self.project = info["project_id"]
        self.creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
        self.log = log
        self.last_color = None
        self.last_sent = 0.0

    def _token(self) -> str:
        if not self.creds.valid:
            from google.auth.transport.requests import Request
            self.creds.refresh(Request())
        return self.creds.token

    def send(self, color: str, high: bool, text: str | None = None) -> bool:
        data = {"k": color, "t": str(int(time.time())), "h": str(HEARTBEAT_S)}
        if text:
            data["x"] = text[:3000]  # ліміт FCM — 4 КБ на все повідомлення
        body = {"message": {
            "topic": TOPIC,
            "data": data,
            "android": {"priority": "HIGH" if high else "NORMAL", "ttl": "900s", "collapse_key": TOPIC},
        }}
        req = urllib.request.Request(
            f"https://fcm.googleapis.com/v1/projects/{self.project}/messages:send",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
            return True
        except Exception as e:  # не валимо бота через пуші
            detail = e.read().decode()[:300] if hasattr(e, "read") else ""
            self.log("fcm:", e, detail)
            return False

    def update(self, state: dict, text: str | None = None) -> None:
        color = kyiv_color(state)
        now = time.time()
        if color != self.last_color:
            if self.send(color, high=True, text=text):
                self.log("fcm: колір Києва →", color)
                self.last_color, self.last_sent, self.last_text = color, now, text
        elif now - self.last_sent >= HEARTBEAT_S:
            if self.send(color, high=True, text=text):
                self.last_sent, self.last_text = now, text
        elif text and text != getattr(self, "last_text", None):
            # Лише свіжий текст для екрана застосунку: звичайний пріоритет, не будить телефон.
            if self.send(color, high=False, text=text):
                self.last_text = text
