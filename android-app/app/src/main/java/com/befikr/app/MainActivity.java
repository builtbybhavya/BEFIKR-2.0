package com.befikr.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.telephony.PhoneNumberUtils;
import android.telephony.SmsManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private static final int SOS_PERMISSION_REQUEST = 4201;
    private WebView webView;
    private GeolocationPermissions.Callback pendingGeoCallback;
    private String pendingGeoOrigin;
    private PendingSos pendingSos;
    private boolean permissionRequestInProgress;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(0xFFF7F3EC);
        getWindow().setNavigationBarColor(0xFFF7F3EC);

        webView = new WebView(this);
        webView.setBackgroundColor(0xFFF7F3EC);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setGeolocationEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) settings.setSafeBrowsingEnabled(true);

        webView.addJavascriptInterface(new BefikrBridge(), "BefikrAndroid");
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
                if (hasLocationPermission()) {
                    callback.invoke(origin, true, false);
                    return;
                }
                pendingGeoOrigin = origin;
                pendingGeoCallback = callback;
                requestRuntimePermissions(false);
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return routeUrl(request.getUrl());
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return routeUrl(Uri.parse(url));
            }
        });
        setContentView(webView);
        webView.loadUrl(BuildConfig.BEFIKR_START_URL);
    }

    private boolean routeUrl(Uri uri) {
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
        if (scheme.equals("tel")) {
            openDialer(uri);
            return true;
        }
        if (scheme.equals("https") || scheme.equals("http")) {
            Uri start = Uri.parse(BuildConfig.BEFIKR_START_URL);
            if (sameOrigin(uri, start)) return false;
            openExternal(uri);
            return true;
        }
        if (scheme.equals("mailto") || scheme.equals("sms")) {
            openExternal(uri);
            return true;
        }
        return true;
    }

    private boolean sameOrigin(Uri left, Uri right) {
        if (left.getHost() == null || right.getHost() == null) return false;
        int leftPort = left.getPort() >= 0 ? left.getPort() : ("https".equalsIgnoreCase(left.getScheme()) ? 443 : 80);
        int rightPort = right.getPort() >= 0 ? right.getPort() : ("https".equalsIgnoreCase(right.getScheme()) ? 443 : 80);
        return left.getScheme().equalsIgnoreCase(right.getScheme())
                && left.getHost().equalsIgnoreCase(right.getHost())
                && leftPort == rightPort;
    }

    private void openDialer(Uri uri) {
        try {
            Intent intent = new Intent(Intent.ACTION_DIAL, uri);
            startActivity(intent);
        } catch (Exception exception) {
            showToast("No phone dialer is available on this device.");
        }
    }

    private void openExternal(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception exception) {
            showToast("No app is available to open this link.");
        }
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private boolean hasSmsPermission() {
        return checkSelfPermission(Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED;
    }

    private void requestRuntimePermissions(boolean includeSms) {
        if (permissionRequestInProgress) return;
        permissionRequestInProgress = true;
        String[] requested = includeSms
                ? new String[]{Manifest.permission.SEND_SMS, Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}
                : new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION};
        requestPermissions(requested, SOS_PERMISSION_REQUEST);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != SOS_PERMISSION_REQUEST) return;
        permissionRequestInProgress = false;
        boolean locationGranted = hasLocationPermission();
        boolean smsGranted = hasSmsPermission();

        if (pendingGeoCallback != null) {
            pendingGeoCallback.invoke(pendingGeoOrigin, locationGranted, false);
            pendingGeoCallback = null;
            pendingGeoOrigin = null;
        }
        notifyWebPermissions(smsGranted, locationGranted);

        PendingSos queued = pendingSos;
        pendingSos = null;
        if (queued != null) {
            if (smsGranted) dispatchSosNow(queued);
            else {
                showToast("SMS permission was declined. Opening the 112 dialer.");
                openEmergencyDialer();
            }
        }
    }

    private void notifyWebPermissions(boolean smsGranted, boolean locationGranted) {
        if (webView == null) return;
        String script = "window.onBefikrAndroidPermissions && window.onBefikrAndroidPermissions({sms:"
                + smsGranted + ",location:" + locationGranted + "});";
        webView.post(() -> webView.evaluateJavascript(script, null));
    }

    private void dispatchSosNow(PendingSos sos) {
        int sentCount = 0;
        if (hasSmsPermission()) {
            try {
                JSONArray contacts = new JSONArray(sos.contactsJson);
                SmsManager smsManager = getSmsManager();
                java.util.HashSet<String> sentNumbers = new java.util.HashSet<>();
                for (int index = 0; index < contacts.length(); index++) {
                    JSONObject contact = contacts.optJSONObject(index);
                    if (contact == null) continue;
                    String number = normalizePhone(contact.optString("phone", ""));
                    if (number.isEmpty() || !sentNumbers.add(number)) continue;
                    smsManager.sendTextMessage(number, null, sos.message, null, null);
                    sentCount++;
                }
            } catch (Exception exception) {
                showToast("The SOS text could not be queued. Opening the 112 dialer.");
            }
        }

        if (sentCount > 0) {
            showToast("SOS text submitted for " + sentCount + " trusted contact" + (sentCount == 1 ? "." : "s."));
        } else if (hasSmsPermission()) {
            showToast("No trusted contact with a valid phone number was available. Opening the 112 dialer.");
        }
        openEmergencyDialer();
    }

    @SuppressWarnings("deprecation")
    private SmsManager getSmsManager() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            SmsManager manager = getSystemService(SmsManager.class);
            if (manager != null) return manager;
        }
        return SmsManager.getDefault();
    }

    private String normalizePhone(String input) {
        String number = PhoneNumberUtils.normalizeNumber(input == null ? "" : input.trim());
        if (number.isEmpty()) return "";
        if (number.startsWith("00")) number = "+" + number.substring(2);
        if (number.length() == 10) number = "+91" + number;
        else if (number.length() == 12 && number.startsWith("91")) number = "+" + number;
        else if (number.length() == 11 && number.startsWith("0")) number = "+91" + number.substring(1);
        if (number.length() < 10 || number.length() > 16) return "";
        return number;
    }

    private void openEmergencyDialer() {
        openDialer(Uri.parse("tel:112"));
    }

    private void showToast(String message) {
        runOnUiThread(() -> Toast.makeText(this, message, Toast.LENGTH_LONG).show());
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    private final class BefikrBridge {
        @JavascriptInterface
        public boolean isAvailable() {
            return true;
        }

        @JavascriptInterface
        public boolean hasSosPermissions() {
            return hasSmsPermission() && hasLocationPermission();
        }

        @JavascriptInterface
        public void requestSosPermissions() {
            runOnUiThread(() -> {
                if (hasSmsPermission() && hasLocationPermission()) {
                    notifyWebPermissions(true, true);
                    showToast("SOS SMS and location permissions are ready.");
                } else {
                    requestRuntimePermissions(true);
                }
            });
        }

        @JavascriptInterface
        public void dispatchSos(String contactsJson, String message, String mapsUrl) {
            PendingSos sos = new PendingSos(contactsJson, message, mapsUrl);
            runOnUiThread(() -> {
                if (!hasSmsPermission()) {
                    pendingSos = sos;
                    requestRuntimePermissions(true);
                    return;
                }
                dispatchSosNow(sos);
            });
        }

        @JavascriptInterface
        public void openWhatsApp(String message) {
            runOnUiThread(() -> {
                Intent whatsapp = new Intent(Intent.ACTION_SEND);
                whatsapp.setType("text/plain");
                whatsapp.putExtra(Intent.EXTRA_TEXT, message == null ? "" : message);
                whatsapp.setPackage("com.whatsapp");
                try {
                    if (whatsapp.resolveActivity(getPackageManager()) != null) {
                        startActivity(whatsapp);
                    } else {
                        whatsapp.setPackage("com.whatsapp.w4b");
                        if (whatsapp.resolveActivity(getPackageManager()) != null) {
                            startActivity(whatsapp);
                        } else {
                            Intent chooser = new Intent(Intent.ACTION_SEND);
                            chooser.setType("text/plain");
                            chooser.putExtra(Intent.EXTRA_TEXT, message == null ? "" : message);
                            startActivity(Intent.createChooser(chooser, "Choose an app to share your SOS message"));
                        }
                    }
                } catch (Exception exception) {
                    showToast("WhatsApp is not available. Your SMS was handled separately.");
                }
            });
        }
    }

    private static final class PendingSos {
        final String contactsJson;
        final String message;
        final String mapsUrl;

        PendingSos(String contactsJson, String message, String mapsUrl) {
            this.contactsJson = contactsJson == null ? "[]" : contactsJson;
            this.message = message == null ? "SOS!!- Current location unavailable" : message;
            this.mapsUrl = mapsUrl;
        }
    }
}
