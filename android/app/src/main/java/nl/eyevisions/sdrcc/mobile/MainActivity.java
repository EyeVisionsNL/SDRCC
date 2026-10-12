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

import android.net.http.SslError;
import java.net.URI;
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

    private final Handler handler = new Handler(Looper.getMainLooper());
    private WebView webView;
    private View loadingCover;
    private TextView loadingText;
    private Button retryButton;
    private Button changeHostButton;
    private Runnable loadTimeout;
    private boolean pageFailed;
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

        TextView beta = text("ANDROID  ·  0.1 BETA", 12, MUTED);
        beta.setPadding(0, dp(3), 0, dp(10));
        content.addView(beta);

        RadarView radar = new RadarView(this);
        content.addView(radar, new LinearLayout.LayoutParams(dp(170), dp(170)));

        TextView description = text(
                "Verbind met je SDRCC mini-pc via het lokale wifi-netwerk. "
                        + "AIS en ADS-B blijven op hun bestaande HTTP-poorten werken.",
                14, MUTED);
        description.setPadding(0, dp(8), 0, dp(16));
        content.addView(description);

        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setSelectAllOnFocus(true);
        input.setTextSize(16);
        input.setTextColor(TEXT);
        input.setHintTextColor(MUTED);
        input.setHint("192.168.1.50:8080");
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        input.setBackground(surface(SURFACE, 0xFF54747B, 9));
        input.setPadding(dp(14), dp(12), dp(14), dp(12));
        input.setText(preferences().getString(PREF_HOST, ""));
        content.addView(input, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(53)));

        TextView validation = text(error == null ? "" : error, 13, 0xFFF4ACA2);
        validation.setPadding(0, dp(8), 0, dp(8));
        content.addView(validation);

        Button connect = button("▶ Verbinden met SDRCC");
        LinearLayout.LayoutParams connectParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(54));
        connectParams.topMargin = dp(7);
        content.addView(connect, connectParams);
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
        TextView title = text("SDRCC Android  ·  BETA", 14, ACCENT);
        title.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        title.setPadding(dp(8), 0, 0, 0);
        bar.addView(title, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.MATCH_PARENT, 1f));

        Button refresh = button("⟳");
        refresh.setContentDescription("SDRCC verversen");
        bar.addView(refresh, new LinearLayout.LayoutParams(dp(44), dp(42)));
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
        overlay.setPadding(dp(28), dp(24), dp(28), dp(24));
        overlay.setBackgroundColor(BG);

        ImageView bigLogo = new ImageView(this);
        bigLogo.setImageResource(R.drawable.sdrcc_logo);
        overlay.addView(bigLogo, new LinearLayout.LayoutParams(dp(90), dp(90)));
        TextView brand = text("SDRCC MOBILE", 19, ACCENT);
        brand.setPadding(0, dp(12), 0, dp(6));
        overlay.addView(brand);
        overlay.addView(new RadarView(this), new LinearLayout.LayoutParams(dp(140), dp(140)));
        loadingText = text("Verbinden met " + currentHost + "…", 14, MUTED);
        loadingText.setPadding(0, dp(12), 0, dp(12));
        overlay.addView(loadingText);

        retryButton = button("↻ Opnieuw proberen");
        retryButton.setVisibility(View.GONE);
        LinearLayout.LayoutParams retryParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
        retryParams.topMargin = dp(10);
        overlay.addView(retryButton, retryParams);
        changeHostButton = button("⚙ Adres wijzigen");
        changeHostButton.setVisibility(View.GONE);
        LinearLayout.LayoutParams changeParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(50));
        changeParams.topMargin = dp(10);
        overlay.addView(changeHostButton, changeParams);

        loadingCover = overlay;
        browserContainer.addView(overlay, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(outer);

        refresh.setOnClickListener(v -> reloadStation());
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
        loadingCover.setVisibility(View.VISIBLE);
        retryButton.setVisibility(View.GONE);
        changeHostButton.setVisibility(View.GONE);
        loadingText.setText("Verbinden met " + currentHost + "…");
        clearConnectionTimeout();
        loadTimeout = () -> showLoadError(
                "SDRCC reageert niet. Controleer het adres, wifi en of de mini-pc aanstaat.");
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
        loadingText.setText(text);
        retryButton.setVisibility(View.VISIBLE);
        changeHostButton.setVisibility(View.VISIBLE);
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
                showLoadError("SDRCC is niet bereikbaar via dit netwerk. "
                        + "Controleer het IP-adres en de wifi-verbinding.");
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
