# 📱 Your station, on your phone

SDRCC Mobile connects to the SDRCC computer already running your receivers. The computer stays switched on; the phone provides remote viewing, listening and selected controls.

## 1. Install the official app

1. Use **Android 8.0 or later**.
2. Download the [official signed SDRCC Mobile v2.0.0 APK](https://github.com/EyeVisionsNL/SDRCC/releases/download/sdrcc-mobile-v7/SDRCC-Mobile.apk).
3. Open the download. Allow installation from your browser if Android asks, then tap **Install**.
4. Open SDRCC Mobile. Enter your SDRCC computer's address, such as **192.168.1.50:8080** (example), and tap **Verbinden met SDRCC**.

Use the same trusted Wi-Fi network as the computer, or a private Tailscale connection. To correct a saved address, choose **IP-adres wijzigen**, then **Adres bewerken** or **Wissen**.

<img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/android-startup.webp" alt="Station connection screen" width="260">

## 2. Enable the AIS map plugins

1. Open **Marine**.
2. Start Marine Voice and/or AIS as needed; they have independent controls.
3. Open the AIS map's **plugin selector**.
4. Enable **VTS sector** and **SDRCC ATIS**, where installed.
5. A validated ATIS/AIS match highlights the vessel. Tap it for details: the map does not automatically move or re-center.

<img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/android-marine-control.webp" alt="Marine controls" width="240"> <img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/android-ais-map.webp" alt="AIS map and VTS sectors" width="240"> <img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/android-atis-photo.webp" alt="ATIS match and vessel photograph" width="240">

## 3. Check map connections

Open **System → Settings → Map Connections**. If all services run on the same computer with standard ports, use:

| Connection | Example |
| --- | --- |
| SDRCC | http://192.168.1.50:8080 |
| AIS-Catcher Map URL | http://192.168.1.50:8119/ |
| ADS-B Map URL | http://192.168.1.50/tar1090/ |

Replace the example IP with your own computer's reachable address. If a map runs on a different computer, use that computer's address. Choose **Save Map Addresses**.

## 4. Connect away from home

Connect the SDRCC computer and Android phone to the same private Tailscale network. In SDRCC Mobile, use the **computer's Tailscale IP**, not the phone's IP. Change map addresses to reachable Tailscale addresses too if required.

Keep Tailscale connected on both devices. Test using mobile data with Wi-Fi switched off. The [detailed Android and Tailscale guide](https://github.com/EyeVisionsNL/SDRCC/blob/main/android/README.md) contains the full setup steps. No public router port forwarding is needed for this setup.

## 5. Replay recordings and use the other tabs

Replay or save recent Marine recordings while live reception continues. The aircraft tab provides ADS-B controls and the aircraft map. Satellite pages show positions, upcoming missions and received images, with selected mission controls. System shows service status and usage.

<img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/android-recordings.webp" alt="Marine recordings" width="240"> <img src="https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/android-settings.webp" alt="Mobile settings" width="240">

## 6. Update the Android app

Tap **↓** in the top toolbar, or **App-update controleren** on the connection screen. If a newer signed version is available, choose **APK openen**, download it and select **Update / Bijwerken**. Install over the existing signed app to retain settings.

Use official signed release APKs. Historical debug builds can have incompatible signing keys.

**The Android button updates only the phone app.** Update the SDRCC computer through **System → Advanced Maintenance** in the desktop dashboard. Receiver bindings, full mission planning and detailed history/analytics also remain in the desktop interface.

[[Home]] · [[Updates and troubleshooting]]
