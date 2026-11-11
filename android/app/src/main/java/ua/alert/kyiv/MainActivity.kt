package ua.alert.kyiv

import android.app.Activity
import android.os.Bundle
import android.text.format.DateFormat
import android.view.Gravity
import android.widget.LinearLayout
import android.widget.TextView
import java.util.Date

/** Екран лише для перевірки: який стан і коли прийшло останнє оновлення. */
class MainActivity : Activity() {
    private lateinit var text: TextView
    private lateinit var swatch: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        swatch = TextView(this).apply { minHeight = 320 }
        text = TextView(this).apply { textSize = 18f; setPadding(48, 48, 48, 48) }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(48, 160, 48, 48)
            addView(swatch, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 320))
            addView(text)
        })
    }

    override fun onResume() {
        super.onResume()
        val ok = App.ensureFirebase(application)
        swatch.setBackgroundColor(Status.color(this))
        val t = Status.sentAt(this)
        text.text = buildString {
            append("Київ: ").append(Status.label(this@MainActivity)).append("\n\n")
            append(if (t > 0) "Останнє оновлення від бота: " + DateFormat.format("dd.MM HH:mm", Date(t)) else "Оновлень від бота ще не було")
            append("\n\n")
            append(if (ok) "Пуші підключені. Додайте віджет «Київ» на робочий стіл." else "Firebase не налаштований у цій збірці.")
            append("\n\n🔴 тривога в Києві\n🟡 шахеди чи ракети курсом на Київ\n🟢 спокійно\n⚪ бот давно не надсилав оновлень")
        }
        KyivWidget.updateAll(this)
    }
}
