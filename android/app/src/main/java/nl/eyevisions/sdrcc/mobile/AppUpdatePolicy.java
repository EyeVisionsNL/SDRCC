package nl.eyevisions.sdrcc.mobile;

/**
 * Pure, side-effect-free validation for the public signed Android release feed.
 * No SDRCC receiver APIs or Android permissions are involved.
 */
final class AppUpdatePolicy {
    enum Status { UNPUBLISHED, UP_TO_DATE, AVAILABLE, INVALID }

    private AppUpdatePolicy() { }

    static Status evaluate(int installedCode, int offeredCode, String versionName, String apkUrl) {
        String name = versionName == null ? "" : versionName.trim();
        String url = apkUrl == null ? "" : apkUrl.trim();

        if (offeredCode == 0 && name.isEmpty() && url.isEmpty()) {
            return Status.UNPUBLISHED;
        }
        if (offeredCode <= 0 || offeredCode > 1000000
                || !name.matches("[0-9]+[.][0-9]+(?:[.][0-9]+)?(?:-[A-Za-z0-9.]+)?")
                || !trustedReleaseUrl(offeredCode, url)) {
            return Status.INVALID;
        }
        return offeredCode > installedCode ? Status.AVAILABLE : Status.UP_TO_DATE;
    }

    /** A feed cannot offer an arbitrary URL or an APK from a different version tag. */
    static boolean trustedReleaseUrl(int versionCode, String url) {
        if (versionCode <= 0 || versionCode > 1000000 || url == null) return false;
        return url.equals("https://github.com/EyeVisionsNL/SDRCC/releases/download/"
                + "sdrcc-mobile-v" + versionCode + "/SDRCC-Mobile.apk");
    }
}
