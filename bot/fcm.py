"""Тихі пуші на Android-віджет «Київ» через Firebase Cloud Messaging (HTTP v1).

Шлемо data-повідомлення на тему «kyiv»: {"k": "red|yellow|green", "t": unix}.
Високий пріоритет — лише коли колір змінився (щоб розбудити телефон у сні);
підтвердження «нічого не змінилось» — звичайним пріоритетом раз на 15 хв,
інакше віджет вважає дані застарілими й сіріє.

Потрібен секрет FCM_SERVICE_ACCOUNT (JSON ключа сервісного акаунта Firebase)
і пакет google-auth (pip install google-auth requests).
"""
from __future__ import annotations

import json
import time
import urllib.request

TOPIC = "kyiv"
HEARTBEAT_S = 15 * 60


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

    def send(self, color: str, high: bool) -> bool:
        body = {"message": {
            "topic": TOPIC,
            "data": {"k": color, "t": str(int(time.time()))},
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

    def update(self, state: dict) -> None:
        color = kyiv_color(state)
        now = time.time()
        if color != self.last_color:
            if self.send(color, high=True):
                self.log("fcm: колір Києва →", color)
                self.last_color, self.last_sent = color, now
        elif now - self.last_sent >= HEARTBEAT_S:
            if self.send(color, high=False):
                self.last_sent = now
