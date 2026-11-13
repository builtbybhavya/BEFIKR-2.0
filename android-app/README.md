# BEFIKR Android app

This is a native Android Studio shell around BEFIKR's existing five-module mobile app. It loads the deployed BEFIKR web client in a locked-down WebView and adds Android SMS and location permissions for SOS. The app icon uses the existing BEFIKR icon.

## What SOS does on Android

- The app asks for SMS and location permission before the first use. After permission is granted, one SOS action submits `SOS!!- https://maps.google.com/?q=LATITUDE,LONGITUDE` by SMS to every saved trusted contact, then opens the system dialer on 112.
- If Android location is unavailable, the SMS says `SOS!!- Current location unavailable` rather than inventing a location.
- Android requires the phone owner to tap **Call** in the 112 dialer. Third-party apps cannot silently place emergency calls. Calls to saved contacts also open the phone dialer for the phone owner to confirm.
- WhatsApp uses Android's share handoff to open WhatsApp's recipient picker with the SOS text. The user chooses the recipient and taps Send; a personal WhatsApp account cannot silently send a message.
- SMS is submitted to the phone's SMS service. BEFIKR does not receive carrier delivery receipts, so the app cannot promise that the recipient received it.
- Saved contacts and account features are still served by the BEFIKR backend. The Android app needs network access to that backend; it does not turn the current SQLite development server into a public service.

## Configure the backend URL

For a release APK, deploy the BEFIKR backend and web client over HTTPS first. Then provide that public URL as the Gradle property `befikrStartUrl`. For example, from this directory in PowerShell:

```powershell
.\gradlew.bat assembleDebug -PbefikrStartUrl=https://your-befikr-host.example/
```

The first Windows build downloads the pinned Gradle 9.6.0 distribution into your user Gradle cache. The debug build defaults to `http://10.0.2.2:8000/`, which is the Android emulator address for a server running on the development computer. Start Uvicorn with `--host 0.0.0.0` for emulator testing. A phone cannot reach the computer using `127.0.0.1`; for a physical phone, use a reachable HTTPS server.

The release build deliberately fails unless `befikrStartUrl` is an HTTPS URL. Do not ship a build pointing at `127.0.0.1`, `10.0.2.2`, or a development server.

## Build an APK

Install Android Studio with JDK 17 and Android SDK Platform 36. Open this `android-app` folder as a project, allow Gradle sync, and set the Gradle property `befikrStartUrl` to the deployed HTTPS URL. In Android Studio, use **Build → Build Bundle(s) / APK(s) → Build APK(s)**. The debug APK is normally written to `app/build/outputs/apk/debug/app-debug.apk`.

For a release APK, configure a signing key in Android Studio and use a deployed HTTPS backend URL. Before publishing on Google Play, declare and obtain approval for the SMS permission use under Google's restricted SMS permission policy. Sideloaded APKs still require the user to grant Android's runtime SMS and location permissions.

## Local toolchain status

This repository currently has no Android Studio, Android SDK, or Java installed in the workspace, so an APK cannot be built here yet. The project includes a Windows Gradle bootstrap script; the Android build tools and deployed backend URL are still required to produce an installable APK.
