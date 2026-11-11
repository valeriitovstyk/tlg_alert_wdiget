package ua.alert.kyiv

import android.app.Activity
import android.os.Bundle
import android.text.Html
import android.text.format.DateFormat
import android.text.method.LinkMovementMethod
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.Date

/** Відкривається з віджета: кольорова смуга й те саме повідомлення, що бот пише в Telegram. */
class MainActivity : Activity() {
    private lateinit var swatch: TextView
    private lateinit var body: TextView
    private lateinit var footer: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (20 * resources.displayMetrics.density).toInt()
        swatch = TextView(this).apply {
            textSize = 22f
            setTextColor(0xFFFFFFFF.toInt())
            setPadding(pad, pad * 3, pad, pad)
        }
        body = TextView(this).apply {
            textSize = 18f
            setLineSpacing(0f, 1.15f)
            setPadding(pad, pad, pad, pad)
            movementMethod = LinkMovementMethod.getInstance()
        }
        footer = TextView(this).apply {
            textSize = 13f
            alpha = 0.6f
            setPadding(pad, 0, pad, pad * 2)
        }
        setContentView(ScrollView(this).apply {
            addView(LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.VERTICAL
                addView(swatch, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                addView(body)
                addView(footer)
            })
        })
    }

    override fun onResume() {
        super.onResume()
        render()
        KyivWidget.updateAll(this)
    }

    private fun render() {
        val ok = App.ensureFirebase(application)
        swatch.setBackgroundColor(Status.color(this))
        swatch.text = "Київ: " + Status.label(this)
        val x = Status.text(this)
        body.text = if (x != null)
            Html.fromHtml(x.replace("   ", "&nbsp;&nbsp;&nbsp;").replace("\n", "<br>"), Html.FROM_HTML_MODE_COMPACT)
        else
            "Повідомлення від бота ще не приходило."
        val t = Status.sentAt(this)
        footer.text = buildString {
            append(if (t > 0) "Отримано від бота: " + DateFormat.format("dd.MM HH:mm", Date(t)) else "Від бота ще нічого не приходило")
            if (!ok) append("\nFirebase не налаштований у цій збірці.")
            append("\n\n🔴 тривога в Києві · 🟡 шахеди чи ракети курсом на Київ · 🟢 спокійно · ⚪ бот давно не надсилав оновлень")
        }
    }
}
