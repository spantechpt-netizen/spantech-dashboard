package com.spanplay

import android.content.Context

/** Simple settings storage for the Guardian (Phase A). */
class Prefs(ctx: Context) {
    private val sp = ctx.applicationContext.getSharedPreferences("spanplay", Context.MODE_PRIVATE)

    var targetPkg: String?
        get() = sp.getString("target_pkg", null)
        set(v) { sp.edit().putString("target_pkg", v).apply() }

    var watchdogEnabled: Boolean
        get() = sp.getBoolean("watchdog_enabled", true)
        set(v) { sp.edit().putBoolean("watchdog_enabled", v).apply() }

    var delaySec: Int
        get() = sp.getInt("delay_sec", 5)
        set(v) { sp.edit().putInt("delay_sec", v.coerceIn(1, 600)).apply() }

    var maxRetries: Int
        get() = sp.getInt("max_retries", 5)
        set(v) { sp.edit().putInt("max_retries", v.coerceIn(1, 100)).apply() }

    /** Whether boot / USB-attach should start the guardian service. */
    var serviceWanted: Boolean
        get() = sp.getBoolean("service_wanted", true)
        set(v) { sp.edit().putBoolean("service_wanted", v).apply() }
}
