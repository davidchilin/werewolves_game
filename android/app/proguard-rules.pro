# 1. Protect your specific app code from being deleted or renamed
# This ensures Chaquopy can still find your Kotlin classes when Python needs them.
-keep class io.github.davidchilin.werewolves_game.** { *; }

# 2. Protect Chaquopy's internal bridge
# Chaquopy usually bundles its own rules, but this guarantees the minifier
# won't touch the core Python-to-Java translation layer.
-keep class com.chaquo.python.** { *; }

# 3. Keep all native JNI methods
# Python relies on compiled C/C++ libraries (.so files). This rule ensures
# the Java native interfaces that talk to those C files are preserved.
-keepclasseswithmembernames class * {
    native <methods>;
}

# 4. Do not warn about missing okhttp/okio references inside standard libraries
# (Very common when minifying networking apps like local servers)
-dontwarn okhttp3.**
-dontwarn okio.**

