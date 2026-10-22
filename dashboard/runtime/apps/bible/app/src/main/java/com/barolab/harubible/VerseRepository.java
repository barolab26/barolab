package com.barolab.harubible;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

public final class VerseRepository {
    public static final class Verse {
        public final String id, reference, text, theme;
        Verse(JSONObject value) throws Exception {
            id = value.getString("id"); reference = value.getString("reference");
            text = value.getString("text"); theme = value.optString("theme", "");
            if (id.trim().isEmpty() || reference.trim().isEmpty() || text.trim().isEmpty()) throw new IllegalArgumentException("Incomplete verse");
        }
    }
    public final List<Verse> verses = new ArrayList<>();
    public final String translationName, copyrightNotice, sourceUrl;
    public final boolean rightsConfirmed;
    public VerseRepository(Context context) throws Exception {
        JSONObject data;
        try (java.io.InputStream stream = context.getAssets().open("verses.json")) {
            java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[8192]; int count;
            while ((count = stream.read(buffer)) != -1) bytes.write(buffer, 0, count);
            data = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
        }
        if (data.getInt("schemaVersion") != 1) throw new IllegalArgumentException("Unsupported collection");
        JSONObject translation = data.getJSONObject("translation");
        translationName = translation.getString("name");
        copyrightNotice = translation.getString("copyrightNotice");
        sourceUrl = translation.getString("sourceUrl");
        rightsConfirmed = translation.optBoolean("rightsConfirmed", false);
        HashSet<String> ids = new HashSet<>();
        JSONArray rows = data.getJSONArray("verses");
        for (int i = 0; i < rows.length(); i++) {
            Verse verse = new Verse(rows.getJSONObject(i));
            if (!ids.add(verse.id)) throw new IllegalArgumentException("Duplicate verse");
            verses.add(verse);
        }
        if (verses.isEmpty()) throw new IllegalArgumentException("No offline verses");
    }
    public Verse today() { return verses.get(DailyReading.index(LocalDate.now(), verses.size())); }
}
