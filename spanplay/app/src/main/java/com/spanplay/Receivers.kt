package com.spanplay

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Bundle

/** Starts the guardian on BOOT_COMPLETED (and common vendor quick-boot broadcasts). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        EventLog.add(context, "Boot broadcast received: ${intent.action}")
        if (Prefs(context).serviceWanted) GuardianService.start(context, "boot")
    }
}

/** Invisible activity that receives USB_DEVICE_ATTACHED for the CH341 dongle (1a86:5512). */
class UsbAttachActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EventLog.add(this, "USB dongle 1a86:5512 attached")
        if (Prefs(this).serviceWanted) GuardianService.start(this, "usb-attach")
        finish()
    }
}
