package com.family.kitchen;

import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class BailianKey {
    private static final String ALIAS = "kitchen.bailian";
    private static final String CIPHERTEXT = "bailianKeyCiphertext";
    private static final String IV = "bailianKeyIv";
    private static final String BASE = "bailianBase";
    private final SharedPreferences preferences;

    BailianKey(SharedPreferences preferences) { this.preferences = preferences; }

    String base(String fallback) { return preferences.getString(BASE, fallback); }

    String read() throws Exception {
        String ciphertext = preferences.getString(CIPHERTEXT, "");
        if (ciphertext.isEmpty()) return "";
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, (SecretKey) keyStore().getKey(ALIAS, null),
            new GCMParameterSpec(128, Base64.decode(preferences.getString(IV, ""), Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(ciphertext, Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }

    boolean save(String base, String token) throws Exception {
        KeyStore store = keyStore();
        SecretKey key = (SecretKey) store.getKey(ALIAS, null);
        if (key == null) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            key = generator.generateKey();
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key);
        byte[] ciphertext = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        return preferences.edit().putString(BASE, base)
            .putString(CIPHERTEXT, Base64.encodeToString(ciphertext, Base64.NO_WRAP))
            .putString(IV, Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)).commit();
    }

    boolean clear() { return preferences.edit().remove(CIPHERTEXT).remove(IV).commit(); }

    private static KeyStore keyStore() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        return store;
    }
}

