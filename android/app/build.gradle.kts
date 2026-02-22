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
        versionName = System.getenv("VERSION_NAME") ?: "1.0"
        resConfigs("en", "es", "de")

        ndk {
            // Python 3.8 supports ALL of these, so this will work on old and new phones
            //abiFilters.add("armeabi-v7a")
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
            isMinifyEnabled = false
            isShrinkResources = false
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

    sourceSets {
        getByName("main") {
            // Tells Chaquopy to look in the root folder of your GitHub repository
            srcDir("../../")

            // EXPLICITLY INCLUDE ALL NECESSARY FILES:
            include("app.py")
            include("config.py")
            include("game_engine.py")
            include("roles.py")
            include(".env.werewolves")

            // INCLUDE FOLDERS (Using ** to get all files inside them)
            include("static/**")
            include("templates/**")
            include("img/**")

            // EXCLUDE HEAVY/UNNECESSARY FOLDERS SO THE APK DOESN'T BLOAT
            exclude(".venv/**")
            exclude("android/**")
            exclude(".git/**")
            exclude("__pycache__/**")
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

