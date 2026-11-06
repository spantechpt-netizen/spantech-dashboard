package com.spanplay

import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.Toast

/** Two tabs: "Guardian" (Phase A) and "Dongle Probe" (Phase 1). */
class MainActivity : Activity() {
    private lateinit var guardian: GuardianTab
    private lateinit var probe: ProbeTab
    private lateinit var tabGuardian: Button
    private lateinit var tabProbe: Button

    private var pendingName: String? = null
    private var pendingText: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EventLog.init(this)
        guardian = GuardianTab(this)
        probe = ProbeTab(this)

        val content = FrameLayout(this)
        content.addView(guardian.root, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        content.addView(probe.root, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)

        tabGuardian = btn("Guardian") { show(0) }
        tabProbe = btn("Dongle Probe") { show(1) }
        val bar = row(tabGuardian, tabProbe)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(bar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(content, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        setContentView(root)
        show(0)

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)

        EventLog.add(this, "App opened (SpanPlay A1)")
    }

    private fun show(i: Int) {
        guardian.root.visibility = if (i == 0) View.VISIBLE else View.GONE
        probe.root.visibility = if (i == 1) View.VISIBLE else View.GONE
        tabGuardian.setBackgroundColor(if (i == 0) Color.parseColor("#0B3D91") else Color.DKGRAY)
        tabProbe.setBackgroundColor(if (i == 1) Color.parseColor("#0B3D91") else Color.DKGRAY)
        tabGuardian.setTextColor(Color.WHITE)
        tabProbe.setTextColor(Color.WHITE)
    }

    override fun onResume() {
        super.onResume()
        guardian.refresh()
    }

    /** Save through the system file picker (lets the owner choose the USB stick). */
    fun exportViaPicker(name: String, text: String) {
        pendingName = name
        pendingText = text
        try {
            val i = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "text/plain"
                putExtra(Intent.EXTRA_TITLE, name)
            }
            @Suppress("DEPRECATION")
            startActivityForResult(i, 42)
        } catch (t: Throwable) {
            Toast.makeText(this, "No file picker on this unit: $t", Toast.LENGTH_LONG).show()
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 42 || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        try {
            contentResolver.openOutputStream(uri)?.use { it.write((pendingText ?: "").toByteArray()) }
            Toast.makeText(this, "Saved: $uri", Toast.LENGTH_LONG).show()
            EventLog.add(this, "Exported $pendingName via picker to $uri")
        } catch (t: Throwable) {
            Toast.makeText(this, "Save failed: $t", Toast.LENGTH_LONG).show()
        }
    }
}
