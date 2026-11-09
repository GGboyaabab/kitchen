package com.family.kitchen;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.widget.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import javax.net.ssl.HttpsURLConnection;
import org.json.*;

final class BailianSettings {
    private final Activity activity;
    private final BailianKey credentials;
    private String sessionToken = "", sessionBase = "";
    private static final String DEFAULT = "https://dashscope.aliyuncs.com/compatible-mode/v1";
    private static final String PLAN = "token-plan.cn-beijing.maas.aliyuncs.com";

    BailianSettings(Activity activity, SharedPreferences preferences) {
        this.activity = activity;
        credentials = new BailianKey(preferences);
    }

    static URI endpoint(String base) {
        URI uri = URI.create(base);
        String host = uri.getHost();
        if (!"https".equals(uri.getScheme()) || host == null ||
            !(host.equals("dashscope.aliyuncs.com") || host.equals("dashscope-intl.aliyuncs.com") ||
            host.endsWith(".dashscope.aliyuncs.com") || host.endsWith(".maas.aliyuncs.com")) ||
            uri.getUserInfo() != null || uri.getPort() != -1 || uri.getQuery() != null ||
            uri.getFragment() != null || !"/compatible-mode/v1".equals(uri.getPath()))
            throw new IllegalArgumentException("请输入百炼控制台的 HTTPS Base URL");
        return URI.create(base + "/chat/completions");
    }

    static void validate(URI endpoint, String token) {
        if (token.isEmpty() || token.matches("(?s).*\\s.*")) throw new IllegalArgumentException("请输入有效 API Key");
        boolean plan = PLAN.equalsIgnoreCase(endpoint.getHost());
        if (token.startsWith("sk-sp-") != plan)
            throw new IllegalArgumentException(plan ? "请填写 sk-sp- 开头的套餐密钥" : "套餐密钥请使用 token-plan.cn-beijing.maas.aliyuncs.com 地址");
    }

    void show() {
        LinearLayout body = new LinearLayout(activity);
        body.setOrientation(1);
        body.setPadding(32, 16, 32, 16);
        EditText base = new EditText(activity);
        base.setHint("百炼 Base URL");
        base.setText(credentials.base(DEFAULT));
        body.addView(base);
        EditText key = new EditText(activity);
        key.setInputType(129);
        key.setHint("API Key（留空保留已保存密钥）");
        body.addView(key);
        CheckBox remember = new CheckBox(activity);
        remember.setText("加密保存到手机（不勾选则仅本次使用）");
        body.addView(remember);
        TextView status = new TextView(activity);
        body.addView(status);
        Button clear = new Button(activity);
        clear.setText("清除密钥");
        body.addView(clear);
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle("百炼 API 设置").setView(body)
            .setNegativeButton("关闭", null).setNeutralButton("测试连接", null).setPositiveButton("保存", null).create();
        dialog.show();
        clear.setOnClickListener(v -> { sessionToken = ""; sessionBase = ""; status.setText(credentials.clear() ? "密钥已清除" : "清除失败"); key.setText(""); });
        for (int button : new int[]{AlertDialog.BUTTON_POSITIVE, AlertDialog.BUTTON_NEUTRAL}) {
            dialog.getButton(button).setOnClickListener(v -> {
                String address = base.getText().toString().trim().replaceAll("/+$", "");
                final String token;
                final URI url;
                try {
                    url = endpoint(address);
                    String entered = key.getText().toString().trim();
                    token = entered.isEmpty() ? (sessionToken.isEmpty() ? credentials.read() : sessionToken) : entered;
                    validate(url, token);
                    if (button == AlertDialog.BUTTON_POSITIVE) {
                        if (remember.isChecked()) {
                            if (!credentials.save(address, token)) throw new IllegalStateException("Save failed");
                        } else if (!credentials.clear()) throw new IllegalStateException("Clear failed");
                        sessionToken = token; sessionBase = address;
                        status.setText(remember.isChecked() ? "配置已加密保存" : "仅本次使用，未保存密钥");
                        key.setText("");
                        return;
                    }
                } catch (Exception e) { status.setText(e instanceof IllegalArgumentException ? e.getMessage() : "无法读取或保存密钥，请重新输入"); return; }
                v.setEnabled(false);
                status.setText("正在测试（会调用模型）…");
                new Thread(() -> {
                    String message;
                    try { test(url, token); message = "连接成功"; }
                    catch (Exception e) { message = "连接失败，请检查地址、密钥、额度和网络"; }
                    final String result = message;
                    activity.runOnUiThread(() -> { if (dialog.isShowing()) { status.setText(result); v.setEnabled(true); } });
                }, "kitchen-api-test").start();
            });
        }
    }

    String ask(String prompt) throws Exception {
        String token = sessionToken.isEmpty() ? credentials.read() : sessionToken;
        URI url = endpoint(sessionBase.isEmpty() ? credentials.base(DEFAULT) : sessionBase); validate(url, token);
        if (prompt.contains(token)) throw new IllegalArgumentException("请从问题中移除 API Key");
        return request(url, token, prompt, 4000);
    }
    private static void test(URI url, String token) throws Exception { request(url, token, "只回复 OK", 16); }
    private static String request(URI url, String token, String prompt, int limit) throws Exception {
        HttpsURLConnection connection = (HttpsURLConnection) url.toURL().openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(30000);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Authorization", "Bearer " + token);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] payload = new JSONObject().put("model", PLAN.equalsIgnoreCase(url.getHost()) ? "qwen3.8-flash" : "qwen-flash")
                .put("enable_thinking", false).put("max_tokens", limit)
                .put("messages", new JSONArray().put(new JSONObject().put("role", "user").put("content", prompt)))
                .toString().getBytes(StandardCharsets.UTF_8);
            connection.setDoOutput(true);
            connection.setFixedLengthStreamingMode(payload.length);
            try (java.io.OutputStream output = connection.getOutputStream()) { output.write(payload); }
            int status = connection.getResponseCode();
            if (status != 200) throw new java.io.IOException(status == 401 ? "密钥无效或已过期" : status == 429 ? "额度不足或请求过于频繁" : "模型请求失败（HTTP " + status + "）");
            try (java.io.InputStream input = connection.getInputStream()) {
                java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
                byte[] chunk = new byte[2048];
                int count;
                while ((count = input.read(chunk)) != -1) {
                    buffer.write(chunk, 0, count);
                    if (buffer.size() > 65536) throw new java.io.IOException("Response too large");
                }
                byte[] response = buffer.toByteArray();
                JSONObject choice = new JSONObject(new String(response, StandardCharsets.UTF_8)).getJSONArray("choices").getJSONObject(0);
                if (!"stop".equals(choice.optString("finish_reason"))) throw new java.io.IOException("回答未完成，请缩短问题后重试");
                return choice.getJSONObject("message").getString("content");
            }
        } finally { connection.disconnect(); }
    }
}
