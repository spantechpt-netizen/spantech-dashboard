package com.spanplay

import android.app.AppOpsManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Process
import android.provider.Settings

/**
 * Phase A watchdog. Polls UsageStatsManager every 2 s, works out which package is in the
 * foreground, and relaunches the target app when it has been missing for `delaySec` seconds
 * (up to `maxRetries` relaunches in a row).
 */
class GuardianService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var prefs: Prefs

    private var fgPkg: String? = null
    private var lastQuery = 0L
    private var missingSince = 0L
    private var fgSince = 0L
    private var retries = 0
    private var gaveUp = false
    private var lastLoggedState = ""
    private var lastNotifText = ""
    private var accessWarned = false
    private var lastTickAt = 0L
    private var lastRestartAt = 0L

    /** Logs power / screen / USB events so we can see what the head unit does when the car is switched off and on. */
    private val powerRx = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            val up = android.os.SystemClock.elapsedRealtime() / 1000
            EventLog.add(c, "System event: ${i.action?.substringAfterLast('.')} (device uptime ${up}s)")
        }
    }

    private val tick = object : Runnable {
        override fun run() {
            try { check() } catch (t: Throwable) { EventLog.add(this@GuardianService, "Watchdog error: $t") }
            handler.postDelayed(this, POLL_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        running = true
        prefs = Prefs(this)
        createChannel()
        val n = buildNotif("Starting...")
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIF_ID, n)
        }
        val f = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON); addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_USER_PRESENT); addAction(Intent.ACTION_SHUTDOWN)
            addAction(Intent.ACTION_POWER_CONNECTED); addAction(Intent.ACTION_POWER_DISCONNECTED)
            addAction("android.hardware.usb.action.USB_DEVICE_ATTACHED")
            addAction("android.hardware.usb.action.USB_DEVICE_DETACHED")
        }
        try { registerReceiver(powerRx, f) } catch (t: Throwable) { EventLog.add(this, "powerRx register failed: $t") }
        EventLog.add(this, "Guardian service created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            EventLog.add(this, "Guardian service stopped by user")
            stopForeground(true)
            stopSelf()
            return START_NOT_STICKY
        }
        val why = intent?.getStringExtra(EXTRA_REASON) ?: "restart"
        EventLog.add(this, "Guardian service started (reason: $why)")
        handler.removeCallbacks(tick)
        handler.post(tick)
        if (prefs.restartOnWake && why in WAKE_REASONS) scheduleRestart(why)
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacks(tick)
        try { unregisterReceiver(powerRx) } catch (_: Throwable) {}
        running = false
        EventLog.add(this, "Guardian service destroyed")
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ------------------------------------------------------------------ restart on wake (no Usage Access)

    private fun scheduleRestart(why: String) {
        val t = prefs.targetPkg ?: return
        val now = System.currentTimeMillis()
        if (now - lastRestartAt < 60_000) { EventLog.add(this, "Restart-on-wake skipped (debounce), trigger: $why"); return }
        lastRestartAt = now
        EventLog.add(this, "Restart-on-wake: will restart $t in ${RESTART_DELAY_S}s (trigger: $why)")
        handler.postDelayed({
            try {
                (getSystemService(Context.ACTIVITY_SERVICE) as android.app.ActivityManager).killBackgroundProcesses(t)
                EventLog.add(this, "killBackgroundProcesses($t) requested")
            } catch (e: Throwable) { EventLog.add(this, "kill failed: $e") }
            handler.postDelayed({ launchTarget(t) }, 2000)
        }, RESTART_DELAY_S * 1000L)
    }

    // ------------------------------------------------------------------ watchdog

    private fun hasUsageAccess(): Boolean {
        val ops = getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        @Suppress("DEPRECATION")
        val mode = ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), packageName)
        return mode == AppOpsManager.MODE_ALLOWED
    }

    private fun updateForeground() {
        val usm = getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val now = System.currentTimeMillis()
        val from = if (lastQuery > 0) lastQuery else now - 10 * 60_000L
        val events = usm.queryEvents(from, now)
        val e = UsageEvents.Event()
        var maxTs = 0L
        while (events.hasNextEvent()) {
            events.getNextEvent(e)
            when (e.eventType) {
                1 -> fgPkg = e.packageName                       // ACTIVITY_RESUMED / MOVE_TO_FOREGROUND
                2, 23 -> if (fgPkg == e.packageName) fgPkg = null // PAUSED / STOPPED
            }
            if (e.timeStamp > maxTs) maxTs = e.timeStamp
        }
        if (maxTs > 0) lastQuery = maxTs + 1 else if (lastQuery == 0L) lastQuery = from
    }

    private fun check() {
        val t0 = System.currentTimeMillis()
        if (lastTickAt != 0L && t0 - lastTickAt > 15_000) {
            EventLog.add(this, "Watchdog was frozen for ${(t0 - lastTickAt) / 1000}s (device suspended / process frozen?)")
        }
        lastTickAt = t0
        val target = prefs.targetPkg
        if (target == null) { setNotif("No target app selected - open SpanPlay > Guardian"); return }
        if (!prefs.watchdogEnabled) { setNotif("Watchdog paused"); return }
        if (!hasUsageAccess()) {
            if (!accessWarned) {
                EventLog.add(this, "Usage Access NOT granted - watchdog cannot see foreground app")
                accessWarned = true
            }
            setNotif("Usage Access missing - tap to open SpanPlay")
            return
        }
        accessWarned = false
        updateForeground()

        val now = System.currentTimeMillis()
        val fg = fgPkg
        when (fg) {
            target -> {
                if (lastLoggedState != "fg") EventLog.add(this, "Target $target is in foreground")
                lastLoggedState = "fg"
                if (fgSince == 0L) fgSince = now
                missingSince = 0L
                if (now - fgSince > STABLE_MS && (retries > 0 || gaveUp)) {
                    EventLog.add(this, "Target stable for ${STABLE_MS / 1000}s - retry counter reset")
                    retries = 0; gaveUp = false
                }
                setNotif("Watching $target (OK)")
            }
            packageName -> {
                // The owner is inside SpanPlay itself; never fight him.
                missingSince = 0L; fgSince = 0L
                setNotif("Watchdog idle (SpanPlay open)")
            }
            else -> {
                fgSince = 0L
                if (missingSince == 0L) {
                    missingSince = now
                    EventLog.add(this, "Target not in foreground (current: ${fg ?: "none"}) - waiting ${prefs.delaySec}s")
                    lastLoggedState = "missing"
                }
                if (now - missingSince >= prefs.delaySec * 1000L) {
                    if (retries < prefs.maxRetries) {
                        retries++
                        launchTarget(target)
                        missingSince = now // wait another delay before trying again
                        setNotif("Relaunched target ($retries/${prefs.maxRetries})")
                    } else if (!gaveUp) {
                        gaveUp = true
                        EventLog.add(this, "Gave up after ${prefs.maxRetries} relaunches (until target is seen again)")
                        setNotif("Gave up after ${prefs.maxRetries} retries")
                    }
                }
            }
        }
    }

    private fun launchTarget(pkg: String) {
        try {
            val i = packageManager.getLaunchIntentForPackage(pkg)
            if (i == null) { EventLog.add(this, "No launch intent for $pkg (not installed?)"); return }
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
            startActivity(i)
            var note = ""
            if (Build.VERSION.SDK_INT >= 29 && !Settings.canDrawOverlays(this))
                note = " (Android 10+ may block background launches - grant 'Display over other apps')"
            EventLog.add(this, "Relaunch #$retries of $pkg requested$note")
        } catch (t: Throwable) {
            EventLog.add(this, "Relaunch of $pkg FAILED: $t")
        }
    }

    // ------------------------------------------------------------------ notification

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "SpanPlay Guardian", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    private fun buildNotif(text: String): Notification {
        val open = android.app.PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            android.app.PendingIntent.FLAG_IMMUTABLE or android.app.PendingIntent.FLAG_UPDATE_CURRENT
        )
        val b = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL)
        else @Suppress("DEPRECATION") Notification.Builder(this)
        return b.setSmallIcon(R.drawable.ic_notif)
            .setContentTitle("SpanPlay Guardian")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
    }

    private fun setNotif(text: String) {
        if (text == lastNotifText) return
        lastNotifText = text
        getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotif(text))
    }

    companion object {
        const val ACTION_STOP = "com.spanplay.STOP"
        private const val EXTRA_REASON = "reason"
        private const val CHANNEL = "guardian"
        private const val NOTIF_ID = 1
        private const val POLL_MS = 2000L
        private const val STABLE_MS = 30_000L
        private const val RESTART_DELAY_S = 20
        private val WAKE_REASONS = setOf(
            "android.intent.action.BOOT_COMPLETED", "android.intent.action.QUICKBOOT_POWERON",
            "com.htc.intent.action.QUICKBOOT_POWERON", "usb-attach"
        )

        @Volatile var running = false

        fun start(ctx: Context, reason: String) {
            val i = Intent(ctx, GuardianService::class.java).putExtra(EXTRA_REASON, reason)
            try {
                if (Build.VERSION.SDK_INT >= 26) ctx.startForegroundService(i) else ctx.startService(i)
            } catch (t: Throwable) {
                EventLog.add(ctx, "Could not start service: $t")
            }
        }

        fun stop(ctx: Context) {
            ctx.startService(Intent(ctx, GuardianService::class.java).setAction(ACTION_STOP))
        }
    }
}
