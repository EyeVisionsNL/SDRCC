package nl.eyevisions.sdrcc.mobile;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;

public class StationAddressTest {
    @Test public void plainIpv4DefaultsTo8080() {
        assertEquals("http://192.168.1.50:8080/static/mobile/index.html",
            StationAddress.parse("192.168.1.50").toString());
    }
    @Test public void explicitPortPreserved() {
        assertEquals("http://192.168.1.50:8090/static/mobile/index.html",
            StationAddress.parse("http://192.168.1.50:8090/").toString());
    }
    @Test public void acceptsLocalDns() {
        assertEquals("http://eyevisions.local:8080/static/mobile/index.html",
            StationAddress.parse("eyevisions.local").toString());
    }
    @Test public void acceptsTailscaleHostWithoutEnablingIt() {
        assertEquals("http://station.tailnet.ts.net:8080/static/mobile/index.html",
            StationAddress.parse("station.tailnet.ts.net").toString());
    }
    @Test public void stripsOuterWhitespace() {
        assertEquals("http://minipc:8080/static/mobile/index.html",
            StationAddress.parse("  MINIPC:8080  ").toString());
    }
    private static void rejected(String input) {
        try { StationAddress.parse(input); fail("Expected rejection: " + input); }
        catch (IllegalArgumentException expected) { /* intentional */ }
    }
    @Test public void noHttpsInHttpBeta() { rejected("https://example.org"); }
    @Test public void noInternetPath() { rejected("192.168.1.2:8080/admin"); }
    @Test public void noQueries() { rejected("192.168.1.2:8080/?mode=admin"); }
    @Test public void noCredentials() { rejected("http://u:p@192.168.1.2:8080"); }
    @Test public void noJavascript() { rejected("javascript:alert(1)"); }
    @Test public void noFileScheme() { rejected("file:///etc/passwd"); }
    @Test public void noInvalidPort() { rejected("192.168.1.2:99999"); }
    @Test public void noMissingHost() { rejected("http:///"); }
    @Test public void noWhitespaceInHost() { rejected("my host"); }
    @Test public void noEmptyAddress() { rejected("  "); }
    @Test public void noDoubleDots() { rejected("test..local"); }
}
