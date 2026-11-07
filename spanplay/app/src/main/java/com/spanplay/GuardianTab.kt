package com.spanplay

import android.app.AlertDialog
import android.app.AppOpsManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.os.Process
import android.provider.Settings
import android.text.InputType
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Phase A tab: watchdog settings, permission shortcuts, event log. */
class GuardianTab(private val act: MainActivity) {
    private val prefs = Prefs(act)
    private val status = act.label("", size = 13f)
    private val targetText = act.label("", size = 15f)
    private val logView = act.label("", mono = true, size = 11f)
    private val sw = Switch(act).apply { text = "Watchdog enabled" }
    private val delayEdit = EditText(act).apply { inputType = InputType.TYPE_CLASS_NUMBER; hint = "seconds" }
    private val retryEdit = EditText(act).apply { inputType = InputType.TYPE_CLASS_NUMBER; hint = "count" }
    val root: ScrollView

    init {
        val box = act.vbox()
        box.addView(act.header("Status"))
        box.addView(status)

        box.addView(act.header("Permissions & shortcuts"))
        box.addView(act.btn("1) Grant Usage Access (required for watchdog)") {
            open(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS), "Usage Access")
        })
        box.addView(act.btn("2) Allow 'Display over other apps' (lets relaunch work on Android 10+)") {
            open(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${act.packageName}")), "Overlay")
        })
        box.addView(act.btn("3) Battery optimization: exempt SpanPlay") { batterySelf() })
        box.addView(act.btn("4) Battery optimization: target app (list / app info)") { batteryTarget() })
        box.addView(act.btn("Open Wi-Fi hotspot settings") { hotspot() })

        box.addView(act.header("Target app"))
        box.addView(targetText)
        box.addView(act.btn("Pick target app (shows package names)") { pickApp() })
        box.addView(act.btn("Open target app now (test)") { launchNow() })

        box.addView(act.header("Watchdog"))
        box.addView(sw)
        box.addView(TextView(act).apply { text = "Relaunch delay (seconds, default 5):" })
        box.addView(delayEdit)
        box.addView(TextView(act).apply { text = "Max retries in a row (default 5):" })
        box.addView(retryEdit)
        box.addView(act.btn("Save settings") { save() })
        box.addView(act.row(
            act.btn("Start service") { save(); prefs.serviceWanted = true; GuardianService.start(act, "button"); refreshSoon() },
            act.btn("Stop service") { prefs.serviceWanted = false; GuardianService.stop(act); refreshSoon() },
        ))

        box.addView(act.header("Event log"))
        box.addView(act.row(
            act.btn("Refresh") { refresh() },
            act.btn("Clear") { EventLog.clear(act); refresh() },
        ))
        box.addView(act.btn("Export log to USB / storage") { exportLog() })
        box.addView(act.btn("Export log via file picker") { act.exportViaPicker(logName(), EventLog.readAll(act)) })
        box.addView(logView)

        root = ScrollView(act).apply { addView(box) }
        sw.isChecked = prefs.watchdogEnabled
        delayEdit.setText(prefs.delaySec.toString())
        retryEdit.setText(prefs.maxRetries.toString())
        refresh()
    }

    private fun logName() = "SpanPlay-log-" + SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date()) + ".txt"

    private fun hasUsage(): Boolean {
        val ops = act.getSystemService(android.content.Context.APP_OPS_SERVICE) as AppOpsManager
        @Suppress("DEPRECATION")
        return ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), act.packageName) == AppOpsManager.MODE_ALLOWED
    }

    fun refresh() {
        val pm = act.getSystemService(android.content.Context.POWER_SERVICE) as PowerManager
        val tgt = prefs.targetPkg
        val sb = StringBuilder()
        sb.append("Service running      : ${GuardianService.running}\n")
        sb.append("Usage Access         : ${if (hasUsage()) "GRANTED" else "NOT granted  <-- do step 1"}\n")
        sb.append("Display over apps    : ${if (Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(act)) "granted" else "not granted (step 2)"}\n")
        sb.append("SpanPlay battery-exempt: ${if (Build.VERSION.SDK_INT < 23 || pm.isIgnoringBatteryOptimizations(act.packageName)) "yes" else "no (step 3)"}\n")
        val lb = prefs.lastBootBroadcast
        sb.append("Last boot broadcast : ${if (lb == 0L) "NEVER received" else SimpleDateFormat("MM-dd HH:mm:ss", Locale.US).format(Date(lb))}\n")
        sb.append("Device uptime        : ${android.os.SystemClock.elapsedRealtime() / 1000}s\n")
        sb.append("Android ${Build.VERSION.RELEASE} / SDK ${Build.VERSION.SDK_INT}")
        status.text = sb.toString()
        targetText.text = if (tgt == null) "(none selected)" else "${labelOf(tgt)}\n$tgt" +
            (if (act.packageManager.getLaunchIntentForPackage(tgt) == null) "\n!! not installed / no launcher activity" else "")
        logView.text = EventLog.tail(act, 150).ifBlank { "(log is empty)" }
    }

    private fun refreshSoon() {
        root.postDelayed({ refresh() }, 800)
    }

    private fun labelOf(pkg: String): String = try {
        act.packageManager.getApplicationLabel(act.packageManager.getApplicationInfo(pkg, 0)).toString()
    } catch (_: Throwable) { "?" }

    private fun save() {
        prefs.watchdogEnabled = sw.isChecked
        prefs.delaySec = delayEdit.text.toString().toIntOrNull() ?: 5
        prefs.maxRetries = retryEdit.text.toString().toIntOrNull() ?: 5
        delayEdit.setText(prefs.delaySec.toString())
        retryEdit.setText(prefs.maxRetries.toString())
        EventLog.add(act, "Settings saved: watchdog=${prefs.watchdogEnabled} delay=${prefs.delaySec}s retries=${prefs.maxRetries} target=${prefs.targetPkg}")
        Toast.makeText(act, "Saved", Toast.LENGTH_SHORT).show()
        refresh()
    }

    private fun pickApp() {
        val pm = act.packageManager
        val apps = pm.getInstalledApplications(0)
            .filter { pm.getLaunchIntentForPackage(it.packageName) != null && it.packageName != act.packageName }
            .map { Pair(pm.getApplicationLabel(it).toString(), it.packageName) }
            .sortedBy { it.first.lowercase() }
        val items = apps.map { "${it.first}\n${it.second}" }
        val filter = EditText(act).apply { hint = "type to filter (name or package)" }
        val list = ListView(act)
        val adapter = ArrayAdapter(act, android.R.layout.simple_list_item_1, items.toMutableList())
        list.adapter = adapter
        filter.addTextChangedListener(object : android.text.TextWatcher {
            override fun afterTextChanged(s: android.text.Editable?) {
                val q = s.toString().trim().lowercase()
                adapter.clear()
                adapter.addAll(items.filter { it.lowercase().contains(q) })
            }
            override fun beforeTextChanged(s: CharSequence?, st: Int, c: Int, a: Int) {}
            override fun onTextChanged(s: CharSequence?, st: Int, b: Int, c: Int) {}
        })
        val col = LinearLayout(act).apply {
            orientation = LinearLayout.VERTICAL
            addView(filter)
            addView(list, LinearLayout.LayoutParams(-1, act.dp(360)))
        }
        val dlg = AlertDialog.Builder(act).setTitle("Pick the target app (${apps.size} apps)").setView(col)
            .setNegativeButton("Cancel", null).create()
        list.setOnItemClickListener { _, _, pos, _ ->
            val pkg = adapter.getItem(pos)!!.substringAfter('\n')
            prefs.targetPkg = pkg
            EventLog.add(act, "Target app set to $pkg")
            dlg.dismiss()
            refresh()
        }
        dlg.show()
    }

    private fun launchNow() {
        val t = prefs.targetPkg ?: return Toast.makeText(act, "Pick a target first", Toast.LENGTH_SHORT).show()
        val i = act.packageManager.getLaunchIntentForPackage(t)
        if (i == null) Toast.makeText(act, "No launch intent for $t", Toast.LENGTH_LONG).show()
        else { EventLog.add(act, "Manual launch of $t"); act.startActivity(i) }
    }

    private fun open(i: Intent, what: String) {
        try { act.startActivity(i) } catch (t: Throwable) {
            EventLog.add(act, "Cannot open $what settings: $t")
            Toast.makeText(act, "This unit has no '$what' screen: $t", Toast.LENGTH_LONG).show()
        }
    }

    private fun batterySelf() {
        try {
            act.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${act.packageName}")))
        } catch (_: Throwable) {
            open(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS), "Battery optimization")
        }
    }

    private fun batteryTarget() {
        val t = prefs.targetPkg
        // Android only lets an app request its OWN exemption, so for the target we open the system list
        // (choose "All apps" there) and fall back to the target's App Info page.
        try {
            act.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        } catch (_: Throwable) {
            if (t != null) open(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$t")), "App info")
        }
        if (t != null) Toast.makeText(act, "Find: ${labelOf(t)} ($t)", Toast.LENGTH_LONG).show()
    }

    private fun hotspot() {
        val tries = listOf(
            Intent().setComponent(ComponentName("com.android.settings", "com.android.settings.TetherSettings")),
            Intent().setComponent(ComponentName("com.android.settings", "com.android.settings.Settings\$TetherSettingsActivity")),
            Intent(Settings.ACTION_WIRELESS_SETTINGS),
            Intent(Settings.ACTION_WIFI_SETTINGS),
        )
        for (i in tries) {
            try { act.startActivity(i); EventLog.add(act, "Opened hotspot settings via ${i.component ?: i.action}"); return } catch (_: Throwable) {}
        }
        Toast.makeText(act, "No hotspot settings screen found", Toast.LENGTH_LONG).show()
    }

    private fun exportLog() {
        val paths = Exporter.export(act, logName(), EventLog.readAll(act))
        val msg = if (paths.isEmpty()) "Could not write anywhere - use 'Export log via file picker'."
        else "Saved to:\n" + paths.joinToString("\n")
        Toast.makeText(act, msg, Toast.LENGTH_LONG).show()
        EventLog.add(act, "Log export: ${paths.size} location(s)")
        refresh()
    }
}
