package com.spanplay

import android.content.Context
import android.os.Environment
import java.io.File

/**
 * Writes a text file to every place a USB stick could be reachable from a normal app:
 *  - app-specific dirs on every mounted volume (getExternalFilesDirs) - this includes a USB stick
 *    when the head unit mounts it as secondary storage
 *  - /storage/<volume>/SpanPlay/ (works only where the OS allows it)
 * The caller can additionally offer the system file picker (ACTION_CREATE_DOCUMENT).
 */
object Exporter {
    fun export(ctx: Context, fileName: String, text: String): List<String> {
        val written = mutableListOf<String>()
        val dirs = linkedSetOf<File>()
        try {
            ctx.getExternalFilesDirs(null).filterNotNull().forEach { dirs.add(it) }
        } catch (_: Throwable) {}
        try {
            File("/storage").listFiles()?.forEach { v ->
                if (v.isDirectory && v.name != "self" && v.name != "emulated") dirs.add(File(v, "SpanPlay"))
            }
        } catch (_: Throwable) {}
        try {
            @Suppress("DEPRECATION")
            dirs.add(File(Environment.getExternalStorageDirectory(), "SpanPlay"))
        } catch (_: Throwable) {}

        for (d in dirs) {
            try {
                d.mkdirs()
                val f = File(d, fileName)
                f.writeText(text)
                if (f.exists() && f.length() > 0) written.add(f.absolutePath)
            } catch (_: Throwable) {
            }
        }
        return written
    }
}
