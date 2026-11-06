package com.spanplay

import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Phase 1 tab: system info + CH341 / MFi chip probe + report export. */
class ProbeTab(private val act: MainActivity) {
    private val report = StringBuilder()
    private val out: TextView
    private var running = false
    val root: ScrollView

    init {
        val box = act.vbox()
        out = act.label("", mono = true, size = 12f)
        box.addView(act.label("Phase 1 - talk to the genuine MFi chip through the CH341. READ-ONLY identification; " +
            "no authentication is started.", size = 13f))
        box.addView(act.btn("1) Show device info") { showInfo() })
        box.addView(act.btn("2) Run dongle probe (plug the dongle first)") { runProbe() })
        box.addView(act.btn("3) Export report to USB / storage") { exportReport() })
        box.addView(act.btn("3b) Export report via file picker") {
            act.exportViaPicker(reportName(), fullReport())
        })
        box.addView(out)
        root = ScrollView(act).apply { addView(box) }
        append("Ready. Press 1, then 2, then 3.\n")
    }

    private fun reportName(): String =
        "SpanPlay-report-" + SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date()) + ".txt"

    private fun fullReport(): String =
        "SpanPlay report (A1)\n" + SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date()) +
            "\n\n" + SystemInfo.report(act) + "\n" + report

    private fun append(s: String) {
        act.runOnUiThread {
            report.append(s)
            out.text = report.toString()
        }
    }

    private fun showInfo() = append("\n" + SystemInfo.report(act) + "\n")

    private fun runProbe() {
        if (running) { Toast.makeText(act, "Probe already running", Toast.LENGTH_SHORT).show(); return }
        running = true
        Thread {
            try {
                DongleProbe(act) { line -> append(line + "\n") }.run()
            } catch (t: Throwable) {
                append("PROBE CRASHED: $t\n" + t.stackTrace.take(8).joinToString("\n") + "\n")
            } finally {
                running = false
            }
        }.start()
    }

    private fun exportReport() {
        val paths = Exporter.export(act, reportName(), fullReport())
        val msg = if (paths.isEmpty()) "Could not write anywhere - use button 3b (file picker)."
        else "Saved to:\n" + paths.joinToString("\n")
        append("\n[export] $msg\n")
        EventLog.add(act, "Report export: ${paths.size} location(s)")
        Toast.makeText(act, msg, Toast.LENGTH_LONG).show()
    }
}
