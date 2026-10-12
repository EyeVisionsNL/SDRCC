package nl.eyevisions.sdrcc.mobile;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Read-only validation of the host typed by the station operator.
 * No internet discovery, port scans or service reconfiguration.
 */
public final class StationAddress {
    private static final int DEFAULT_PORT = 8080;
    private static final Pattern HOST = Pattern.compile(
        "[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?"
    );

    private StationAddress() {}

    public static URI parse(String entered) {
        if (entered == null) {
            throw new IllegalArgumentException("Vul het IP-adres van je mini-pc in.");
        }
        String text = entered.trim();
        if (text.isEmpty()) {
            throw new IllegalArgumentException("Vul het IP-adres van je mini-pc in.");
        }
        if (!text.contains("://")) {
            text = "http://" + text;
        }
        final URI uri;
        try {
            uri = new URI(text);
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("Gebruik bijvoorbeeld 192.168.1.50:8080.");
        }
        if (!"http".equalsIgnoreCase(uri.getScheme())) {
            throw new IllegalArgumentException("Deze beta gebruikt HTTP via wifi of een VPN.");
        }
        String host = uri.getHost();
        if (host == null || !HOST.matcher(host).matches() || host.contains("..")) {
            throw new IllegalArgumentException("Gebruik een geldig IP-adres of een lokale hostnaam.");
        }
        int port = uri.getPort();
        if (port == -1) {
            port = DEFAULT_PORT;
        }
        if (port < 1 || port > 65535 ||
                uri.getRawUserInfo() != null || uri.getRawQuery() != null ||
                uri.getRawFragment() != null ||
                (uri.getRawPath() != null && !uri.getRawPath().isEmpty()
                        && !"/".equals(uri.getRawPath()))) {
            throw new IllegalArgumentException("Gebruik alleen het adres en eventueel de poort.");
        }
        String canonicalHost = host.toLowerCase(Locale.ROOT);
        return URI.create("http://" + canonicalHost + ":" + port
                + "/static/mobile/index.html");
    }
}
