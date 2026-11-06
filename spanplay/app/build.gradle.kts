plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.spanplay"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.spanplay"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "A1"
    }

    // A fixed debug keystore (public, not secret) so every build has the SAME
    // signature and the APK can be updated in the car without uninstalling.
    signingConfigs {
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        getByName("debug") {
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}
