package com.spanplay

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Persistent event log (one line per event) stored in the app's private files dir. */
object EventLog {
    private const val FILE = "events.log"
    private const val MAX_BYTES = 400_000L
    private val fmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
    private var file: File? = null

    @Synchronized
    fun init(ctx: Context) {
        if (file == null) file = File(ctx.applicationContext.filesDir, FILE)
    }

    @Synchronized
    fun add(ctx: Context, event: String) {
        init(ctx)
        val f = file ?: return
        try {
            if (f.length() > MAX_BYTES) {
                // Keep the newest half.
                val lines = f.readLines()
                f.writeText(lines.drop(lines.size / 2).joinToString("\n", postfix = "\n"))
            }
            f.appendText("${fmt.format(Date())} | $event\n")
        } catch (_: Throwable) {
        }
    }

    @Synchronized
    fun readAll(ctx: Context): String {
        init(ctx)
        return try { file?.takeIf { it.exists() }?.readText() ?: "" } catch (_: Throwable) { "" }
    }

    fun tail(ctx: Context, maxLines: Int = 200): String =
        readAll(ctx).lines().filter { it.isNotBlank() }.takeLast(maxLines).joinToString("\n")

    @Synchronized
    fun clear(ctx: Context) {
        init(ctx)
        try { file?.writeText("") } catch (_: Throwable) {}
    }
}
