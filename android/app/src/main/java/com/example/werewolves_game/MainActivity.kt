package io.github.davidchilin.werewolves_game

import android.content.ClipboardManager
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.android.AndroidPlatform
import com.chaquo.python.PyException
import com.chaquo.python.Python
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

        val tvVersion = findViewById<TextView>(R.id.tvVersion)
        val versionName = packageManager.getPackageInfo(packageName, 0).versionName
        tvVersion.text = "$versionName"

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

        // 4. Start Button Logic
        btnStart.setOnClickListener {
            val portText = etPort.text.toString()
            if (portText.isEmpty()) {
                etPort.error = "Enter a $@%^ port #!"
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
                    val python = Python.getInstance()
                    val pythonModule = python.getModule("app")
                    pythonModule.callAttr("run_server", portText)
                } catch (e: PyException) {
                    Log.e("PYTHON_CRASH", e.message ?: "Unknown Python error")
                    runOnUiThread {
                        resetUI(btnStart, btnStop, tvStatus, etPort)
                        tvStatus.text = "Python Crash:\n${e.message}"
                    }
                } catch (e: Exception) {
                    Log.e("JAVA_CRASH", e.message ?: "Unknown Java error")
                    runOnUiThread {
                        resetUI(btnStart, btnStop, tvStatus, etPort)
                        tvStatus.text = "Java Error: ${e.message}"
                    }
                }
            }
        }

        btnStop.setOnClickListener {
            Toast.makeText(this, "Closing Server...", Toast.LENGTH_SHORT).show()
            // This aggressively kills the app and instantly frees Port 5000
            finishAffinity()
            System.exit(0)
        }
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
        try {
            // Ask the OS for all active network connections (bypasses WifiManager)
            val interfaces = java.net.NetworkInterface.getNetworkInterfaces()
            for (intf in interfaces) {
                // Ignore inactive networks and the local loopback (127.0.0.1)
                if (intf.isLoopback || !intf.isUp) continue

                for (addr in intf.inetAddresses) {
                    // Find the standard IPv4 address (e.g., 192.168.x.x)
                    if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                        return addr.hostAddress ?: "0.0.0.0"
                    }
                }
            }
        } catch (e: Exception) {
            Log.e("IP_ERROR", "Error getting network IP: ${e.message}")
        }
        return "0.0.0.0"
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
                Toast.makeText(this, "Enable 'Unrestricted Battery' so game can still work in background.", Toast.LENGTH_LONG).show()
            }
        }
    }
}
