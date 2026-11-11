import groovy.json.JsonSlurper

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Конфіг Firebase для клієнта береться з google-services.json (він не секретний:
// Google сам вшиває ці значення в кожен застосунок). Плагін google-services не потрібен.
val fb: Map<String, String> = run {
    val f = file("google-services.json")
    if (!f.exists()) return@run emptyMap()
    @Suppress("UNCHECKED_CAST")
    val j = JsonSlurper().parse(f) as Map<String, Any?>
    val info = j["project_info"] as Map<String, Any?>
    val client = (j["client"] as List<Map<String, Any?>>).first {
        ((it["client_info"] as Map<String, Any?>)["android_client_info"] as Map<String, Any?>)["package_name"] == "ua.alert.kyiv"
    }
    mapOf(
        "appId" to ((client["client_info"] as Map<String, Any?>)["mobilesdk_app_id"] as String),
        "apiKey" to (((client["api_key"] as List<Map<String, Any?>>).first())["current_key"] as String),
        "projectId" to (info["project_id"] as String),
        "senderId" to (info["project_number"] as String),
    )
}

android {
    namespace = "ua.alert.kyiv"
    compileSdk = 35

    defaultConfig {
        applicationId = "ua.alert.kyiv"
        minSdk = 26
        targetSdk = 35
        versionCode = (System.getenv("VERSION_CODE") ?: "1").toInt()
        versionName = "1.0." + (System.getenv("VERSION_CODE") ?: "1")
        buildConfigField("String", "FB_APP_ID", "\"${fb["appId"] ?: ""}\"")
        buildConfigField("String", "FB_API_KEY", "\"${fb["apiKey"] ?: ""}\"")
        buildConfigField("String", "FB_PROJECT_ID", "\"${fb["projectId"] ?: ""}\"")
        buildConfigField("String", "FB_SENDER_ID", "\"${fb["senderId"] ?: ""}\"")
    }

    signingConfigs {
        create("release") {
            val ks = System.getenv("KEYSTORE_FILE")
            if (ks != null && file(ks).exists()) {
                storeFile = file(ks)
                storePassword = System.getenv("KEYSTORE_PASSWORD")
                keyAlias = "kyivalert"
                keyPassword = System.getenv("KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            val rel = signingConfigs.getByName("release")
            signingConfig = if (rel.storeFile != null) rel else signingConfigs.getByName("debug")
        }
    }
    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(platform("com.google.firebase:firebase-bom:33.7.0"))
    implementation("com.google.firebase:firebase-messaging")
}
