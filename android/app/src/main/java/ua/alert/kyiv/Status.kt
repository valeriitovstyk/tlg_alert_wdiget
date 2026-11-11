package ua.alert.kyiv

import android.content.Context
import android.graphics.Color

/** Стан Києва, який шле бот: red — тривога, yellow — шахеди/ракети курсом на Київ, green — спокійно. */
object Status {
    private const val PREFS = "status"
    /** Бот шле підтвердження раз на 15 хв; якщо 45 хв нічого — дані застаріли (сірий). */
    const val STALE_MS = 45L * 60 * 1000

    const val RED = 0xFFFF0A0A.toInt()
    const val YELLOW = 0xFFF2CE02.toInt()
    const val GREEN = 0xFF209C05.toInt()
    const val GREY = 0xFF6B6B6B.toInt()

    fun save(ctx: Context, kind: String, sentAtMs: Long) {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        // Пуші можуть прийти не по порядку: старіший не перезаписує новіший.
        if (sentAtMs < p.getLong("t", 0)) return
        p.edit().putString("k", kind).putLong("t", sentAtMs).putLong("rx", System.currentTimeMillis()).apply()
    }

    fun kind(ctx: Context): String? = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("k", null)
    fun sentAt(ctx: Context): Long = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getLong("t", 0)

    fun isStale(ctx: Context): Boolean {
        val t = sentAt(ctx)
        return t == 0L || System.currentTimeMillis() - t > STALE_MS
    }

    fun color(ctx: Context): Int = if (isStale(ctx)) GREY else when (kind(ctx)) {
        "red" -> RED
        "yellow" -> YELLOW
        "green" -> GREEN
        else -> GREY
    }

    fun label(ctx: Context): String = if (isStale(ctx)) "немає свіжих даних" else when (kind(ctx)) {
        "red" -> "тривога в Києві"
        "yellow" -> "шахеди / ракети курсом на Київ"
        "green" -> "спокійно"
        else -> "немає даних"
    }
}
