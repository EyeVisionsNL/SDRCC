# 📱 SDRCC Mobile

Your SDRCC computer runs the receivers; Android connects to it for maps, audio and selected controls.

## 1. Install and connect

Download the [official signed SDRCC Mobile APK](https://github.com/EyeVisionsNL/SDRCC/releases/download/sdrcc-mobile-v7/SDRCC-Mobile.apk) on Android 8 or newer. Install it and enter your SDRCC computer's address, e.g. `192.168.1.50:8080` (example).

![Connection screen](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/android-startup.webp)

## 2. Turn on map plugins

Open **Marine** and the AIS map's plugin selector. Enable **VTS sector** and **SDRCC ATIS** where installed.

A matched vessel **highlights without moving the map**. Tap the ship for details.

<img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/android-marine-control.webp" alt="Marine controls" width="240"> <img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/android-ais-map.webp" alt="AIS map with sectors" width="240"> <img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/android-atis-photo.webp" alt="ATIS match and vessel photograph" width="240">

## 3. Check map addresses

Go to **System → Settings → Map Connections**. Enter reachable addresses for SDRCC, AIS-catcher and ADS-B. Use your own station IP instead of the example above.

Away from home? Connect phone and SDRCC computer to the same private **Tailscale** network. Use the **computer's Tailscale IP** for the station and maps. [Full Android guide](https://github.com/EyeVisionsNL/SDRCC/blob/main/android/README.md).

## 4. Audio and updates

Listen and replay Marine recordings, use the ADS-B map and view available satellite controls.

Tap **↓** or **App-update controleren** to download and install a signed Android update over the existing app.

**The Android button updates only the app.** Update the SDRCC computer under **System → Advanced Maintenance**.

<img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/android-recordings.webp" alt="Recent recordings" width="240"> <img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/e807e4aa5ca56bb72dc76efbea117077be94ce0a/images/android-settings.webp" alt="Settings" width="240">
