package nl.eyevisions.sdrcc.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.content.Context;
import android.view.inputmethod.InputMethodManager;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.GeolocationPermissions;
import android.webkit.JsResult;
import android.webkit.PermissionRequest;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import android.net.http.SslError;
import java.net.URI;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;

/**
 * Android shell around SDRCC Mobile. The actual receiver/mission/ATIS controls
 * remain on the existing SDRCC server. No JavaScript bridge is exposed.
 */
public final class MainActivity extends Activity {
    private static final String PREFS = "sdrcc_android_beta";
    private static final String PREF_HOST = "station_address";
    private static final int BG = 0xFF09151D;
    private static final int SURFACE = 0xFF102330;
    private static final int ACCENT = 0xFF72D8B3;
    private static final int TEXT = 0xFFE6F2F4;
    private static final int MUTED = 0xFF9AB2B9;
    private static final long CONNECT_TIMEOUT_MS = 20000L;
    // Public update metadata is distinct from the private SDRCC receiver API.
    // Never download or execute an APK inside the app itself.
    private static final String APP_UPDATE_FEED =
            "https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/android/update.json";
    private static final int APP_UPDATE_MAX_BYTES = 16384;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private WebView webView;
    private View loadingCover;
    private TextView loadingText;
    private TextView loadingIndicator;
    private Button retryButton;
    private Button changeHostButton;
    private Runnable loadTimeout;
    private boolean pageFailed;
    private boolean updateCheckBusy;
    private String connectionErrorDetails = "";
    private String currentHost;
    private int currentPort;
    private String currentPageUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        String stored = preferences().getString(PREF_HOST, "");
        if (stored.isEmpty()) {
            showConnectionScreen(null);
        } else {
            try {
                loadStation(StationAddress.parse(stored));
            } catch (IllegalArgumentException error) {
                showConnectionScreen(error.getMessage());
            }
        }
    }

    private SharedPreferences preferences() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private int dp(float value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable surface(int fill, int outline, int corner) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(fill);
        d.setCornerRadius(dp(corner));
        d.setStroke(dp(1), outline);
        return d;
    }

    private TextView text(String value, int size, int color) {
        TextView label = new TextView(this);
        label.setText(value);
        label.setTextSize(size);
        label.setTextColor(color);
        label.setGravity(Gravity.CENTER);
        return label;
    }

    private Button button(String title) {
        Button button = new Button(this);
        button.setText(title);
        button.setTextColor(TEXT);
        button.setTextSize(14);
        button.setAllCaps(false);
        button.setBackground(surface(0xFF173C41, 0xFF3C8779, 9));
        return button;
    }

    private void destroyPreviousWebView() {
        clearConnectionTimeout();
        if (webView != null) {
            webView.stopLoading();
            webView.loadUrl("about:blank");
            ViewGroup parent = (ViewGroup) webView.getParent();
            if (parent != null) {
                parent.removeView(webView);
            }
            webView.destroy();
            webView = null;
        }
    }

    // Display the installed APK version instead of an outdated hard-coded label.
    private String appVersionLabel() {
        try {
            String version = getPackageManager()
                    .getPackageInfo(getPackageName(), 0).versionName;
            return version == null ? "versie onbekend"
                    : "v" + version.replace("-beta", " BETA ");
        } catch (android.content.pm.PackageManager.NameNotFoundException error) {
            return "versie onbekend";
        }
    }

    private void showConnectionScreen(String error) {
        destroyPreviousWebView();
        getWindow().getDecorView().setBackgroundColor(BG);
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);

        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setGravity(Gravity.CENTER_HORIZONTAL);
        content.setPadding(dp(24), dp(28), dp(24), dp(28));
        scroll.addView(content, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.sdrcc_logo);
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        content.addView(logo, new LinearLayout.LayoutParams(dp(106), dp(106)));

        TextView heading = text("SDRCC Mobile", 26, ACCENT);
        heading.setPadding(0, dp(16), 0, 0);
        content.addView(heading);

        TextView beta = text("ANDROID  ·  " + appVersionLabel(), 12, MUTED);
        beta.setPadding(0, dp(3), 0, dp(10));
        content.addView(beta);

        RadarView radar = new RadarView(this);
        content.addView(radar, new LinearLayout.LayoutParams(dp(170), dp(170)));

        TextView description = text(
                "Verbind met je SDRCC mini-pc via wifi of een privé-Tailscale-VPN. "
                        + "AIS en ADS-B blijven op hun bestaande HTTP-poorten werken.",
                14, MUTED);
        description.setPadding(0, dp(8), 0, dp(16));
        content.addView(description);

        TextView hostLabel = text("IP-adres of hostnaam van de mini-pc", 14, ACCENT);
        hostLabel.setGravity(Gravity.START);
        hostLabel.setPadding(0, 0, 0, dp(8));
        content.addView(hostLabel);

        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setFocusable(true);
        input.setFocusableInTouchMode(true);
        input.setShowSoftInputOnFocus(true);
        input.setSelectAllOnFocus(true);
        input.setTextSize(16);
        input.setTextColor(TEXT);
        input.setHintTextColor(MUTED);
        input.setHint("Bijv. 192.168.1.50:8080");
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setBackground(surface(SURFACE, 0xFF54747B, 9));
        input.setPadding(dp(14), dp(12), dp(14), dp(12));
        input.setText(preferences().getString(PREF_HOST, ""));
        content.addView(input, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(53)));

        LinearLayout editControls = new LinearLayout(this);
        editControls.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams editorParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(46));
        editorParams.topMargin = dp(8);
        content.addView(editControls, editorParams);

        Button editAddress = button("✎ Adres bewerken");
        editControls.addView(editAddress,
                new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));
        Button clearAddress = button("× Wissen");
        LinearLayout.LayoutParams clearParams = new LinearLayout.LayoutParams(
                dp(102), ViewGroup.LayoutParams.MATCH_PARENT);
        clearParams.leftMargin = dp(8);
        editControls.addView(clearAddress, clearParams);

        editAddress.setOnClickListener(view -> {
            input.requestFocus();
            input.selectAll();
            InputMethodManager keyboard = (InputMethodManager)
                    getSystemService(Context.INPUT_METHOD_SERVICE);
            if (keyboard != null) {
                keyboard.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT);
            }
        });
        clearAddress.setOnClickListener(view -> {
            input.setText("");
            input.requestFocus();
            InputMethodManager keyboard = (InputMethodManager)
                    getSystemService(Context.INPUT_METHOD_SERVICE);
            if (keyboard != null) {
                keyboard.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT);
            }
        });

        TextView validation = text(error == null ? "" : error, 13, 0xFFF4ACA2);
        validation.setPadding(0, dp(8), 0, dp(8));
        content.addView(validation);

        Button connect = button("▶ Verbinden met SDRCC");
        LinearLayout.LayoutParams connectParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(54));
        connectParams.topMargin = dp(7);
        content.addView(connect, connectParams);
        Button updateApp = button("↓ App-update controleren");
        LinearLayout.LayoutParams updateParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(48));
        updateParams.topMargin = dp(10);
        content.addView(updateApp, updateParams);
        updateApp.setOnClickListener(view -> checkForAppUpdate());
        connect.setOnClickListener(view -> {
            try {
                String raw = input.getText().toString().trim();
                URI uri = StationAddress.parse(raw);
                preferences().edit().putString(PREF_HOST, raw).apply();
                loadStation(uri);
            } catch (IllegalArgumentException exception) {
                validation.setText(exception.getMessage());
            }
        });

        TextView note = text(
                "De app opent het bestaande SDRCC Mobile-dashboard. "
                        + "Geen extra SDR-diensten of nieuwe ontvangerinstellingen nodig. "
                        + "Later kun je dezelfde verbinding via Tailscale VPN gebruiken.",
                12, MUTED);
        note.setPadding(0, dp(24), 0, 0);
        content.addView(note);

        setContentView(scroll);
    }

    private void loadStation(URI stationPage) {
        destroyPreviousWebView();
        currentHost = stationPage.getHost().toLowerCase(Locale.ROOT);
        currentPort = stationPage.getPort();
        currentPageUrl = stationPage.toString();
        pageFailed = false;

        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.VERTICAL);
        outer.setBackgroundColor(BG);

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(9), 0, dp(9), 0);
        bar.setBackgroundColor(SURFACE);
        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.sdrcc_logo);
        logo.setContentDescription("SDRCC");
        bar.addView(logo, new LinearLayout.LayoutParams(dp(35), dp(35)));
        TextView title = text("SDRCC Android  ·  " + appVersionLabel(), 14, ACCENT);
        title.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        title.setPadding(dp(8), 0, 0, 0);
        bar.addView(title, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));

        Button refresh = button("⟳");
        refresh.setContentDescription("SDRCC verversen");
        bar.addView(refresh, new LinearLayout.LayoutParams(dp(44), dp(42)));
        Button update = button("↓");
        update.setContentDescription("Android app-update controleren");
        bar.addView(update, new LinearLayout.LayoutParams(dp(42), dp(42)));
        Button settings = button("⚙");
        settings.setContentDescription("SDRCC adres wijzigen");
        LinearLayout.LayoutParams settingsParams = new LinearLayout.LayoutParams(dp(44), dp(42));
        settingsParams.leftMargin = dp(8);
        bar.addView(settings, settingsParams);
        outer.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(50)));

        FrameLayout browserContainer = new FrameLayout(this);
        browserContainer.setBackgroundColor(BG);
        outer.addView(browserContainer, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        webView = new WebView(this);
        webView.setBackgroundColor(BG);
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
        WebSettings webSettings = webView.getSettings();
        webSettings.setJavaScriptEnabled(true); // Existing SDRCC Mobile requires JS.
        webSettings.setDomStorageEnabled(true);  // Map addresses / last tab.
        webSettings.setMediaPlaybackRequiresUserGesture(true);
        webSettings.setSupportMultipleWindows(false);
        webSettings.setJavaScriptCanOpenWindowsAutomatically(false);
        webSettings.setAllowFileAccess(false);
        webSettings.setAllowContentAccess(false);
        webSettings.setAllowFileAccessFromFileURLs(false);
        webSettings.setAllowUniversalAccessFromFileURLs(false);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            webSettings.setSafeBrowsingEnabled(true);
        }
        webView.setWebViewClient(new StationWebViewClient());
        webView.setWebChromeClient(new StationChromeClient());
        browserContainer.addView(webView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout overlay = new LinearLayout(this);
        overlay.setOrientation(LinearLayout.VERTICAL);
        overlay.setGravity(Gravity.CENTER);
        overlay.setPadding(dp(24), dp(18), dp(24), dp(18));
        overlay.setBackgroundColor(BG);

        ImageView bigLogo = new ImageView(this);
        bigLogo.setImageResource(R.drawable.sdrcc_logo);
        bigLogo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        bigLogo.setContentDescription("SDRCC Mobile");
        bigLogo.setPadding(dp(8), dp(8), dp(8), dp(8));
        bigLogo.setBackground(surface(0xFF10232D, 0xFF28665E, 18));
        overlay.addView(bigLogo, new LinearLayout.LayoutParams(dp(122), dp(122)));
        TextView brand = text("SDRCC MOBILE", 21, ACCENT);
        brand.setTypeface(null, android.graphics.Typeface.BOLD);
        brand.setLetterSpacing(.09f);
        brand.setPadding(0, dp(12), 0, dp(2));
        overlay.addView(brand);
        TextView stationCaption = text("VERBINDEN MET JE SDRCC-STATION", 10, MUTED);
        stationCaption.setLetterSpacing(.08f);
        stationCaption.setPadding(0, 0, 0, dp(3));
        overlay.addView(stationCaption);
        overlay.addView(new RadarView(this), new LinearLayout.LayoutParams(dp(202), dp(202)));

        LinearLayout statusPanel = new LinearLayout(this);
        statusPanel.setOrientation(LinearLayout.HORIZONTAL);
        statusPanel.setGravity(Gravity.CENTER_VERTICAL);
        statusPanel.setPadding(dp(14), dp(11), dp(14), dp(11));
        statusPanel.setBackground(surface(0xCC10232D, 0xFF244C4D, 14));
        LinearLayout.LayoutParams statusParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        statusParams.topMargin = dp(8);
        overlay.addView(statusPanel, statusParams);

        loadingIndicator = text("●", 10, ACCENT);
        loadingIndicator.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        LinearLayout.LayoutParams indicatorParams = new LinearLayout.LayoutParams(
                dp(18), ViewGroup.LayoutParams.WRAP_CONTENT);
        indicatorParams.rightMargin = dp(8);
        statusPanel.addView(loadingIndicator, indicatorParams);
        loadingText = text("Verbinden met " + currentHost + "…", 14, MUTED);
        loadingText.setGravity(Gravity.CENTER);
        statusPanel.addView(loadingText, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        TextView networkHint = text("Wifi of privé-VPN  ·  poort " + currentPort,
                12, MUTED);
        networkHint.setPadding(0, dp(8), 0, dp(2));
        overlay.addView(networkHint);

        retryButton = button("↻ Opnieuw proberen");
        retryButton.setVisibility(View.GONE);
        LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
        retryParams.topMargin = dp(10);
        overlay.addView(retryButton, retryParams);
        changeHostButton = button("✎ IP-adres wijzigen");
        // The operator must be able to correct an incorrect stored IP immediately.
        // Do not hide this button while the native radar connection screen is open.
        changeHostButton.setVisibility(View.VISIBLE);
        LinearLayout.LayoutParams changeParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(54));
        changeParams.topMargin = dp(8);
        overlay.addView(changeHostButton, changeParams);
        changeHostButton.setTextSize(16);
        changeHostButton.setBackground(surface(0xFF173C41, 0xFF54A28D, 12));

        ScrollView overlayScroll = new ScrollView(this);
        overlayScroll.setFillViewport(true);
        overlayScroll.setVerticalScrollBarEnabled(false);
        overlayScroll.setBackgroundColor(BG);
        overlayScroll.addView(overlay, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        loadingCover = overlayScroll;
        browserContainer.addView(overlayScroll, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(outer);

        refresh.setOnClickListener(v -> reloadStation());
        update.setOnClickListener(v -> checkForAppUpdate());
        settings.setOnClickListener(v -> showConnectionScreen(null));
        retryButton.setOnClickListener(v -> reloadStation());
        changeHostButton.setOnClickListener(v -> showConnectionScreen(null));
        reloadStation();
    }

    private void reloadStation() {
        if (webView == null) {
            return;
        }
        pageFailed = false;
        connectionErrorDetails = "";
        loadingCover.setVisibility(View.VISIBLE);
        retryButton.setVisibility(View.GONE);
        changeHostButton.setVisibility(View.VISIBLE);
        if (loadingIndicator != null) {
            loadingIndicator.setTextColor(ACCENT);
        }
        loadingText.setText("Verbinden met " + currentHost + "…");
        clearConnectionTimeout();
        loadTimeout = () -> {
            showLoadError("SDRCC reageert niet binnen 20 seconden via wifi of VPN."
                    + " Controleer het adres en de netwerkverbinding."
                    + "\nAndroid-netwerktest wordt uitgevoerd…");
            probeStationAfterWebError(webView);
        };
        // Probe with the app's own HTTP stack as a second diagnostic signal.
        // The probe never starts/stops services or retries a receiver action.
        handler.postDelayed(loadTimeout, CONNECT_TIMEOUT_MS);
        // User-initiated refresh or initial load. No receiver POST is replayed.
        webView.loadUrl(currentPageUrl);
    }

    private void clearConnectionTimeout() {
        if (loadTimeout != null) {
            handler.removeCallbacks(loadTimeout);
            loadTimeout = null;
        }
    }

    private void showLoadError(String text) {
        if (loadingCover == null || pageFailed) {
            return;
        }
        pageFailed = true;
        clearConnectionTimeout();
        loadingCover.setVisibility(View.VISIBLE);
        connectionErrorDetails = text;
        loadingText.setText(text);
        if (loadingIndicator != null) {
            loadingIndicator.setTextColor(0xFFF4ACA2);
        }
        retryButton.setVisibility(View.VISIBLE);
        changeHostButton.setVisibility(View.VISIBLE);
    }

    /**
     * Compare the native Android network path with WebView for the configured
     * SDRCC page. An HTTP HEAD request is read-only, bounded, and never follows
     * redirects. It is only used after a main-frame WebView error.
     */
    private void probeStationAfterWebError(final WebView failingView) {
        final String target = currentPageUrl;
        new Thread(() -> {
            HttpURLConnection connection = null;
            String result;
            try {
                connection = (HttpURLConnection) new URL(target).openConnection();
                connection.setRequestMethod("HEAD");
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(5000);
                connection.setInstanceFollowRedirects(false);
                connection.setUseCaches(false);
                int status = connection.getResponseCode();
                result = "Android-netwerktest: HTTP " + status +
                        (status >= 200 && status < 400
                                ? " (mini-pc bereikbaar; probleem zit in WebView)."
                                : " (mini-pc antwoordt met HTTP-fout).");
            } catch (Exception exception) {
                String detail = String.valueOf(exception.getMessage());
                if (detail.length() > 140) detail = detail.substring(0, 140);
                result = "Android-netwerktest: " +
                        exception.getClass().getSimpleName() + ": " + detail;
            } finally {
                if (connection != null) connection.disconnect();
            }
            final String probeResult = result;
            handler.post(() -> {
                if (webView == failingView && pageFailed && loadingText != null) {
                    loadingText.setText(connectionErrorDetails + "\n" + probeResult);
                }
            });
        }, "sdrcc-android-network-diagnostic").start();
    }

    private int installedAppVersionCode() {
        try {
            android.content.pm.PackageInfo info =
                    getPackageManager().getPackageInfo(getPackageName(), 0);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                return (int) info.getLongVersionCode();
            }
            return info.versionCode;
        } catch (android.content.pm.PackageManager.NameNotFoundException exception) {
            return 0;
        }
    }

    /**
     * Read public metadata with a strict size bound; the app never needs
     * GitHub credentials and the station's private HTTP API is untouched.
     */
    private String readUpdateFeed() throws Exception {
        HttpURLConnection connection = (HttpURLConnection)
                new URL(APP_UPDATE_FEED).openConnection();
        try {
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(7000);
            connection.setReadTimeout(7000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            int status = connection.getResponseCode();
            if (status != 200) throw new IOException("Updatebron geeft HTTP " + status);
            try (InputStream input = connection.getInputStream();
                 ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[2048];
                int n;
                while ((n = input.read(buffer)) != -1) {
                    if (bytes.size() + n > APP_UPDATE_MAX_BYTES) {
                        throw new IOException("Updatebericht is onverwacht groot.");
                    }
                    bytes.write(buffer, 0, n);
                }
                return bytes.toString(StandardCharsets.UTF_8.name());
            }
        } finally {
            connection.disconnect();
        }
    }

    private void checkForAppUpdate() {
        if (updateCheckBusy) return;
        updateCheckBusy = true;
        Toast.makeText(this, "SDRCC app-update controleren…", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                JSONObject feed = new JSONObject(readUpdateFeed());
                Object rawCode = feed.opt("version_code");
                if (!(rawCode instanceof Integer) && !(rawCode instanceof Long)) {
                    throw new IOException("Het versieveld van de updatebron is ongeldig.");
                }
                long code = ((Number) rawCode).longValue();
                if (code < Integer.MIN_VALUE || code > Integer.MAX_VALUE) {
                    throw new IOException("De aangeboden versiecode is ongeldig.");
                }
                int offeredCode = (int) code;
                String name = feed.optString("version_name", "").trim();
                String link = feed.optString("apk_url", "").trim();
                AppUpdatePolicy.Status status = AppUpdatePolicy.evaluate(
                        installedAppVersionCode(), offeredCode, name, link);
                handler.post(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    AlertDialog.Builder dialog = new AlertDialog.Builder(this);
                    if (status == AppUpdatePolicy.Status.UNPUBLISHED) {
                        dialog.setTitle("Nog geen ondertekende app-release")
                                .setMessage("De updatecontrole is bereikbaar, maar er staat "
                                        + "nog geen officieel ondertekende Android-APK op GitHub. "
                                        + "Je huidige app blijft gewoon werken.")
                                .setPositiveButton("OK", null);
                    } else if (status == AppUpdatePolicy.Status.INVALID) {
                        dialog.setTitle("Update tijdelijk niet beschikbaar")
                                .setMessage("GitHub geeft een onvolledig of onjuist "
                                        + "updatebericht. Er wordt geen APK geopend.")
                                .setPositiveButton("OK", null);
                    } else if (status == AppUpdatePolicy.Status.UP_TO_DATE) {
                        dialog.setTitle("SDRCC Mobile is bijgewerkt")
                                .setMessage("Geen nieuwere Android-app gepubliceerd. "
                                        + "Geïnstalleerd: " + appVersionLabel() + ".")
                                .setPositiveButton("OK", null);
                    } else {
                        dialog.setTitle("Nieuwe SDRCC Mobile-versie")
                                .setMessage("Versie " + name + " is beschikbaar. "
                                        + "De officiële GitHub APK wordt in je browser geopend. "
                                        + "Android vraagt zelf toestemming voor de installatie. "
                                        + "Je SDRCC mini-pc blijft draaien.")
                                .setNegativeButton("Annuleren", null)
                                .setPositiveButton("APK openen", (whichDialog, which) ->
                                        openExternal(Uri.parse(link)));
                    }
                    dialog.show();
                });
            } catch (Exception exception) {
                String details = exception.getMessage() == null
                        ? exception.getClass().getSimpleName() : exception.getMessage();
                if (details.length() > 160) details = details.substring(0, 160);
                final String failure = details;
                handler.post(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    new AlertDialog.Builder(this)
                            .setTitle("Updatecontrole niet beschikbaar")
                            .setMessage("Kan de openbare GitHub-updatebron niet controleren. "
                                    + "Controleer internet op je telefoon. Details: " + failure
                                    + "\nDe SDRCC-ontvangst blijft actief.")
                            .setPositiveButton("OK", null)
                            .show();
                });
            } finally {
                handler.post(() -> updateCheckBusy = false);
            }
        }, "sdrcc-app-update-check").start();
    }

    private boolean isStationUri(Uri uri) {
        if (uri == null || uri.getHost() == null || currentHost == null) {
            return false;
        }
        String scheme = uri.getScheme();
        if (!"http".equalsIgnoreCase(scheme)) {
            return false;
        }
        if (!currentHost.equalsIgnoreCase(uri.getHost())) {
            return false;
        }
        int port = uri.getPort() == -1 ? 80 : uri.getPort();
        // Default dashboards and map ports; no arbitrary origin navigation.
        return port == currentPort || port == 8119 || port == 80;
    }

    private void openExternal(Uri uri) {
        if (uri == null) return;
        String scheme = uri.getScheme();
        if (!"http".equalsIgnoreCase(scheme) && !"https".equalsIgnoreCase(scheme)) {
            return;
        }
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, uri);
            intent.addCategory(Intent.CATEGORY_BROWSABLE);
            startActivity(intent);
        } catch (ActivityNotFoundException ignored) {
            // This is not a receiver error, and should never alter SDRCC state.
        }
    }

    private final class StationWebViewClient extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            // The AIS :8119 and ADS-B :80 iframes remain inside this WebView.
            if (!request.isForMainFrame()) {
                return false;
            }
            Uri uri = request.getUrl();
            if (isStationUri(uri)) {
                return false;
            }
            openExternal(uri);
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
            super.onPageStarted(view, url, icon);
            pageFailed = false;
            if (loadingCover != null) {
                loadingCover.setVisibility(View.VISIBLE);
            }
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            super.onPageFinished(view, url);
            if (!pageFailed && loadingCover != null) {
                clearConnectionTimeout();
                loadingCover.setVisibility(View.GONE);
            }
        }

        @Override
        public void onReceivedError(
                WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) {
                String explanation = String.valueOf(error.getDescription());
                if (explanation.length() > 140) explanation = explanation.substring(0, 140);
                String location = request.getUrl() == null
                        ? currentHost : request.getUrl().getHost();
                showLoadError("WebView-fout " + error.getErrorCode() + ": " + explanation
                        + "\nHost: " + location + ". Wifi of VPN mag allebei."
                        + "\nAndroid-netwerktest wordt uitgevoerd…");
                probeStationAfterWebError(view);
            }
        }

        @Override
        public void onReceivedHttpError(
                WebView view, WebResourceRequest request, WebResourceResponse response) {
            if (request.isForMainFrame() && response.getStatusCode() >= 400) {
                showLoadError("SDRCC geeft HTTP " + response.getStatusCode()
                        + ". Controleer de mini-pc en het adres.");
            }
        }

        @Override
        public void onReceivedSslError(
                WebView view, SslErrorHandler handler, SslError error) {
            // Never silently bypass an invalid HTTPS certificate.
            handler.cancel();
        }

        @Override
        public boolean onRenderProcessGone(
                WebView view, android.webkit.RenderProcessGoneDetail detail) {
            showConnectionScreen("De Android WebView is gestopt. "
                    + "Controleer de verbinding en probeer opnieuw.");
            return true;
        }
    }

    private final class StationChromeClient extends WebChromeClient {
        @Override
        public boolean onJsAlert(WebView view, String url, String message, JsResult result) {
            new AlertDialog.Builder(MainActivity.this)
                    .setTitle("SDRCC Mobile")
                    .setMessage(message)
                    .setPositiveButton("OK", (dialog, which) -> result.confirm())
                    .setOnCancelListener(dialog -> result.cancel())
                    .show();
            return true;
        }

        @Override
        public boolean onJsConfirm(WebView view, String url, String message, JsResult result) {
            // Existing SDRCC Mission STOP confirmations must remain effective.
            new AlertDialog.Builder(MainActivity.this)
                    .setTitle("SDRCC bevestiging")
                    .setMessage(message)
                    .setPositiveButton("Ja", (dialog, which) -> result.confirm())
                    .setNegativeButton("Nee", (dialog, which) -> result.cancel())
                    .setOnCancelListener(dialog -> result.cancel())
                    .show();
            return true;
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            // No camera, microphone, geolocation or media capture is required.
            request.deny();
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(
                String origin, GeolocationPermissions.Callback callback) {
            callback.invoke(origin, false, false);
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override
    public void onConfigurationChanged(Configuration configuration) {
        // Keep iframe map zoom/center and WebView state across rotation.
        super.onConfigurationChanged(configuration);
    }

    @Override
    protected void onDestroy() {
        destroyPreviousWebView();
        super.onDestroy();
    }
}
