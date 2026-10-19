package com.barolab.harubible;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.text.Layout;
import android.view.*;
import android.widget.*;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;

public final class MainActivity extends Activity {
    private static final int INK = Color.rgb(38, 55, 48), GREEN = Color.rgb(48, 93, 80), MUTED = Color.rgb(108, 117, 107);
    private LinearLayout root, content, adContainer, nav, readingTools;
    private ScrollView scroll;
    private final List<Button> tabs = new ArrayList<>();
    private Button listenButton;
    private TextView voiceStatus, voiceDiagnostics, readingBody;
    private boolean returningFromVoiceSettings;
    private VerseRepository repository;
    private VerseRepository.Verse selected;
    private android.content.SharedPreferences preferences;
    private OfflineTtsController speech;
    private boolean pendingReminderPermission, todaySelected, disposed, savedOnly;
    private String currentPage = "today", searchQuery = "", verseOrigin = "favorites";
    private LocalDate shownDate;
    private AdsController ads;
    private final ExecutorService sharing = Executors.newSingleThreadExecutor();

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = ReminderReceiver.prefs(this);
        getWindow().setStatusBarColor(Color.TRANSPARENT);
        getWindow().setNavigationBarColor(Color.rgb(249, 247, 240));
        if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(Color.rgb(249, 247, 240));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            int left, top, right, bottom;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                left = bars.left; top = bars.top; right = bars.right; bottom = bars.bottom;
            } else { left = insets.getSystemWindowInsetLeft(); top = insets.getSystemWindowInsetTop(); right = insets.getSystemWindowInsetRight(); bottom = insets.getSystemWindowInsetBottom(); }
            view.setPadding(left, top, right, bottom); return insets;
        });
        LinearLayout brand = new LinearLayout(this);brand.setOrientation(largeSystemText()?LinearLayout.VERTICAL:LinearLayout.HORIZONTAL); brand.setGravity(largeSystemText()?Gravity.START:Gravity.CENTER_VERTICAL); brand.setPadding(dp(22), dp(10), dp(22), dp(2));
        TextView name = text(largeSystemText()?"오늘의 말씀":"오늘의 성경말씀", 21, GREEN);name.setContentDescription("오늘의 성경말씀"); name.setTypeface(Typeface.DEFAULT, Typeface.BOLD); brand.addView(name, largeSystemText()?new LinearLayout.LayoutParams(-1,-2):new LinearLayout.LayoutParams(0, -2, 1));
        TextView edition = text("선정 말씀 30개", 12, MUTED); brand.addView(edition); if (!compactHeight()) root.addView(brand);
        nav = new LinearLayout(this); nav.setPadding(dp(18), dp(2), dp(18), dp(8));
        addTab("오늘", v -> showToday()); addTab(largeSystemText()?"모음":"말씀 모음", v -> { savedOnly = false; showSearch(); }); addTab("설정", v -> showSettings()); root.addView(nav);
        readingTools = new LinearLayout(this); readingTools.setOrientation(LinearLayout.VERTICAL); readingTools.setPadding(dp(20), 0, dp(20), dp(4)); readingTools.setVisibility(View.GONE); root.addView(readingTools);
        scroll = new ScrollView(this); scroll.setId(R.id.reading_scroll); scroll.setFillViewport(true);
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(dp(20), dp(12), dp(20), dp(28)); scroll.addView(content);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        adContainer = new LinearLayout(this); adContainer.setOrientation(LinearLayout.VERTICAL); adContainer.setGravity(Gravity.CENTER); adContainer.setPadding(0, dp(12), 0, dp(8)); adContainer.setVisibility(View.GONE); root.addView(adContainer);
        setContentView(root);
        if(state!=null)returningFromVoiceSettings=state.getBoolean("returningFromVoiceSettings",false);
        if (state != null) { pendingReminderPermission = state.getBoolean("pendingReminderPermission", false); searchQuery = state.getString("searchQuery", ""); verseOrigin = state.getString("verseOrigin", "favorites"); savedOnly = state.getBoolean("savedOnly", false); }
        try {
            repository = new VerseRepository(this);
            String page = state == null ? (preferences.contains("reading_verse_id")?"savedVerse":"today") : state.getString("page", "today");
            if ("favorites".equals(page)) showFavorites();
            else if ("settings".equals(page)) showSettings();
            else if ("search".equals(page)) showSearch();
            else if ("savedVerse".equals(page)) {
                String id = state==null?preferences.getString("reading_verse_id", ""):state.getString("verseId", "");
                for (VerseRepository.Verse verse : repository.verses) if (verse.id.equals(id)) selected = verse;
                if (selected == null) showToday(); else { showVerse(selected, state==null&&preferences.getBoolean("reading_was_today",false)&&selected.id.equals(repository.today().id));restoreReadingPosition(state); }
            } else {showToday();if(state!=null)restoreReadingPosition(state);}
        }
        catch (Exception error) { content.addView(text("말씀 파일을 읽을 수 없어요.", 27, INK)); content.addView(text("앱을 다시 열어 주세요. 계속되면 배포 파일을 확인해야 합니다. 본문을 임의로 대체하지 않습니다.", 17, MUTED)); }
        speech = new OfflineTtsController(this, (status, detail) -> updateVoiceStatus(status, detail));
        speech.start();
        ads = new AdsController(this, adContainer); ads.start();
        ReminderReceiver.schedule(this);
    }

    private void clear() { rememberReading(); readingBody=null;voiceDiagnostics=null; listenButton = null; voiceStatus = null; if (speech != null) speech.stop(); content.removeAllViews(); readingTools.removeAllViews(); readingTools.setVisibility(View.GONE); scroll.post(() -> scroll.scrollTo(0, 0)); }
    private void addTab(String label, View.OnClickListener action) { Button tab = button(label, action);if(label.equals("모음"))tab.setContentDescription("말씀 모음, 전체 30개와 저장한 말씀"); tab.setTextSize(14); tab.setMinHeight(dp(48)); tabs.add(tab); nav.addView(tab, weighted()); }
    private void selectTab(int index) {
        for (int i = 0; i < tabs.size(); i++) { Button tab = tabs.get(i); boolean active = i == index; tab.setSelected(active); tab.setTextColor(active ? Color.WHITE : GREEN); tab.setTypeface(Typeface.DEFAULT, active ? Typeface.BOLD : Typeface.NORMAL); tab.setBackground(surface(active ? GREEN : Color.TRANSPARENT, active ? GREEN : Color.rgb(222, 226, 219), 13)); }
    }
    private GradientDrawable surface(int color, int stroke, int radius) { GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(radius)); if (stroke != Color.TRANSPARENT) d.setStroke(dp(1), stroke); return d; }
    private void pageTitle(String eyebrow, String title, String description) {
        content.addView(text(eyebrow, 13, MUTED)); TextView heading = text(title, 27, INK); heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD); content.addView(heading); if (!description.isEmpty()) content.addView(text(description, 15, MUTED));
    }
    private LinearLayout panel() { LinearLayout panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setPadding(dp(18), dp(16), dp(18), dp(16)); panel.setBackground(surface(Color.WHITE, Color.rgb(230, 230, 221), 20)); content.addView(panel, new LinearLayout.LayoutParams(-1, -2)); return panel; }
    private void fillButton(Button b) { b.setTextColor(Color.WHITE); b.setTypeface(Typeface.DEFAULT, Typeface.BOLD); b.setBackground(surface(GREEN, GREEN, 14)); }
    private void fullButton(LinearLayout parent, Button b) { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(5), 0, dp(5)); parent.addView(b, p); }
    private TextView text(String value, float size, int color) {
        TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setTextColor(color); view.setLineSpacing(dp(4), 1.16f); if (Build.VERSION.SDK_INT >= 29) { view.setBreakStrategy(android.graphics.text.LineBreaker.BREAK_STRATEGY_HIGH_QUALITY); view.setHyphenationFrequency(Layout.HYPHENATION_FREQUENCY_NONE); } view.setPadding(0, dp(4), 0, dp(12)); return view;
    }
    private Button button(String label, View.OnClickListener action) {
        Button button = new Button(this); button.setText(label); button.setAllCaps(false); button.setTextSize(16); button.setTextColor(GREEN); button.setMinHeight(dp(56)); button.setMinimumWidth(0);
        GradientDrawable shape = new GradientDrawable(); shape.setColor(Color.WHITE); shape.setCornerRadius(dp(14)); shape.setStroke(dp(1), Color.rgb(215, 224, 216)); button.setBackground(shape);
        button.setStateListAnimator(null); button.setPadding(dp(10), dp(10), dp(10), dp(10)); button.setOnClickListener(action); return button;
    }
    private LinearLayout.LayoutParams weighted() { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -2, 1); p.setMargins(dp(3), dp(3), dp(3), dp(3)); return p; }
    private void gap(int height) { Space space = new Space(this); content.addView(space, new LinearLayout.LayoutParams(1, dp(height))); }
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private boolean largeSystemText(){return getResources().getConfiguration().fontScale>=1.5f;}
    private boolean compactHeight() { return getResources().getConfiguration().screenHeightDp < 500; }

    private void showToday() {
        if (repository == null) return;
        todaySelected = true; shownDate = LocalDate.now(); showVerse(repository.today(), true);
    }
    private void showVerse(VerseRepository.Verse verse, boolean today) {
        clear(); selected = verse; todaySelected = today; currentPage = today ? "today" : "savedVerse"; selectTab(today ? 0 : 1);
        readingTools.setVisibility(View.VISIBLE); LinearLayout metadata = compactHeight() ? content : readingTools; metadata.addView(text((today ? LocalDate.now().format(DateTimeFormatter.ofPattern("M월 d일 EEEE", Locale.KOREAN)) : "읽던 말씀")+(compactHeight()?" · 선정 말씀 30개":""), 13, MUTED));
        LinearLayout referenceRow=new LinearLayout(this);referenceRow.setGravity(Gravity.CENTER_VERTICAL);TextView reference = text(verse.reference, 24, GREEN); reference.setTypeface(Typeface.DEFAULT, Typeface.BOLD);reference.setPadding(0,0,dp(8),0); referenceRow.addView(reference,new LinearLayout.LayoutParams(0,-2,1));metadata.addView(referenceRow);
        LinearLayout actions = new LinearLayout(this);
        listenButton = button("말씀 듣기", v -> speak()); fillButton(listenButton); actions.addView(listenButton, weighted());
        Button favorite = button(largeSystemText()?"저장":isFavorite(verse.id) ? "저장됨" : "저장하기", v -> { });favorite.setSelected(isFavorite(verse.id));favorite.setContentDescription(isFavorite(verse.id)?"저장한 말씀, 누르면 저장 취소":"말씀 저장하기");
        favorite.setOnClickListener(v -> { Set<String> saved = favorites(); boolean removed = saved.remove(verse.id); if (!removed) saved.add(verse.id); preferences.edit().putStringSet("favorites", saved).apply(); favorite.setText(largeSystemText()?"저장":saved.contains(verse.id) ? "저장됨" : "저장하기");favorite.setSelected(saved.contains(verse.id)); favorite.setContentDescription(saved.contains(verse.id) ? "저장 취소" : "말씀 저장"); toast(removed ? "저장한 말씀에서 지웠어요." : "저장한 말씀에 담았어요."); });
        actions.addView(favorite, weighted());
        Button share = button(largeSystemText()?"공유":"카드 공유", v -> { }); share.setContentDescription("말씀 카드 이미지 공유");share.setOnClickListener(v -> shareCard(share, verse)); actions.addView(share, weighted()); readingTools.addView(actions);
        voiceStatus = text("듣기를 준비하고 있어요", 12, MUTED); voiceStatus.setMaxLines(compactHeight()?4:2); (compactHeight() ? content : readingTools).addView(voiceStatus); if (speech != null) updateVoiceStatus(speech.getState(), "");
        LinearLayout card = panel();
        TextView body = text(verse.text, preferences.getInt("font_size", 30), INK); readingBody=body;body.setTypeface(Typeface.create("serif", Typeface.NORMAL)); body.setTextIsSelectable(true); body.setTextLocale(Locale.KOREAN); if (Build.VERSION.SDK_INT >= 33) body.setLineBreakWordStyle(android.graphics.text.LineBreakConfig.LINE_BREAK_WORD_STYLE_PHRASE); body.setPadding(0, dp(7), 0, dp(16)); Button sizeControl = button("글씨 " + preferences.getInt("font_size", 30)+" ▾", v -> { }); sizeControl.setTextSize(14);sizeControl.setMinHeight(dp(48));sizeControl.setPadding(dp(10),dp(6),dp(10),dp(6));sizeControl.setContentDescription("말씀 글씨 크기 바꾸기, 현재 "+preferences.getInt("font_size",30));referenceRow.addView(sizeControl,new LinearLayout.LayoutParams(-2,-2));
        sizeControl.setOnClickListener(v -> chooseReadingSize(body, sizeControl)); card.addView(body);
        TextView source = text(repository.translationName, 12, MUTED); source.setPadding(0, dp(12), 0, 0); card.addView(source);
        gap(12);
        if(!today)fullButton(content,button("오늘 말씀으로",v -> showToday()));
        if (!today && "search".equals(verseOrigin)) { fullButton(content, button("말씀 목록으로 돌아가기", v -> showSearch())); gap(4); }
        fullButton(content, button("수록된 " + repository.verses.size() + "개 말씀 찾기", v -> showSearch()));
        content.addView(text("말씀은 끝까지 스크롤해 읽을 수 있어요. 글씨 크기는 본문 위에서 바로 바꿀 수 있습니다.", 12, MUTED));
        content.addView(text(repository.verses.size() + "개 구절을 날짜에 따라 하루 하나씩 전해 드립니다.", 12, MUTED));
        if (BuildConfig.IS_PREVIEW) content.addView(text("내부 테스트 버전 · Google 테스트 광고 사용", 11, MUTED));
        if (!repository.rightsConfirmed) content.addView(text("본문 권리 확인 전 미리보기 · 출시용이 아닙니다.", 13, Color.rgb(135, 78, 35)));
    }
    private void shareCard(Button share, VerseRepository.Verse verse) {
        share.setEnabled(false); sharing.execute(() -> {
            try {
                Intent intent = VerseCard.share(this, verse, repository.translationName + " · " + repository.copyrightNotice);
                runOnUiThread(() -> { if (!disposed && !isFinishing() && !isDestroyed()) { share.setEnabled(true); try { startActivity(Intent.createChooser(intent, "말씀 카드 공유")); } catch (ActivityNotFoundException e) { toast("이미지를 공유할 앱이 설치되어 있지 않아요."); } } });
            } catch (Exception e) { runOnUiThread(() -> { if (!disposed) { share.setEnabled(true); toast("카드를 만들지 못했어요. 다시 시도해 주세요."); } }); }
        });
    }
    private void chooseReadingSize(TextView body, Button control) {
        final int[] sizes = {24, 30, 36, 42}; final String[] labels = {"24 · 작게", "30 · 보통", "36 · 크게", "42 · 아주 크게"};
        int checked = 1; for (int i = 0; i < sizes.length; i++) if (sizes[i] == preferences.getInt("font_size", 30)) checked = i;
        new AlertDialog.Builder(this).setTitle("말씀 글씨 크기").setSingleChoiceItems(labels, checked, (dialog, which) -> {
            int y = scroll.getScrollY(), size = sizes[which]; preferences.edit().putInt("font_size", size).apply();
            body.setTextSize(size); control.setText("글씨 " + size+" ▾");control.setContentDescription("말씀 글씨 크기 바꾸기, 현재 "+size); scroll.post(() -> scroll.scrollTo(0, y)); dialog.dismiss();
        }).setNegativeButton("닫기", null).show();
    }
    private String normalizeSearch(String value) {
        StringBuilder normalized = new StringBuilder();
        for (int i = 0; i < value.length(); i++) if (!Character.isWhitespace(value.charAt(i)) && !Character.isSpaceChar(value.charAt(i))) normalized.append(value.charAt(i));
        return normalized.toString().toLowerCase(Locale.ROOT);
    }
    private void showSearch() {
        if (repository == null) return;
        clear(); todaySelected = false; currentPage = "search"; selectTab(1);
        pageTitle("수록된 " + repository.verses.size() + "개 말씀", "말씀 모음", "성경 전체 검색이 아닙니다. 구절 이름이나 본문의 낱말로 찾아보세요.");
        LinearLayout filters = new LinearLayout(this);
        Button all = button("전체 " + repository.verses.size() + "개", v -> { savedOnly = false; showSearch(); });
        Button saved = button("저장한 말씀", v -> { savedOnly = true; showSearch(); });
        if (savedOnly) { fillButton(saved); saved.setSelected(true); } else { fillButton(all); all.setSelected(true); }
        filters.addView(all, weighted()); filters.addView(saved, weighted()); content.addView(filters);
        EditText query = new EditText(this); query.setTextSize(18); query.setSingleLine(true); query.setHint("예: 시편 또는 도움"); query.setContentDescription("수록된 말씀 검색어"); query.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH); query.setText(searchQuery); content.addView(query, new LinearLayout.LayoutParams(-1, -2));
        fullButton(content, button("검색어 지우기", v -> query.setText("")));
        TextView count = text("", 14, MUTED); content.addView(count);
        LinearLayout results = new LinearLayout(this); results.setOrientation(LinearLayout.VERTICAL); content.addView(results);
        query.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence value, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence value, int start, int before, int countChanged) { searchQuery = value.toString(); renderSearchResults(results, count, query); }
            @Override public void afterTextChanged(android.text.Editable value) { }
        });
        query.setOnEditorActionListener((view, action, event) -> { if (action == android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH) { hideKeyboard(query); return true; } return false; });
        renderSearchResults(results, count, query); content.setFocusableInTouchMode(true); content.requestFocus();
    }
    private void hideKeyboard(View input) { android.view.inputmethod.InputMethodManager keyboard = (android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE); if (keyboard != null) keyboard.hideSoftInputFromWindow(input.getWindowToken(), 0); }
    private void renderSearchResults(LinearLayout results, TextView count, EditText query) {
        results.removeAllViews(); String term = normalizeSearch(searchQuery); int matched = 0; Set<String> stored = favorites();
        for (VerseRepository.Verse verse : repository.verses) {
            if (savedOnly && !stored.contains(verse.id)) continue;
            if (!term.isEmpty() && !normalizeSearch(verse.reference).contains(term) && !normalizeSearch(verse.text).contains(term)) continue;
            matched++; LinearLayout card = new LinearLayout(this); card.setOrientation(LinearLayout.VERTICAL); card.setPadding(dp(18), dp(14), dp(18), dp(14)); card.setBackground(surface(Color.WHITE, Color.rgb(230, 230, 221), 18));
            TextView reference = text(verse.reference, 18, GREEN); reference.setTypeface(Typeface.DEFAULT, Typeface.BOLD); card.addView(reference);
            TextView preview = text(verse.text, 18, INK); preview.setMaxLines(2); preview.setEllipsize(android.text.TextUtils.TruncateAt.END); card.addView(preview);
            fullButton(card, button("말씀 읽기 · 듣기", v -> { hideKeyboard(query); verseOrigin = "search"; showVerse(verse, false); }));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, 0, 0, dp(12)); results.addView(card, params);
        }
        count.setText(term.isEmpty() ? (savedOnly ? "저장한 말씀 " : "전체 ") + matched + "개" : "검색 결과 " + matched + "개");
        if (matched == 0 && savedOnly && term.isEmpty()) results.addView(text("아직 저장한 말씀이 없어요. 오늘 말씀이나 전체 목록에서 ‘저장하기’를 눌러 보세요.", 18, MUTED));
        else if (matched == 0) results.addView(text("찾는 말씀이 없어요. 더 짧은 낱말로 찾거나 검색어를 지워 보세요. 수록된 " + repository.verses.size() + "개 말씀 안에서만 찾습니다.", 18, MUTED));
    }
    private Set<String> favorites() { return new HashSet<>(preferences.getStringSet("favorites", Collections.emptySet())); }
    private boolean isFavorite(String id) { return favorites().contains(id); }
    private void showFavorites() { savedOnly = true; showSearch(); }
    private void updateVoiceStatus(OfflineTtsController.State state, String detail) {
        if (disposed) return;
        String label, description;
        switch (state) {
            case INITIALIZING: label = "음성 준비 중"; description = "기기의 한국어 음성을 확인하고 있어요."; break;
            case STARTING: label = "시작 대기 · 취소"; description = "기기 음성의 시작 응답을 기다리고 있어요."; break;
            case SPEAKING: label = "듣기 멈춤"; description = "말씀을 읽고 있어요. 버튼을 누르면 멈춥니다."; break;
            case READY: label = "말씀 듣기"; description = "기기 한국어 음성 · 인터넷 없이 들을 수 있어요."; break;
            case NEEDS_VOICE: label = "음성 준비하기"; description = "기본 음성 엔진에서 한국어 오프라인 음성을 확인하지 못했어요."; break;
            case NO_ENGINE: label = "음성 준비하기"; description = "이 기기에 음성 읽기 기능을 준비해 주세요."; break;
            default: label = "듣기 다시 시도"; description = "기기 음성을 연결하지 못했어요. 설정을 확인할 수 있습니다.";
        }
        if (listenButton != null) {listenButton.setContentDescription(label);
            if(largeSystemText()&&!currentPage.equals("settings")){
                switch(state){case READY:label="듣기";break;case SPEAKING:label="멈춤";break;case STARTING:label="취소";break;case INITIALIZING:label="준비";break;case ENGINE_ERROR:label="다시";break;default:label="설정";}
            }
            if(currentPage.equals("settings") && state==OfflineTtsController.State.READY)label="짧은 소리 확인";listenButton.setText(label); listenButton.setEnabled(state != OfflineTtsController.State.INITIALIZING); }
        if (voiceStatus != null) {voiceStatus.setText(detail == null || detail.isEmpty() ? description : detail);voiceStatus.setVisibility(!currentPage.equals("settings")&&state==OfflineTtsController.State.READY?View.GONE:View.VISIBLE);}
        if(voiceDiagnostics!=null&&speech!=null)voiceDiagnostics.setText("기본 엔진: "+(speech.engineLabel().isEmpty()?"확인 중":speech.engineLabel())+"\n"+speech.voiceDescription()+"\n소리가 들리지 않으면 휴대폰의 미디어 음량을 확인해 주세요.");
    }
    private void speak() {
        if (selected == null || speech == null) return;
        OfflineTtsController.State state = speech.getState();
        if (state == OfflineTtsController.State.SPEAKING || state == OfflineTtsController.State.STARTING) { speech.stop(); return; }
        if (state == OfflineTtsController.State.INITIALIZING) { toast("기기 음성을 준비하고 있어요. 잠시만 기다려 주세요."); return; }
        if (state == OfflineTtsController.State.READY) { if (speech.speak(selected.reference + ". " + selected.text)) return; state = speech.getState(); }
        if (state == OfflineTtsController.State.ENGINE_ERROR) {
            new AlertDialog.Builder(this).setTitle("기기 음성 연결 확인")
                .setMessage("음성 엔진 연결이나 재생에 실패했어요. 다시 연결하거나 기기의 기본 음성 엔진과 미디어 음량을 확인해 주세요.")
                .setPositiveButton("다시 연결", (d, w) -> speech.retry()).setNeutralButton("음성 설정", (d, w) -> openVoiceIntent(false)).setNegativeButton("닫기", null).show(); return;
        }
        new AlertDialog.Builder(this).setTitle(state == OfflineTtsController.State.NO_ENGINE ? "음성 읽기 기능이 필요해요" : "한국어 음성 준비")
            .setMessage("현재 기본 음성 엔진에서 한국어 오프라인 음성을 확인하지 못했어요. 준비한 뒤 앱으로 돌아오면 다시 확인합니다.\n\n" + voiceSetupHelp() + "\n\n말씀 읽기와 저장은 계속 사용할 수 있어요.")
            .setPositiveButton("음성 설치", (d, w) -> openVoiceIntent(true))
            .setNeutralButton("음성 설정", (d, w) -> openVoiceIntent(false)).setNegativeButton("나중에", null).show();
    }
    private String voiceSetupHelp() {
        return "갤럭시에서는 설정 → 일반 → 글자 읽어주기를 확인해 주세요. 기본 엔진 옆 설정에서 ‘음성 데이터 설치’ → ‘한국어’를 선택하거나 준비된 다른 기본 엔진을 선택합니다. 메뉴 이름은 기기와 엔진에 따라 다를 수 있어요. 찾기 어려우면 설정에서 ‘글자 읽어주기’ 또는 ‘텍스트 음성 변환’을 검색해 주세요.";
    }
    private boolean launchVoiceIntent(Intent intent) {
        if (intent == null) return false;
        try { startActivity(intent);returningFromVoiceSettings=true; return true; }
        catch (ActivityNotFoundException | SecurityException ignored) { return false; }
    }
    private void openVoiceIntent(boolean install) {
        if (speech == null) return;
        if (install && launchVoiceIntent(speech.installVoiceIntent())) return;
        if (launchVoiceIntent(speech.settingsIntent())) return;
        toast("설정에서 ‘글자 읽어주기’ 또는 ‘텍스트 음성 변환’을 검색해 주세요.");
        if (launchVoiceIntent(new Intent(Settings.ACTION_SETTINGS))) return;
        new AlertDialog.Builder(this).setTitle("기기 음성 설정 안내").setMessage(voiceSetupHelp()).setPositiveButton("확인", null).show();
    }
    private void showSettings() {
        clear(); todaySelected = false; currentPage = "settings"; selectTab(2); pageTitle("읽는 시간을 편안하게", "설정", "글씨와 알림, 기기 음성을 나에게 맞춰 보세요.");
        LinearLayout reading = panel(); reading.addView(text("글씨 크기", 19, GREEN));
        int current = preferences.getInt("font_size", 30);
        reading.addView(text("현재 " + current + " · 말씀 본문에 적용됩니다", 13, MUTED));
        LinearLayout sizes = new LinearLayout(this);
        for (int size : new int[]{24, 30, 36, 42}) { Button choice = button(String.valueOf(size), v -> { preferences.edit().putInt("font_size", size).apply(); showSettings(); }); if (size == current) { fillButton(choice); choice.setSelected(true); } choice.setContentDescription("본문 글씨 " + size + (size == current ? ", 현재 선택" : "")); sizes.addView(choice, weighted()); }
        reading.addView(sizes); TextView sample = text("나의 도움이 천지를 지으신 여호와에게서로다", current, INK); sample.setPadding(0, dp(18), 0, 0); sample.setTypeface(Typeface.create("serif", Typeface.NORMAL)); reading.addView(sample); reading.addView(text("시편 121:2 · 글씨 미리보기", 12, MUTED)); gap(16);
        LinearLayout audio = panel(); audio.addView(text("말씀 듣기", 19, GREEN));
        voiceStatus = text("기기의 음성을 확인하고 있어요.", 14, MUTED); audio.addView(voiceStatus);
        voiceDiagnostics=text("",12,MUTED);audio.addView(voiceDiagnostics);
        listenButton=button("짧은 소리 확인",v -> {
            if(speech==null)return;
            if(speech.getState()==OfflineTtsController.State.SPEAKING||speech.getState()==OfflineTtsController.State.STARTING){speech.stop();return;}
            if(speech.getState()==OfflineTtsController.State.READY)speech.speak("오늘도 평안한 하루 보내세요.");else toast("음성 상태를 확인하고 다시 확인을 눌러 주세요.");
        });fullButton(audio,listenButton);
        fullButton(audio,button("한국어 음성 다시 확인",v -> {if(speech!=null)speech.retry();}));
        fullButton(audio, button("기기 음성 설정", v -> { if (speech != null) openVoiceIntent(false); }));
        audio.addView(text(voiceSetupHelp(), 13, MUTED));
        if (speech != null) updateVoiceStatus(speech.getState(), ""); gap(16);
        LinearLayout reminder = panel(); reminder.addView(text("하루 한 번 알림", 19, GREEN));
        String time = String.format(Locale.KOREAN, "%02d:%02d", preferences.getInt("hour", 8), preferences.getInt("minute", 0));
        boolean enabled = preferences.getBoolean("reminder_enabled", false) && ReminderReceiver.canNotify(this);
        TextView alarmState = text(enabled ? time + "에 말씀 읽을 시간" : "알림 꺼짐", 21, INK); alarmState.setTypeface(Typeface.DEFAULT, Typeface.BOLD); reminder.addView(alarmState);
        fullButton(reminder, button(enabled ? "알림 시간 바꾸기" : "알림 켜기 · 시간 선택", v -> new TimePickerDialog(this, (view, hour, minute) -> {
            preferences.edit().putInt("hour", hour).putInt("minute", minute).apply();
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) { pendingReminderPermission = true; requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 71); } else enableReminder();
        }, preferences.getInt("hour", 8), preferences.getInt("minute", 0), true).show()));
        if (enabled) fullButton(reminder, button("알림 끄기", v -> { preferences.edit().putBoolean("reminder_enabled", false).apply(); ReminderReceiver.schedule(this); showSettings(); }));
        reminder.addView(text("기기 절전 상태에 따라 늦게 도착할 수 있어요. 알림을 꺼도 읽기는 그대로 사용할 수 있습니다.", 13, MUTED)); gap(16);
        LinearLayout about = panel(); about.addView(text("안내와 도움", 19, GREEN));
        fullButton(about, button("본문 출처 · 앱 개인정보 안내", v -> showAbout()));
        fullButton(about, button("광고 개인정보 선택", v -> { if (ads != null) ads.privacyOptions(); }));
        fullButton(about, button("웹 개인정보처리방침", v -> {
            try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://haru-malsseum.pages.dev/privacy"))); } catch (ActivityNotFoundException e) { toast("브라우저가 설치되어 있지 않아요."); }
        }));
        fullButton(about, button("지원 문의", v -> {
            try { startActivity(new Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:baro76650@gmail.com")).putExtra(Intent.EXTRA_SUBJECT, "오늘의 성경말씀 앱 문의")); } catch (ActivityNotFoundException e) { new AlertDialog.Builder(this).setMessage("지원 문의: baro76650@gmail.com").setPositiveButton("확인", null).show(); }
        }));
        gap(12); content.addView(text("오늘의 성경말씀 · 30개 선정 구절 | " + BuildConfig.VERSION_NAME, 12, MUTED));
    }
    private void enableReminder() {
        boolean allowed = ReminderReceiver.canNotify(this);
        preferences.edit().putBoolean("reminder_enabled", allowed).apply(); ReminderReceiver.schedule(this); showSettings();
        if (!allowed) new AlertDialog.Builder(this).setMessage("기기에서 알림이 허용되지 않았어요. 읽기에는 영향이 없습니다.").setPositiveButton("기기 알림 설정", (d, w) -> startActivity(new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName()))).setNegativeButton("닫기", null).show();
    }
    private void showAbout() {
        String source = repository == null ? "본문을 불러오지 못했습니다." : repository.translationName + "\n\n" + repository.copyrightNotice + "\n\n" + repository.sourceUrl;
        new AlertDialog.Builder(this).setTitle("본문 출처와 개인정보").setMessage(source + "\n\n말씀과 즐겨찾기·알림 설정은 이 기기에 저장합니다. 계정 가입과 분석 SDK는 없습니다. 광고·동의 기능은 Google SDK와 통신할 수 있지만 말씀 본문, 즐겨찾기 내용, 기도 내용이나 종교 관심 분류를 광고 요청에 넣지 않습니다.\n\n소리로 듣기는 기기에 설치된 한국어 오프라인 음성을 선택합니다. 카드 공유는 선택한 다른 앱으로 이미지를 전달합니다.")
                .setPositiveButton("닫기", null).setNeutralButton("본문 제공처", (d, w) -> { if (repository != null) try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(repository.sourceUrl))); } catch (ActivityNotFoundException e) { toast("브라우저가 설치되어 있지 않아요."); } }).show();
    }
    private boolean readingPage(){return selected!=null&&readingBody!=null&&(currentPage.equals("today")||currentPage.equals("savedVerse"));}
    private void writeReadingAnchor(Bundle out){
        int anchor=-1;float lineOffset=0;
        if(readingPage()&&readingBody.getLayout()!=null){android.graphics.Rect r=new android.graphics.Rect();readingBody.getDrawingRect(r);content.offsetDescendantRectToMyCoords(readingBody,r);int y=scroll.getScrollY()-r.top;
            if(y>=0){android.text.Layout l=readingBody.getLayout();int line=l.getLineForVertical(y);anchor=l.getLineStart(line);lineOffset=(y-l.getLineTop(line))/(float)Math.max(1,l.getLineBottom(line)-l.getLineTop(line));}}
        out.putInt("readingAnchor",anchor);out.putFloat("readingLineOffset",lineOffset);
    }
    private void rememberReading(){
        if(!readingPage()||preferences==null)return;Bundle anchor=new Bundle();writeReadingAnchor(anchor);
        preferences.edit().putString("reading_verse_id",selected.id).putBoolean("reading_was_today",currentPage.equals("today")).putInt("reading_y",scroll.getScrollY()).putInt("reading_anchor",anchor.getInt("readingAnchor",-1)).putFloat("reading_line_offset",anchor.getFloat("readingLineOffset",0)).apply();
    }
    private void restoreReadingPosition(Bundle state){
        final int y=state==null?preferences.getInt("reading_y",0):state.getInt("readingY",0);
        final int anchor=state==null?preferences.getInt("reading_anchor",-1):state.getInt("readingAnchor",-1);
        final float fraction=state==null?preferences.getFloat("reading_line_offset",0):state.getFloat("readingLineOffset",0);
        scroll.post(()->{if(readingBody==null)return;int target=y;
            if(anchor>=0&&readingBody.getLayout()!=null){android.text.Layout l=readingBody.getLayout();int line=l.getLineForOffset(Math.min(anchor,readingBody.length()));android.graphics.Rect r=new android.graphics.Rect();readingBody.getDrawingRect(r);content.offsetDescendantRectToMyCoords(readingBody,r);target=r.top+l.getLineTop(line)+Math.round(fraction*(l.getLineBottom(line)-l.getLineTop(line)));}
            scroll.scrollTo(0,Math.max(0,target));});
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == 71 && pendingReminderPermission) { pendingReminderPermission = false; enableReminder(); }
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        rememberReading();state.putBoolean("returningFromVoiceSettings",returningFromVoiceSettings);state.putInt("readingY",scroll.getScrollY());writeReadingAnchor(state);
        state.putString("page", currentPage); state.putBoolean("savedOnly", savedOnly); state.putString("searchQuery", searchQuery); state.putString("verseOrigin", verseOrigin); state.putBoolean("pendingReminderPermission", pendingReminderPermission);
        if (selected != null) state.putString("verseId", selected.id);
        super.onSaveInstanceState(state);
    }
    @Override public void onResume() { super.onResume(); if (speech != null) {if(returningFromVoiceSettings){returningFromVoiceSettings=false;speech.retry();}else speech.refresh();} if (ads != null) ads.resume(); if (repository != null && todaySelected && shownDate != null && !shownDate.equals(LocalDate.now())) showToday(); }
    @Override public void onPause() { rememberReading();if (speech != null) speech.stop(); if (ads != null) ads.pause(); super.onPause(); }
    @Override public void onDestroy() { disposed = true; if (speech != null) speech.close(); if (ads != null) ads.destroy(); sharing.shutdownNow(); super.onDestroy(); }
    private void toast(String message) { Toast.makeText(this, message, Toast.LENGTH_LONG).show(); }
}
