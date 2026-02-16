plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.example.werewolves_game"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.werewolves_game"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        resConfigs("en", "es", "de")

        ndk {
            // Python 3.8 supports ALL of these, so this will work on old and new phones
            abiFilters.add("armeabi-v7a")
            abiFilters.add("arm64-v8a")
            //abiFilters.add("x86")
            //abiFilters.add("x86_64")
        }
    }

    signingConfigs {
        create("release") {
            // 1. Try to read from Environment Variables (GitHub Actions)
            val envKeystore = System.getenv("SIGNING_KEY_STORE_PATH")
            if (envKeystore != null) {
                storeFile = file(envKeystore)
                storePassword = System.getenv("SIGNING_STORE_PASSWORD")
                keyAlias = System.getenv("SIGNING_KEY_ALIAS")
                keyPassword = System.getenv("SIGNING_KEY_PASSWORD")
            } else {
                // 2. Fallback for Local Builds (Optional: if you build release locally)
                // storeFile = file("werewolf_key.jks")
                // storePassword = "your_local_password"
                // keyAlias = "werewolf_key"
                // keyPassword = "your_local_password"
            }
        }
    }

    buildTypes {
        getByName("release") {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    // This allows you to use Java 8 features (needed for some libraries)
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
    kotlinOptions {
        jvmTarget = "1.8"
    }
}

chaquopy {
    defaultConfig {
        version = "3.10"
        pip {
            install("flask")
            install("flask-socketio")
            install("jinja2")
            install("python-dotenv")
        }
    }
}

// THIS BLOCK WAS MISSING. It provides the UI themes.
dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0") // Fixes "Theme.Material3" error
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
}

// AUTOMATION: Copy Python files from Root Project to Android App before building
tasks.register<Copy>("syncPythonFiles") {
    // 1. Where to copy FROM (Your Root Directory, 3 levels up from this file)
    from("../../../") {
        include("*.py")           // app.py, config.py, etc.
        include("templates/*.html")   // HTML files
        include("static/**")      // JSON translations
        include("img/favicon.ico")         // Icon
        include("img/ic_launcher_werewolf.png")         // Icon
        //include(".env.werewolves") // an Android version of .env.werewolves is already there.
        exclude("venv/**", ".git/**", "android/**") // Don't copy junk
    }

    // 2. Where to copy TO
    into("src/main/python")

    // 3. Print a message so you know it worked
    doFirst {
        println("🔥 SYNCING PYTHON FILES FROM ROOT TO ANDROID...")
    }
}

// 4. Force this task to run before Chaquopy processes Python
tasks.named("generateDebugPythonRequirements").configure {
    dependsOn("syncPythonFiles")
}
tasks.named("generateReleasePythonRequirements").configure {
    dependsOn("syncPythonFiles")
}
