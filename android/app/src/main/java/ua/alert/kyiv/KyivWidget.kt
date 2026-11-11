package ua.alert.kyiv

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews

/** Плашка одного кольору. Перемальовується при кожному пуші й сама раз на 30 хв (щоб посіріти, якщо пушів немає). */
class KyivWidget : AppWidgetProvider() {
    override fun onUpdate(ctx: Context, mgr: AppWidgetManager, ids: IntArray) {
        for (id in ids) mgr.updateAppWidget(id, views(ctx))
    }

    override fun onEnabled(ctx: Context) {
        (ctx.applicationContext as? android.app.Application)?.let { App.ensureFirebase(it) }
    }

    companion object {
        fun views(ctx: Context): RemoteViews {
            val v = RemoteViews(ctx.packageName, R.layout.widget)
            v.setInt(R.id.tile, "setColorFilter", Status.color(ctx))
            v.setContentDescription(R.id.tile, "Київ: " + Status.label(ctx))
            val open = PendingIntent.getActivity(
                ctx, 0, Intent(ctx, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            v.setOnClickPendingIntent(R.id.tile, open)
            return v
        }

        fun updateAll(ctx: Context) {
            val mgr = AppWidgetManager.getInstance(ctx)
            val ids = mgr.getAppWidgetIds(ComponentName(ctx, KyivWidget::class.java))
            for (id in ids) mgr.updateAppWidget(id, views(ctx))
        }
    }
}
