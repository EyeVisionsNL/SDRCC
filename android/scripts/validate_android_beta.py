#!/usr/bin/env python3
"""Offline static regression checks for SDRCC Android beta (no SDK required)."""
from __future__ import annotations

from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ANDROID = Path(__file__).resolve().parents[1]
REPO = ANDROID.parent
NS = "{http://schemas.android.com/apk/res/android}"


def require(condition: bool, why: str) -> None:
    if not condition:
        raise AssertionError(why)


def validate() -> None:
    project = ANDROID / "app"
    manifest = ET.parse(project / "src/main/AndroidManifest.xml").getroot()
    permissions = [el.attrib.get(NS + "name") for el in manifest.findall("uses-permission")]
    require(permissions == ["android.permission.INTERNET"],
            "Only Android INTERNET permission is allowed")
    app = manifest.find("application")
    require(app is not None, "Missing Android application")
    require(app.attrib.get(NS + "allowBackup") == "false",
            "Beta app must not back up private server host settings")
    require(app.attrib.get(NS + "usesCleartextTraffic") == "true",
            "Current SDRCC and AIS-Catcher require private HTTP")
    require(app.attrib.get(NS + "networkSecurityConfig") ==
            "@xml/network_security_config", "Missing documented HTTP policy")
    activities = app.findall("activity")
    require(len(activities) == 1, "Exactly one launcher activity expected")
    activity = activities[0]
    require(activity.attrib.get(NS + "name") == ".MainActivity",
            "Wrong native entry activity")
    require(activity.attrib.get(NS + "exported") == "true",
            "Android 12+ launcher requires android:exported")
    config = ET.parse(project / "src/main/res/xml/network_security_config.xml").getroot()
    base = config.find("base-config")
    require(base is not None and base.attrib.get("cleartextTrafficPermitted") == "true",
            "Private dynamic LAN/VPN cleartext policy missing")
    icon_manifest = ET.parse(
        project / "src/main/res/mipmap-anydpi-v26/ic_launcher.xml").getroot()
    require(icon_manifest.find("foreground").attrib.get(NS + "drawable") ==
            "@drawable/sdrcc_logo", "Launcher must use the actual SDRCC logo")
    logo = project / "src/main/res/drawable-nodpi/sdrcc_logo.png"
    old_logo = REPO / "dashboard/static/assets/sdrcc-favicon.png"
    require(logo.is_file() and logo.read_bytes() == old_logo.read_bytes(),
            "Android icon differs from the established SDRCC logo")

    java = (project / "src/main/java/nl/eyevisions/sdrcc/mobile/"
            "MainActivity.java").read_text(encoding="utf-8")
    host = (project / "src/main/java/nl/eyevisions/sdrcc/mobile/"
            "StationAddress.java").read_text(encoding="utf-8")
    require("new WebView(this)" in java and "webView.loadUrl(currentPageUrl)" in java,
            "Must load existing SDRCC Mobile rather than fork controls")
    require("StationAddress.parse(" in java and "getSharedPreferences(" in java,
            "No operator-set local server address")
    require("port == currentPort || port == 8119 || port == 80" in java,
            "The AIS and ADS-B map ports must stay compatible")
    for prohibited in ("addJavascriptInterface(", "setAllowFileAccess(true)",
                       "setAllowUniversalAccessFromFileURLs(true)",
                       "setMediaPlaybackRequiresUserGesture(false)"):
        require(prohibited not in java, "Unsafe WebView capability: " + prohibited)
    require("request.deny()" in java and "handler.cancel()" in java,
            "Camera/microphone/certificate protection missing")
    require("onJsConfirm(" in java and "onJsAlert(" in java,
            "Existing server confirmation and alert dialogs must remain usable")
    require("Intent.ACTION_VIEW" in java, "Credit links need external browser")
    require("RadarView(this)" in java, "SDRCC native radar splash missing")
    require('changeHostButton.setVisibility(View.VISIBLE);' in java,
            "The host editor must be reachable while connecting")
    require('Button clearAddress = button("× Wissen");' in java,
            "The operator must have an explicit way to clear a stored address")
    require("input.setShowSoftInputOnFocus(true)" in java,
            "Android host text field must open the keyboard")
    require("keyboard.showSoftInput(input," in java,
            "Operator must be able to request keyboard input")
    require(activity.attrib.get(NS + "windowSoftInputMode") ==
            "adjustResize|stateAlwaysHidden", "IP field must remain visible with keyboard")
    require("static/mobile/index.html" in host, "Wrong SDRCC Mobile endpoint")
    require("getPackageInfo(getPackageName(), 0).versionName" in java,
            "Native UI must read version from installed APK")
    require("probeStationAfterWebError(view)" in java and
            "getErrorCode()" in java and "getDescription()" in java and
            "new URL(target).openConnection()" in java and
            "setInstanceFollowRedirects(false)" in java,
            "VPN/WebView main-frame diagnostic must report actual errors without redirect")
    require("via wifi of een privé-Tailscale-VPN" in java and
            "Controleer het IP-adres en de wifi-verbinding." not in java,
            "Obsolete Wi-Fi-only connection errors must be removed")
    require('Button update = button("↓");' in java and
            "checkForAppUpdate()" in java and
            'Button updateApp = button("↓ App-update controleren");' in java,
            "App update button must be available when connected and disconnected")
    require('APP_UPDATE_FEED' in java and
            'APP_UPDATE_MAX_BYTES' in java and
            'trustedAndroidApkUrl(link)' in java and
            'setInstanceFollowRedirects(false)' in java and
            '"APK openen"' in java and
            'new Thread(() ->' in java,
            "Update must verify a bounded public feed and ask before browser APK handoff")
    update_feed = (ANDROID / "update.json").read_text(encoding="utf-8")
    import json
    feed = json.loads(update_feed)
    require(set(feed) == {"version_code", "version_name", "apk_url"},
            "Update feed has unexpected fields")
    code = feed["version_code"]
    url = feed["apk_url"]
    require(type(code) is int and code >= 0, "Published app version must be numeric")
    if code == 0:
        require(feed["version_name"] == "" and url == "",
                "Unpublished Android app feed must have no download")
    else:
        import re
        require(re.fullmatch(
            rf"https://github[.]com/EyeVisionsNL/SDRCC/releases/download/sdrcc-mobile-v{code}/SDRCC-Mobile[.]apk",
            url) is not None and bool(feed["version_name"]),
            "Published APK must be an exact matching versioned GitHub release")
    signed_release = (REPO / ".github/workflows/android-release.yml").read_text(encoding="utf-8")
    require("workflow_dispatch:" in signed_release and
            "apksigner" in signed_release and
            "SDRCC_ANDROID_KEYSTORE_BASE64" in signed_release and
            "gh release create" in signed_release and
            "android/update.json" in signed_release and
            "git push origin HEAD:develop" in signed_release,
            "Stable signed release publishing contract is missing")
    require('ANDROID  ·  0.1 BETA' not in java and
            'SDRCC Android  ·  BETA' not in java,
            "Stale hard-coded beta label found")
    gradle = (project / "build.gradle").read_text(encoding="utf-8")
    require("versionName '0.1.0-beta2'" in gradle and
            "versionCode 5" in gradle,
            "Missing Android 0.1.0-beta2 version bump")
    require("com.android.application" in gradle and "targetSdk 34" in gradle,
            "Unexpected Android build setup")
    require((REPO / "VERSION").read_text().strip().startswith("0.66."),
            "SDRCC server VERSION was unexpectedly changed")
    print("PASS: SDRCC Android integration and address editing regression checks")
    print("Original logo, HTTP maps, JNI-free WebView, native dialogs and"
          " safe beta permissions verified.")


if __name__ == "__main__":
    try:
        validate()
    except (AssertionError, FileNotFoundError, ET.ParseError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
