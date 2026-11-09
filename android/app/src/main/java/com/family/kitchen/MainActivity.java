package com.family.kitchen;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;

public class MainActivity extends Activity {
    private WebView web;
    private Uri server;
    private ValueCallback<Uri[]> files;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        Button settings = new Button(this);
        settings.setText("家庭厨房 · 设置服务地址");
        settings.setOnClickListener(v -> configure());
        layout.addView(settings);
        BailianSettings apiSettings = new BailianSettings(this, getPreferences(0));
        Button apiButton = new Button(this);
        apiButton.setText("百炼 API 设置");
        apiButton.setOnClickListener(v -> apiSettings.show());
        layout.addView(apiButton);
        web = new WebView(this);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(true);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                return server == null || !uri.getScheme().equals(server.getScheme()) || !uri.getAuthority().equals(server.getAuthority());
            }
            @Override public void onReceivedHttpAuthRequest(WebView view, android.webkit.HttpAuthHandler handler, String host, String realm) {
                EditText password = new EditText(MainActivity.this);
                password.setInputType(129);
                new AlertDialog.Builder(MainActivity.this).setTitle("厨房访问密码").setView(password)
                    .setPositiveButton("连接", (d, which) -> handler.proceed("kitchen", password.getText().toString()))
                    .setNegativeButton("取消", (d, which) -> handler.cancel()).setOnCancelListener(d -> handler.cancel()).show();
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (files != null) files.onReceiveValue(null);
                files = callback;
                try { startActivityForResult(params.createIntent(), 10); }
                catch (android.content.ActivityNotFoundException e) { files.onReceiveValue(null); files = null; }
                return true;
            }
        });
        layout.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(layout);
        String saved = getPreferences(0).getString("server", "");
        if (saved.isEmpty()) configure(); else connect(saved);
    }

    private void configure() {
        EditText address = new EditText(this);
        address.setSingleLine(true);
        address.setHint("https://你的厨房服务地址");
        address.setText(getPreferences(0).getString("server", ""));
        new AlertDialog.Builder(this).setTitle("连接厨房服务").setView(address)
            .setPositiveButton("连接", (d, which) -> connect(address.getText().toString().trim()))
            .setNegativeButton("取消", null).show();
    }

    private void connect(String value) {
        Uri uri = Uri.parse(value);
        if (!("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) || uri.getHost() == null || uri.getUserInfo() != null) {
            Toast.makeText(this, "请输入有效的 HTTP 或 HTTPS 服务地址", Toast.LENGTH_LONG).show();
            return;
        }
        server = uri;
        getPreferences(0).edit().putString("server", value).apply();
        web.loadUrl(value);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == 10 && files != null) {
            files.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            files = null;
        }
    }
    @Override public void onBackPressed() { if (web.canGoBack()) web.goBack(); else super.onBackPressed(); }
    @Override protected void onDestroy() {
        if (files != null) files.onReceiveValue(null);
        web.destroy();
        super.onDestroy();
    }
}
