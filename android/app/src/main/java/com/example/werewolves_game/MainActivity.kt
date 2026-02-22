package com.example.werewolves_game

import android.content.ClipboardManager
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.android.AndroidPlatform
import com.chaquo.python.Python
import com.chaquo.python.PyException
import com.google.android.material.textfield.TextInputEditText
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.BarcodeEncoder
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {
    // Keep reference to the thread so we know if it's running
    private var serverThread: Thread? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // 1. Setup UI Elements
        val btnStart = findViewById<Button>(R.id.btnStart)
        val btnStop = findViewById<Button>(R.id.btnStop)
        val tvStatus = findViewById<TextView>(R.id.tvStatus)
        val etPort = findViewById<TextInputEditText>(R.id.etPort)

        // 2. Request Battery Permission (Prevent server killing)
        checkBatteryOptimization()

        // 3. Initialize Python
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }

        setupPythonLogging()

        // 4. Start Button Logic
        btnStart.setOnClickListener {
            val portText = etPort.text.toString()
            if (portText.isEmpty()) {
                etPort.error = "Enter a $@%^ port#!"
                return@setOnClickListener
            }

            // 2. Safety Check: Is Wi-Fi actually on?
            if (!isWifiConnected()) {
                Toast.makeText(this, "Connect to Wi-Fi to start server", Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }

            // Disable button so they don't click it twice
            btnStart.visibility = View.GONE
            etPort.isEnabled = false
            btnStop.visibility = View.VISIBLE

            // Get IP Address
            val ipAddress = getWifiIpAddress()
            val fullUrl = "http://$ipAddress:$portText"

            val ivQRCode = findViewById<ImageView>(R.id.ivQRCode)
            try {
                val barcodeEncoder = BarcodeEncoder()
                // Generate a 500x500 pixel QR code bitmap
                val bitmap: Bitmap = barcodeEncoder.encodeBitmap(fullUrl, BarcodeFormat.QR_CODE, 500, 500)
                ivQRCode.setImageBitmap(bitmap)
                ivQRCode.visibility = View.VISIBLE // Show the QR code
            } catch (e: Exception) {
                Log.e("QR_ERROR", e.message ?: "Failed to generate QR")
            }

            // Update UI text
            tvStatus.text = "Game Running at:\n$fullUrl"

            tvStatus.setOnClickListener {
                if (tvStatus.text.toString().contains("http")) {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(fullUrl)))
                }
            }
            tvStatus.setOnLongClickListener {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = ClipData.newPlainText("Werewolves URL", fullUrl)
                clipboard.setPrimaryClip(clip)
                Toast.makeText(this, "URL Copied!", Toast.LENGTH_SHORT).show()
                true
            }
            // Start Python in a background thread
            serverThread = thread {
                try {
                    appendLog("Initializing Python Instance...")
                    val python = Python.getInstance()
                    appendLog("Loading app.py module...")
                    val pythonModule = python.getModule("app")

                    appendLog("Starting Flask-SocketIO server on port $portText...")
                    pythonModule.callAttr("run_server", portText.toInt())
                } catch (e: PyException) {
                    appendLog("FATAL PYTHON CRASH: ${e.message}")
                    runOnUiThread {
                        tvStatus.text = "Python Crash:\n${e.message}"
                        resetUI(btnStart, btnStop, tvStatus, etPort)
                    }
                } catch (e: Exception) {
                    appendLog("JAVA THREAD ERROR: ${e.message}")
                    runOnUiThread {
                        tvStatus.text = "Java Error: ${e.message}"
                        resetUI(btnStart, btnStop, tvStatus, etPort)
                    }
                }
            }
        }

        btnStop.setOnClickListener {
            val portText = etPort.text.toString()
            val currentIp = getWifiIpAddress()

            // We "Stop" by sending a request to the Python shutdown route
            thread {
                try {
                    val url = URL("http://${currentIp}:$portText/shutdown")
                    val connection = url.openConnection() as HttpURLConnection
                    connection.requestMethod = "POST"
                    connection.connectTimeout = 2000 // Don't hang forever
                    connection.readTimeout = 2000

                    // This triggers the /shutdown route in app.py
                    val responseCode = connection.responseCode

                    runOnUiThread {
                        if (responseCode == 200) {
                            Toast.makeText(this, "Server Stopped", Toast.LENGTH_SHORT).show()
                            resetUI(btnStart, btnStop, tvStatus,etPort)
                        } else {
                            tvStatus.text = "Status: Error $responseCode"
                            // Force UI reset anyway if the server is unreachable
                            resetUI(btnStart, btnStop, tvStatus, etPort)
                        }
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        Toast.makeText(this, "Server unreachable, UI reset", Toast.LENGTH_SHORT).show()
                        resetUI(btnStart, btnStop, tvStatus,etPort)
                    }
                }
            }
        }
    }

    private fun setupPythonLogging() {
        val python = Python.getInstance()
        // Pass 'this' (the Activity) to Python so it can call appendLog
        python.getModule("builtins").put("mainActivity", this)

        python.execute("""
            import sys
            from android.util import Log
            import mainActivity

            class LogStream:
                def __init__(self, tag, is_stdout=True):
                    self.tag = tag
                    self.is_stdout = is_stdout
                def write(self, s):
                    if s.strip():
                        # 1. Log to Android System (for adb logcat)
                        Log.i(self.tag, s)
                        # 2. Log to App UI
                        mainActivity.appendLog(s)
                def flush(self):
                    pass

            sys.stdout = LogStream("python.stdout", True)
            sys.stderr = LogStream("python.stderr", False)
        """.trimIndent())
    }

    private fun isWifiConnected(): Boolean {
        val wifiManager = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        return wifiManager.isWifiEnabled && wifiManager.connectionInfo.networkId != -1
    }

    private fun resetUI(start: Button, stop: Button, status: TextView, portInput: TextInputEditText) {
        start.visibility = View.VISIBLE
        start.isEnabled = true
        start.text = "Start Server"
        stop.visibility = View.GONE
        status.text = "Status: Stopped"
        portInput.isEnabled = true
        status.setOnClickListener(null)

        val ivQRCode = findViewById<ImageView>(R.id.ivQRCode)
        ivQRCode.visibility = View.GONE
    }

    private fun getWifiIpAddress(): String {
        val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val ip = wifiManager.connectionInfo.ipAddress
        // Convert integer IP to standard format (e.g. 192.168.1.5)
        return String.format("%d.%d.%d.%d",
            (ip and 0xff),
            (ip shr 8 and 0xff),
            (ip shr 16 and 0xff),
            (ip shr 24 and 0xff))
    }

    private fun appendLog(message: String) {
        runOnUiThread {
            val tvDebugLog = findViewById<TextView>(R.id.tvDebugLog)
            val svLog = findViewById<android.widget.ScrollView>(R.id.svLog)

            // Append the message with a timestamp
            val timestamp = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault()).format(java.util.Date())
            tvDebugLog.append("\n[$timestamp] $message")

            // Auto-scroll to the bottom so the latest log is always visible
            svLog.post { svLog.fullScroll(View.FOCUS_DOWN) }
        }
    }


    private fun checkBatteryOptimization() {
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        val packageName = packageName
        if (!powerManager.isIgnoringBatteryOptimizations(packageName)) {
            try {
                val intent = Intent()
                intent.action = Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS
                intent.data = Uri.parse("package:$packageName")
                startActivity(intent)
            } catch (e: Exception) {
                // Some devices block this intent
                Toast.makeText(this, "Enable 'Unrestricted Battery' so server can still work in background.", Toast.LENGTH_LONG).show()
            }
        }
    }
}
