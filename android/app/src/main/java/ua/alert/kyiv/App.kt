package ua.alert.kyiv

import android.app.Application
import android.util.Log
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        ensureFirebase(this)
    }

    companion object {
        const val TOPIC = "kyiv"

        /** true, якщо Firebase налаштований і підписка на тему пішла. */
        fun ensureFirebase(app: Application): Boolean {
            if (BuildConfig.FB_APP_ID.isEmpty()) return false
            if (FirebaseApp.getApps(app).isEmpty()) {
                FirebaseApp.initializeApp(
                    app,
                    FirebaseOptions.Builder()
                        .setApplicationId(BuildConfig.FB_APP_ID)
                        .setApiKey(BuildConfig.FB_API_KEY)
                        .setProjectId(BuildConfig.FB_PROJECT_ID)
                        .setGcmSenderId(BuildConfig.FB_SENDER_ID)
                        .build()
                )
            }
            FirebaseMessaging.getInstance().subscribeToTopic(TOPIC)
                .addOnCompleteListener { Log.i("KyivAlert", "subscribe $TOPIC: ${it.isSuccessful}") }
            return true
        }
    }
}
