#!/usr/bin/env python3
"""Бот для Telegram-віджета «Тривога · Київ / Львів».

Раз на POLL_S секунд бере тривоги й цілі з NEPTUN (https://neptun.in.ua, без ключа),
рахує стан для Києва й Львова і пише його в спільний (shared) віджет через
editSharedWidgetData: одне оновлення, і віджет змінюється в усіх чатах, куди його надіслано.

Якщо Bot API не знає sendWidget (віджети ще не вийшли публічно), бот сам переходить
у текстовий режим: шле звичайне повідомлення й редагує його.

Лише стандартна бібліотека Python 3.9+. Налаштування — змінні середовища:
  BOT_TOKEN   токен від @BotFather (обов'язково)
  CHAT_IDS    через кому: чати, куди надіслати й закріпити віджет при старті (необов'язково;
              будь-хто може написати боту /start і отримати віджет)
  BOT_API     база Bot API, за замовчуванням https://api.telegram.org
              (бета з віджетами: https://api.telegram.org/beta)
  TEST_ENV    1 — тестове середовище Telegram (…/bot<token>/test/…)
  MODE        auto (за замовчуванням) | widget | text
  POLL_S      як часто питати NEPTUN, с (за замовчуванням 15, мінімум 5)
  RUN_FOR_S   скільки працювати, с (0 — завжди; для GitHub Actions)
  STATE_FILE  де тримати id віджета й повідомлень (за замовчуванням bot/state.json)
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIDGET_HTML = (HERE.parent / "widget" / "widget.html").read_text(encoding="utf-8")

NEPTUN = os.environ.get("NEPTUN_BASE", "https://neptun.in.ua").rstrip("/")
UA = "tlg-alert-widget/1.0 (+https://github.com/valeriitovstyk/tlg_alert_wdiget)"
ATTRIBUTION = "Дані: NEPTUN (neptun.in.ua) — агрегатор, не офіційне оповіщення."

# ---------------------------------------------------------------- аналіз

def norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())

CITIES = [
    dict(name="Київ", lat=50.4501, lon=30.5234, near=60,
         alert=lambda e: norm(e.get("key")) == "м. київ" or norm(e.get("name")) in ("м. київ", "київ"),
         region=lambda r: bool(re.search(r"(^|\s)м\.?\s*київ$", norm(r))) or norm(r) == "київ" or "київськ" in norm(r)),
    dict(name="Львів", lat=49.8397, lon=24.0297, near=60,
         alert=lambda e: "львів" in norm(e.get("key")) or "львів" in norm(e.get("name")),
         region=lambda r: "львів" in norm(r)),
]
RANGE_KM = {"drone": 450, "missile": 1200}
TOL_DEG = 25

def dist_km(a, b, c, d):
    p1, p2, dp, dl = map(math.radians, (a, c, c - a, d - b))
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))

def bearing(a, b, c, d):
    p1, p2, dl = math.radians(a), math.radians(c), math.radians(d - b)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

def ang(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d

KIND = {"uav": "drone", "missile": "missile", "ballistic": "ballistic", "mig31k": "mig31k", "kab": "kab"}

def size(t):
    try:
        n = int(t.get("count") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if n > 0 else 1

def heading(t):
    h = t.get("heading")
    if isinstance(h, (int, float)):
        return float(h)
    v = t.get("velocity") or {}
    b = v.get("bearingDeg") if isinstance(v, dict) else None
    return float(b) if isinstance(b, (int, float)) else None

def relation(t, city):
    lat, lon = t.get("lat"), t.get("lon")
    if t.get("areaOnly") or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return "region" if city["region"](t.get("region")) else None
    d = dist_km(lat, lon, city["lat"], city["lon"])
    if d <= city["near"]:
        return "near"
    k = KIND.get(t.get("type"))
    h = heading(t)
    if h is not None and d <= RANGE_KM["drone" if k == "drone" else "missile"] \
            and ang(h, bearing(lat, lon, city["lat"], city["lon"])) <= TOL_DEG:
        return "toward"
    return "region" if city["region"](t.get("region")) else None

def parse_since(s):
    if not s:
        return 0
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0

def analyze(alerts: dict, threats: dict) -> dict:
    """Стан для віджета, компактно (ліміт 1024 байти):
    c: [[тривога 0/1, з (unix), шахеди курсом, з них поруч, ракети курсом, з них поруч, КАБи, балістика 0/1], …] — Київ, Львів
    g: [шахеди по Україні, ракети, балістичні, МіГ-31К 0/1]"""
    oblasts = alerts.get("oblasts") or []
    raions = alerts.get("raions") or []
    ts = [t for t in (threats.get("threats") or []) if isinstance(t, dict) and t.get("status") not in ("resolved", "stale")]
    g = [0, 0, 0, 0]
    for t in ts:
        k = KIND.get(t.get("type"))
        if k == "mig31k":
            g[3] = 1
        if t.get("advisory"):
            continue
        if k == "drone":
            g[0] += size(t)
        elif k == "missile":
            g[1] += size(t)
        elif k == "ballistic":
            g[2] += size(t)
    cities = []
    for city in CITIES:
        e = next((x for x in oblasts if city["alert"](x)), None) or next((x for x in raions if city["alert"](x)), None)
        r = [1 if e else 0, parse_since(e.get("since")) if e else 0, 0, 0, 0, 0, 0, 0]
        for t in ts:
            if t.get("advisory"):
                continue
            k = KIND.get(t.get("type"))
            if not k or k == "mig31k":
                continue
            rel = relation(t, city)
            if not rel:
                continue
            n = size(t)
            if k == "drone":
                r[2] += n
                r[3] += n if rel == "near" else 0
            elif k == "missile":
                r[4] += n
                r[5] += n if rel == "near" else 0
            elif k == "kab":
                r[6] += n
            elif k == "ballistic":
                r[7] = 1
        cities.append(r)
    return {"c": cities, "g": g}

def fmt_text(state: dict) -> str:
    """Текстова версія для клієнтів без віджетів."""
    lines = []
    for city, c in zip(CITIES, state["c"]):
        a, since, d, dn, mi, mn, kab, bal = c
        if a:
            mins = max(0, int((time.time() - since) / 60)) if since else 0
            lines.append(f"🔴 <b>{city['name']} — ТРИВОГА</b> ({mins} хв)")
            lines.append(f"   🛩 шахедів курсом: <b>{d}</b>" + (f" ({dn} поруч)" if dn else ""))
            lines.append(f"   🚀 ракет курсом: <b>{mi}</b>" + (f" ({mn} поруч)" if mn else ""))
            if kab:
                lines.append(f"   💣 КАБів: <b>{kab}</b>")
            if bal or state["g"][3]:
                lines.append("   ⚠️ " + ("Загроза балістики" if bal else "МіГ-31К у повітрі"))
        else:
            extra = []
            if d:
                extra.append(f"{d} шахед. курсом")
            if mi:
                extra.append(f"{mi} ракет курсом")
            if bal:
                extra.append("загроза балістики")
            lines.append(f"🟢 <b>{city['name']}</b> — тривоги немає" + (f" (але: {', '.join(extra)})" if extra else ""))
        lines.append("")
    g = state["g"]
    lines.append(f"Україна: {g[0]} шахедів · {g[1]} ракет · {g[2]} балістичних" + (" · МіГ-31К у повітрі" if g[3] else ""))
    lines.append(f"Оновлено {time.strftime('%H:%M:%S', time.localtime(state['t']))}")
    lines.append(f"<i>{ATTRIBUTION}</i>")
    return "\n".join(lines)

# ---------------------------------------------------------------- мережа

def http_json(url: str, data: dict | None = None, timeout: float = 20):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA, "Accept": "application/json",
        **({"Content-Type": "application/json"} if body else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

class TgError(Exception):
    pass

class Bot:
    def __init__(self, token: str, base: str, test_env: bool):
        self.token = token
        self.url = f"{base.rstrip('/')}/bot{token}" + ("/test" if test_env else "")

    def __call__(self, method: str, **params):
        for _ in range(5):
            try:
                body = http_json(f"{self.url}/{method}", params, timeout=40)
            except urllib.error.HTTPError as e:
                try:
                    body = json.loads(e.read().decode())
                except Exception:
                    raise TgError(f"{method}: HTTP {e.code}") from None
            except Exception as e:
                raise TgError(f"{method}: {str(e).replace(self.token, '<token>')}") from None
            if body.get("ok"):
                return body["result"]
            wait = (body.get("parameters") or {}).get("retry_after")
            if wait:
                time.sleep(wait + 0.2)
                continue
            raise TgError(f"{method}: {body.get('description')}")
        raise TgError(f"{method}: too many retries")

def not_modified(e: Exception) -> bool:
    return "not modified" in str(e).lower()

def unsupported(e: Exception) -> bool:
    """Bot API без віджетів відповідає на невідомий метод 404 «Not Found»."""
    s = str(e).lower()
    return s.endswith(": not found") or s.endswith("http 404")

# ---------------------------------------------------------------- головний цикл

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def main():
    token = os.environ.get("BOT_TOKEN") or sys.exit("BOT_TOKEN не задано")
    bot = Bot(token, os.environ.get("BOT_API", "https://api.telegram.org"), os.environ.get("TEST_ENV") == "1")
    mode = os.environ.get("MODE", "auto")
    poll_s = max(5, int(os.environ.get("POLL_S", "15")))
    run_for = int(os.environ.get("RUN_FOR_S", "0"))
    state_file = Path(os.environ.get("STATE_FILE", HERE / "state.json"))
    chat_ids = [c.strip() for c in os.environ.get("CHAT_IDS", "").split(",") if c.strip()]

    store = {"widget_id": None, "texts": {}, "chats": []}
    if state_file.exists():
        try:
            store.update(json.loads(state_file.read_text()))
        except ValueError:
            pass

    def save():
        state_file.write_text(json.dumps(store, ensure_ascii=False, indent=1))

    started = time.time()
    rev = int(time.time())  # ревізія росте завжди, навіть після перезапуску
    last_pub = None
    state = None
    offset = None

    def publish(state):
        nonlocal mode
        pub = json.dumps({"r": state["r"], "t": state["t"], "c": state["c"], "g": state["g"]}, separators=(",", ":"))
        if mode != "text" and store.get("widget_id"):
            try:
                bot("editSharedWidgetData", widget_id=store["widget_id"], public_data=pub, cache_time=10)
            except TgError as e:
                if not not_modified(e):
                    log("віджет:", e)
        text = fmt_text(state)
        for chat, mid in list(store["texts"].items()):
            try:
                bot("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML",
                    disable_web_page_preview=True)
            except TgError as e:
                if not not_modified(e):
                    log("текст", chat, e)
                    if "not found" in str(e).lower():
                        store["texts"].pop(chat, None)
                        save()

    def deliver(chat):
        """Надіслати віджет (або текст, якщо віджети недоступні) у чат і закріпити."""
        nonlocal mode
        pub = json.dumps({"r": state["r"], "t": state["t"], "c": state["c"], "g": state["g"]}, separators=(",", ":")) if state else None
        msg = None
        if mode != "text":
            try:
                if store.get("widget_id"):
                    msg = bot("sendSharedWidget", chat_id=chat, widget_id=store["widget_id"])
                else:
                    msg = bot("sendWidget", chat_id=chat, html=WIDGET_HTML, width=0, height=0, is_shared=True,
                              **({"public_data": pub} if pub else {}))
                    wid = (msg.get("widget") or {}).get("id")
                    if wid:
                        store["widget_id"] = wid
                        save()
                        log("створено спільний віджет", wid)
            except TgError as e:
                if mode == "auto" and unsupported(e):
                    log("віджети недоступні на цьому Bot API, переходжу в текстовий режим:", e)
                    mode = "text"
                else:
                    log("sendWidget", chat, e)
        if msg is None and mode == "text":
            msg = bot("sendMessage", chat_id=chat, text=fmt_text(state) if state else "Завантаження…",
                      parse_mode="HTML", disable_web_page_preview=True)
            store["texts"][str(chat)] = msg["message_id"]
        if msg is not None:
            if str(chat) not in store["chats"]:
                store["chats"].append(str(chat))
            save()
            try:
                bot("pinChatMessage", chat_id=chat, message_id=msg["message_id"], disable_notification=True)
            except TgError as e:
                log("pin", chat, e)

    next_poll = 0.0
    while not run_for or time.time() - started < run_for:
        now = time.time()
        if now >= next_poll:
            next_poll = now + poll_s
            try:
                a = http_json(f"{NEPTUN}/api/v1/alerts")
                t = http_json(f"{NEPTUN}/api/v1/threats")
                s = analyze(a, t)
                key = json.dumps(s)
                # Перепублікувати при зміні або раз на хвилину (щоб віджет знав, що дані свіжі).
                if key != last_pub or not state or now - state["t"] >= 60:
                    rev += 1
                    state = {**s, "r": rev, "t": int(now)}
                    publish(state)
                    last_pub = key
                    if chat_ids:
                        for c in chat_ids:
                            if c not in store["chats"]:
                                deliver(c)
            except Exception as e:  # NEPTUN недоступний — спробуємо наступного разу
                log("neptun:", e)
        # Команди: /start (і /alert) — надіслати віджет у цей чат.
        try:
            ups = bot("getUpdates", timeout=max(1, int(next_poll - time.time())),
                      allowed_updates=["message"], **({"offset": offset} if offset else {}))
        except TgError as e:
            log("getUpdates:", e)
            time.sleep(3)
            continue
        for u in ups:
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            txt = (m.get("text") or "").split("@")[0].strip()
            if txt in ("/start", "/alert", "/trivoga") and m.get("chat"):
                try:
                    deliver(m["chat"]["id"])
                except TgError as e:
                    log("deliver:", e)
    log("час роботи вийшов, зупиняюсь")

if __name__ == "__main__":
    main()
