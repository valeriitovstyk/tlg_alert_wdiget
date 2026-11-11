"""Тестовий пуш на віджет «Київ»: червоний → жовтий → зелений (по 20 с), потім справжній колір з NEPTUN."""
import os
import time

import bot
from fcm import Fcm, kyiv_color

f = Fcm(os.environ["FCM_SERVICE_ACCOUNT"], bot.log)
for color in ("red", "yellow", "green"):
    ok = f.send(color, high=True)
    bot.log("тест:", color, "надіслано" if ok else "ПОМИЛКА")
    time.sleep(20)
try:
    a = bot.http_json(f"{bot.NEPTUN}/api/v1/alerts")
    t = bot.http_json(f"{bot.NEPTUN}/api/v1/threats")
    real = kyiv_color(bot.analyze(a, t))
except Exception as e:
    bot.log("neptun:", e, "— лишаю сірий не можу, шлю жовтий як обережний варіант")
    real = "yellow"
ok = f.send(real, high=True)
bot.log("тест завершено, справжній колір:", real, "надіслано" if ok else "ПОМИЛКА")
