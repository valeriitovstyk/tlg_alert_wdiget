package ua.alert.kyiv

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

/** Тихий data-пуш від бота: {"k": "red|yellow|green", "t": unix-секунди}. Нічого не показує. */
class PushService : FirebaseMessagingService() {
    override fun onMessageReceived(message: RemoteMessage) {
        val k = message.data["k"] ?: return
        if (k !in setOf("red", "yellow", "green")) return
        val t = message.data["t"]?.toLongOrNull()?.times(1000) ?: System.currentTimeMillis()
        Status.save(this, k, t)
        KyivWidget.updateAll(this)
    }

    override fun onNewToken(token: String) {
        // Ми шлемо на тему, токени не потрібні; підписка переживає зміну токена.
        App.ensureFirebase(application)
    }
}
