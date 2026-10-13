# SDRCC Android · v0.1 Beta 2

Native Android application around the **existing** SDRCC Mobile dashboard.
It is **not** a second SDRCC server, a fork of the Marine/AIS/ADS-B logic, or
the home-screen browser shortcut.

## Features

- App start screen and toolbar show the installed APK version, such as `v0.1.0 BETA 2`.
- Real Android APK, launcher icon copied from the existing SDRCC favicon and
  native SDRCC splash with a small radar sweep.
- Operator-selected hostname or IP for **HTTP :8080** (custom port is
  supported); stored only in the app's private Android preferences.
- Address can always be edited from the radar connection screen, without
  waiting for a failed connection timeout. The editor includes explicit
  **Adres bewerken** and **Wissen** controls and opens the Android keyboard.
- WebView opens the existing \`/static/mobile/index.html\`; it does not copy
  or independently reimplement Marine, ATIS/AIS match highlighting, AIS-Catcher
  :8119, tar1090 :80, recordings, Satellite or Mission controls.
- JavaScript and DOM Storage for the existing dashboard; HTML audio playback
  remains triggered by a user tap.
- Native confirmation of existing web dialogs, external photo credits opened
  in an external browser, reload and connection settings.
- No JavaScript-to-Android bridge, no file access and no camera/microphone
  permissions. Only the Internet permission is requested.

## One-tap Android app update check

The Android toolbar has a **↓** update button. The same check is available on
the connection screen if the mini-PC is temporarily unreachable.

- The app reads `android/update.json` publicly from the `develop` branch over
  HTTPS. A bounded, read-only request checks the published APK versionCode.
- If a newer *signed* APK is published, the app offers **APK openen**. Android
  opens the trusted GitHub release download in the device browser and the
  operator confirms installation. The app never silently installs a package.
- `android/update.json` starts with version_code 0 and no download link,
  because **no consistently signed Android release has yet been published**.
  The button honestly reports no published update until this is configured.
- Each published Android APK needs the **same protected release signing key**
  and a larger versionCode than the installed app. This is NOT the SDRCC
  mini-PC Update Manager. No APK/signing secrets may be committed to Git.

**Initial migration:** earlier GitHub Actions APKs are signed with temporary
debug keys. Switching to the first permanently signed APK may require
uninstalling the old beta **once**, which clears its stored mini-PC IP.
After that, later APKs signed with the same permanent key can install as upgrades.

Only publish update.json after the signed GitHub Release asset actually exists,
using a versioned GitHub release tag `sdrcc-mobile-v<versionCode>` and APK asset
named `SDRCC-Mobile.apk`. Example:

```json
{
  "version_code": 6,
  "version_name": "0.1.0-beta3",
  "apk_url": "https://github.com/EyeVisionsNL/SDRCC/releases/download/sdrcc-mobile-v6/SDRCC-Mobile.apk"
}
```

Never put an ephemeral debug APK in this update feed.

## Local wifi first

1. Confirm SDRCC Mobile works in the Android phone browser over wifi.
2. Install the **debug beta APK** from the GitHub Actions artifact, or build
   it yourself in Android Studio.
3. Open the SDRCC Mobile app. Tap **Adres bewerken**, enter your mini-PC address, for example
   \`192.168.1.50\` or \`192.168.1.50:8080\`.
4. Tap **Verbinden**. The existing live Mobile UI should appear.
5. To change the IP at any time: use **IP-adres wijzigen** during the
   radar connection screen, or the gear icon after connecting. You can clear
   the field with **Wissen**.
6. Test Marine, AIS map on :8119, ADS-B map on :80, audio, recordings,
   ATIS matching, and Mission buttons. Tap the gear icon to change host.
6. Do not configure public port forwarding to SDRCC.

**Later 4G/5G:** connect the mini-PC and phone to the *same trusted Tailscale
VPN*. Use the mini-PC's Tailscale IP/hostname in the app settings. The VPN
encrypts the transport while SDRCC and AIS-Catcher can remain on HTTP.
No VPN is installed or configured by this Android project.

## Building

Java 17, Android SDK platform 35, Android Build Tools 35.0.0, Gradle 8.9,
Android Gradle Plugin 8.7.3. Open \`android/\` as an Android Studio project
or from the \`android/\` directory run:

\`\`\`bash
gradle :app:testDebugUnitTest :app:assembleDebug
\`\`\`

The Beta 2 app-update check uses Android `versionCode 5` and retains the `0.1.0-beta2` version name. The connection screen reports the Android WebView error code, description and a bounded native HTTP HEAD probe of the configured station URL. This distinguishes VPN/app reachability failures from WebView-only failures. No receiver POST actions are retried by diagnostics.

The generated file is \`android/app/build/outputs/apk/debug/app-debug.apk\`.
The GitHub workflow **Android Beta 2 APK** builds it on pushes to \`develop\`
that touch \`android/\` and uploads the result under the workflow run's
**Artifacts** section.

This debug APK is for internal testing and is signed with the runner's
ephemeral debug certificate. **Before installing beta 2, uninstall beta 1**
if Android reports a package signature conflict. Uninstalling also resets
the saved mini-PC IP address; enter it again after installation. New CI debug
builds may have a different signing key; you may need to uninstall the
previous beta before installing another one. A future stable APK needs a private **persistent release key**
held in repository secrets, never in Git.

## Scope and security

- Only \`android/\` and \`.github/workflows/android-beta.yml\` are changed.
  Desktop SDRCC, Python receiver services, source allowlists and the marine
  overlay remain untouched. The SDRCC server's \`VERSION\` is unchanged.
- Cleartext HTTP is enabled for dynamic private LAN/VPN addresses; on a
  hostile wifi network, HTTP itself is **not authenticated or encrypted**.
  Only use trusted wifi or a private, encrypted VPN. No HTTP endpoints
  should be published on the public internet.
- JavaScript navigation is restricted at the top level to the configured
  station. External photographer-source URLs are opened by Android's browser.
  The embedded AIS/ADS-B maps and normal external photo image resources
  continue to load as the server normally serves them.
- A network error never starts/stops a receiver. No failed POST is retried by
  the Android shell. Native reload is manual; existing SDRCC Mobile network
  recovery remains authoritative.
- \`targetSdk 34\` is intentional for a sideloaded internal beta, not a
  Play Store release. Future release/Play Store builds must update target SDK
  and review edge-to-edge requirements.

## Checks

- \`app/src/test/.../StationAddressTest.java\` covers valid LAN, DNS and VPN
  host input and rejects unsafe/invalid URLs.
- \`scripts/validate_android_beta.py\` verifies the app's manifest,
  network policy and kept hardware-independent architecture.
- The GitHub Actions build runs checks and unit tests before packaging APK.
- On-device receiver and WebView tests must be performed on an Android phone;
  a CI build does not prove audio or map behavior on actual hardware.
