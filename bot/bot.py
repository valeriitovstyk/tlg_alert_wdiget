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

# Повідомлення моніторингових каналів (NEPTUN /api/v1/messages): це текст людей, а не радар.
CITY_TEXT = [
    re.compile(r"(київ|києв|киев|kyiv|kiev)(?!щин|ськ|ск)", re.I),
    re.compile(r"(львів|львов|lviv|lvov)(?!щин|ськ|ск)", re.I),
]
# Лише події, не прогнози: «курсом на», «загроза» сюди не входять.
BOOM_RE = re.compile(r"вибух|взрыв|прил[іиі]т|детонац|прац\w*\s+ппо|робот\w*\s+ппо|работ\w*\s+пво", re.I)
BOOM_WINDOW_S = 20 * 60
STRATEGIC = [  # код, шаблон, підпис
    ("o", re.compile(r"оре[шщ]н|орєшн|oreshnik", re.I), "загроза Орєшніка"),
    ("k", re.compile(r"кин[дж]{1,2}ал|kinzhal", re.I), "загроза Кинджалів"),
    ("t", re.compile(r"ту-?\s?(95|160|22)|стратегічн\w*\s+авіац|стратегическ\w*\s+авиац", re.I), "стратегічна авіація (Ту-95/160/22)"),
    ("c", re.compile(r"калібр|калибр|kalibr", re.I), "загроза Калібрів"),
]
STRATEGIC_LABEL = {code: label for code, _, label in STRATEGIC}
CANCEL_RE = re.compile(r"відбій|отбой|минул|скасов|відмін|отмен|приземл|посадк", re.I)
STRATEGIC_WINDOW_S = 45 * 60
DRONE_KMH = 150  # якщо NEPTUN не дав швидкості

def scan_messages(messages, now):
    """→ (вік останнього повідомлення про вибухи/ППО по містах у хв або -1, [[код, вік у хв], …])."""
    items = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        t = parse_since(m.get("date"))
        if t and now - t <= max(BOOM_WINDOW_S, STRATEGIC_WINDOW_S) and t <= now + 120:
            items.append((t, str(m.get("text") or "")))
    items.sort(reverse=True)  # найновіші спершу
    booms = []
    for city_re in CITY_TEXT:
        hit = next((t for t, x in items if now - t <= BOOM_WINDOW_S and BOOM_RE.search(x) and city_re.search(x)), None)
        booms.append(max(0, int((now - hit) // 60)) if hit else -1)
    strat = []
    for code, rx, _ in STRATEGIC:
        last = next(((t, x) for t, x in items if now - t <= STRATEGIC_WINDOW_S and rx.search(x)), None)
        if last and not CANCEL_RE.search(last[1]):  # найсвіжіша згадка — не «відбій»
            strat.append([code, max(0, int((now - last[0]) // 60))])
    return booms, strat

def analyze(alerts: dict, threats: dict, messages=None, now=None) -> dict:
    """Стан для віджета, компактно (ліміт 1024 байти):
    c: [[тривога 0/1, з (unix), шахеди курсом, з них поруч, ракети курсом, з них поруч, КАБи, балістика 0/1,
         підліт найближчого шахеда у хв (-1 — немає, 0 — вже поруч), вибухи/ППО хв тому (-1 — немає)], …] — Київ, Львів
    g: [шахеди по Україні, ракети, балістичні, МіГ-31К 0/1]
    s: [[код, хв тому], …] — з каналів: o Орєшнік, k Кинджал, t стратегічна авіація, c Калібр"""
    now = now or time.time()
    oblasts = alerts.get("oblasts") or []
    raions = alerts.get("raions") or []
    ts = [t for t in (threats.get("threats") or []) if isinstance(t, dict) and t.get("status") not in ("resolved", "stale")]
    booms, strat = scan_messages(messages, now)
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
    for i, city in enumerate(CITIES):
        e = next((x for x in oblasts if city["alert"](x)), None) or next((x for x in raions if city["alert"](x)), None)
        r = [1 if e else 0, parse_since(e.get("since")) if e else 0, 0, 0, 0, 0, 0, 0, -1, booms[i]]
        etas = []
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
                if rel == "near":
                    etas.append(0)
                elif rel == "toward":
                    v = (t.get("velocity") or {}).get("speedKmh") if isinstance(t.get("velocity"), dict) else None
                    kmh = v if isinstance(v, (int, float)) and 40 <= v <= 400 else DRONE_KMH
                    d = max(0.0, dist_km(t["lat"], t["lon"], city["lat"], city["lon"]) - city["near"])
                    etas.append(max(1, round(d / kmh * 60)))
            elif k == "missile":
                r[4] += n
                r[5] += n if rel == "near" else 0
            elif k == "kab":
                r[6] += n
            elif k == "ballistic":
                r[7] = 1
        r[8] = min(etas) if etas else -1
        cities.append(r)
    return {"c": cities, "g": g, "s": strat}

def ago_txt(m):
    return "щойно" if m <= 0 else f"{m} хв тому"

STRATEGIC_SHORT = {"o": "Орєшнік", "k": "Кинджал", "t": "Ту-95", "c": "Калібр"}

def summary_line(state: dict) -> str:
    """Напр.: «🔴 Київ 9🛩 ~23хв 🚀4 ⚠️ · 🟢 Львів (2🛩)»."""
    parts = []
    for city, c in zip(CITIES, state["c"]):
        a, _, d, _, mi, _, _, bal = c[:8]
        eta = c[8] if len(c) > 8 else -1
        boom = c[9] if len(c) > 9 else -1
        bits = []
        if d:
            bits.append(f"{d}🛩" + (f" ~{eta}хв" if eta > 0 else " поруч" if eta == 0 else ""))
        if mi:
            bits.append(f"🚀{mi}")
        if bal:
            bits.append("⚠️балістика")
        if boom >= 0:
            bits.append("💥")
        if a:
            parts.append(f"🔴 {city['name']}" + (" " + " ".join(bits) if bits else ""))
        else:
            parts.append(f"🟢 {city['name']}" + (f" ({' '.join(bits)})" if bits else ""))
    line = " · ".join(parts)
    strat = state.get("s") or []
    if strat:
        line += " · ⚠️" + ", ".join(STRATEGIC_SHORT[c] for c, _ in strat)
    return f"<b>{line}</b>"

def fmt_text(state: dict) -> str:
    """Текстова версія для клієнтів без віджетів.
    Перший рядок — короткий підсумок: його показують прев'ю чату й віджет «Чати» на Android."""
    lines = [summary_line(state), ""]
    for city, c in zip(CITIES, state["c"]):
        a, since, d, dn, mi, mn, kab, bal = c[:8]
        eta = c[8] if len(c) > 8 else -1
        boom = c[9] if len(c) > 9 else -1
        if a:
            mins = max(0, int((time.time() - since) / 60)) if since else 0
            lines.append(f"🔴 <b>{city['name']} — ТРИВОГА</b> ({mins} хв)")
            lines.append(f"   🛩 шахедів курсом: <b>{d}</b>" + (f" ({dn} поруч)" if dn else ""))
            if eta > 0:
                lines.append(f"   ⏱ найближчий шахед: ~<b>{eta} хв</b>")
            lines.append(f"   🚀 ракет курсом: <b>{mi}</b>" + (f" ({mn} поруч)" if mn else ""))
            if kab:
                lines.append(f"   💣 КАБів: <b>{kab}</b>")
            if bal or state["g"][3]:
                lines.append("   ⚠️ " + ("Загроза балістики" if bal else "МіГ-31К у повітрі"))
        else:
            extra = []
            if d:
                extra.append(f"{d} шахед. курсом" + (f", ~{eta} хв" if eta > 0 else ", вже поруч" if eta == 0 else ""))
            if mi:
                extra.append(f"{mi} ракет курсом")
            if bal:
                extra.append("загроза балістики")
            lines.append(f"🟢 <b>{city['name']}</b> — тривоги немає" + (f" (але: {', '.join(extra)})" if extra else ""))
        if boom >= 0:
            lines.append(f"   💥 вибухи / ППО, {ago_txt(boom)} <i>(з каналів)</i>")
        lines.append("")
    strat = state.get("s") or []
    if strat:
        lines.append("⚠️ <b>З каналів:</b> " + ", ".join(f"{STRATEGIC_LABEL[c]} ({ago_txt(m)})" for c, m in strat))
        lines.append("")
    # Умови NEPTUN вимагають видиме посилання біля даних: воно в рядку «Оновлено».
    lines.append(f'<a href="https://neptun.in.ua/">Оновлено {time.strftime("%H:%M:%S", time.localtime(state["t"]))}</a>')
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
        pub = json.dumps({"r": state["r"], "t": state["t"], "c": state["c"], "g": state["g"], "s": state["s"]}, ensure_ascii=False, separators=(",", ":"))
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
        pub = json.dumps({"r": state["r"], "t": state["t"], "c": state["c"], "g": state["g"], "s": state["s"]}, ensure_ascii=False, separators=(",", ":")) if state else None
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
                try:
                    msgs = http_json(f"{NEPTUN}/api/v1/messages")
                    msgs = msgs.get("messages") if isinstance(msgs, dict) else msgs
                except Exception as e:  # без каналів працюємо далі
                    log("messages:", e)
                    msgs = []
                s = analyze(a, t, msgs, now)
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
