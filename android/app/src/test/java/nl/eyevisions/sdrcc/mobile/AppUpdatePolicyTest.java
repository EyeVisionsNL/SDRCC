package nl.eyevisions.sdrcc.mobile;

import org.junit.Test;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class AppUpdatePolicyTest {
    private static String release(int code) {
        return "https://github.com/EyeVisionsNL/SDRCC/releases/download/"
                + "sdrcc-mobile-v" + code + "/SDRCC-Mobile.apk";
    }

    @Test public void firstUnpublishedFeedIsNotAnUpdate() {
        assertEquals(AppUpdatePolicy.Status.UNPUBLISHED,
                AppUpdatePolicy.evaluate(5, 0, "", ""));
    }

    @Test public void newerSignedReleaseCanBeOffered() {
        assertEquals(AppUpdatePolicy.Status.AVAILABLE,
                AppUpdatePolicy.evaluate(5, 6, "1.9.0-rc1", release(6)));
    }

    @Test public void currentAndOlderBuildsDoNotPrompt() {
        assertEquals(AppUpdatePolicy.Status.UP_TO_DATE,
                AppUpdatePolicy.evaluate(6, 6, "1.9.0-rc1", release(6)));
        assertEquals(AppUpdatePolicy.Status.UP_TO_DATE,
                AppUpdatePolicy.evaluate(7, 6, "1.9.0-rc1", release(6)));
    }

    @Test public void mismatchedCodeAndAssetTagAreRejected() {
        assertEquals(AppUpdatePolicy.Status.INVALID,
                AppUpdatePolicy.evaluate(5, 7, "2.0.0", release(6)));
    }

    @Test public void missingAssetAndMissingNameAreRejected() {
        assertEquals(AppUpdatePolicy.Status.INVALID,
                AppUpdatePolicy.evaluate(5, 6, "1.9.0-rc1", ""));
        assertEquals(AppUpdatePolicy.Status.INVALID,
                AppUpdatePolicy.evaluate(5, 6, "", release(6)));
        assertEquals(AppUpdatePolicy.Status.INVALID,
                AppUpdatePolicy.evaluate(5, 0, "2.0.0", release(6)));
    }

    @Test public void foreignHostsAndUrlTricksAreRejected() {
        assertFalse(AppUpdatePolicy.trustedReleaseUrl(6,
                "https://github.com.attacker.example/EyeVisionsNL/SDRCC/releases/download/sdrcc-mobile-v6/SDRCC-Mobile.apk"));
        assertFalse(AppUpdatePolicy.trustedReleaseUrl(6, release(6) + "?download=1"));
        assertFalse(AppUpdatePolicy.trustedReleaseUrl(6, release(6) + "#fragment"));
        assertFalse(AppUpdatePolicy.trustedReleaseUrl(6, "http://github.com/EyeVisionsNL/SDRCC/releases/download/sdrcc-mobile-v6/SDRCC-Mobile.apk"));
        assertTrue(AppUpdatePolicy.trustedReleaseUrl(6, release(6)));
    }

    @Test public void malformedVersionNumbersAreRejected() {
        assertEquals(AppUpdatePolicy.Status.INVALID,
                AppUpdatePolicy.evaluate(5, -1, "2.0.0", release(6)));
        assertEquals(AppUpdatePolicy.Status.INVALID,
                AppUpdatePolicy.evaluate(5, 1000001, "2.0.0", release(6)));
        assertEquals(AppUpdatePolicy.Status.INVALID,
                AppUpdatePolicy.evaluate(5, 6, "not-a-version", release(6)));
    }
}
