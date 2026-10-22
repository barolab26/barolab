package com.barolab.harubible;

import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.os.Handler;
import android.os.Looper;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import java.util.*;

/** Device synthesis only: language availability is never treated as proof of offline support. */
public final class OfflineTtsController {
    public enum State { INITIALIZING, READY, NEEDS_VOICE, NO_ENGINE, ENGINE_ERROR, STARTING, SPEAKING }
    public interface Listener { void onStateChanged(State state, String detail); }
    private final Context context;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private TextToSpeech engine;
    private State state = State.INITIALIZING;
    private boolean closed, started;
    private int generation;
    private String enginePackage, label = "", activeUtterance, selectedVoiceName = "";

    public OfflineTtsController(Context context, Listener listener) {
        this.context = context.getApplicationContext(); this.listener = listener;
    }
    public State getState() { return state; }
    public String engineLabel() { return label; }
    public String voiceDescription() { return selectedVoiceName.isEmpty() ? "한국어 오프라인 음성 미확인" : "한국어 오프라인 음성 준비됨"; }
    public void retry() { if(!closed) { started=true; initialize(); } }
    public void start() { if (!started && !closed) { started = true; initialize(); } }
    public void refresh() {
        if (closed) return;
        if (!started) { start(); return; }
        if (state == State.INITIALIZING) return;
        try {
            if(engine!=null && !Objects.equals(enginePackage,engine.getDefaultEngine())) { initialize();return; }
            if(state==State.READY && engine!=null) {
                Voice current=engine.getVoice();
                if(eligible(current) && Objects.equals(current.getName(),selectedVoiceName)) return;
                initialize();
            }
        } catch(RuntimeException error) { initialize(); }
    }
    private void publish(State next, String detail) {
        if (!closed) { state = next; listener.onStateChanged(next, detail); }
    }
    private void initialize() {
        int ticket = ++generation;
        releaseEngine(); selectedVoiceName="";
        publish(State.INITIALIZING, "기기 음성을 확인하고 있어요.");
        try {
            engine = new TextToSpeech(context, status -> main.post(() -> initialized(ticket, status, 0)));
            main.postDelayed(() -> {
                if (!closed && ticket == generation && state == State.INITIALIZING) {
                    ++generation; releaseEngine();
                    publish(State.ENGINE_ERROR, "음성 엔진 연결이 지연돼요. 음성 설정을 확인하고 다시 시도해 주세요.");
                }
            }, 15000);
        } catch (RuntimeException error) {
            publish(State.ENGINE_ERROR, "기기 음성 엔진에 연결하지 못했어요. 음성 설정에서 기본 엔진을 확인해 주세요.");
        }
    }
    private void initialized(int ticket, int status, int voiceAttempt) {
        if (closed || ticket != generation || engine == null) return;
        try {
            List<TextToSpeech.EngineInfo> engines = engine.getEngines();
            enginePackage = engine.getDefaultEngine(); label = "";
            if (engines == null || engines.isEmpty()) {
                publish(State.NO_ENGINE, "기기에 음성 엔진이 없어요. 음성 설정에서 엔진 설치와 기본 엔진을 확인해 주세요."); return;
            }
            for (TextToSpeech.EngineInfo info : engines) if (info.name.equals(enginePackage)) label = info.label;
            if (status != TextToSpeech.SUCCESS) {
                publish(State.ENGINE_ERROR, "음성 엔진을 시작하지 못했어요. 음성 설정에서 다른 설치된 엔진을 기본으로 선택한 뒤 돌아와 주세요."); return;
            }
            // Some engines populate their voice list only after language selection.
            engine.setLanguage(Locale.KOREAN);
            Set<Voice> available = engine.getVoices();
            List<Voice> candidates = new ArrayList<>();
            if (available != null) for (Voice v : available) if (eligible(v)) candidates.add(v);
            candidates.sort(Comparator.comparing(Voice::getName));
            // Prefer the engine's working embedded/default Korean voice, even if enumeration lags.
            Voice current=engine.getVoice();
            if(eligible(current)){candidates.removeIf(v -> Objects.equals(v.getName(),current.getName()));candidates.add(0,current);}
            boolean selected = OfflineVoicePolicy.selectFirstWorking(candidates, v ->
                    engine.setVoice(v) == TextToSpeech.SUCCESS && eligible(engine.getVoice())
                            && v.getName().equals(engine.getVoice().getName()));
            if (!selected) {
                if (voiceAttempt < 2) {
                    // Vendor engines can publish voices shortly after onInit when data/service changes.
                    // Retry within this same generation at 750ms and 2000ms; never recreate indefinitely.
                    main.postDelayed(() -> initialized(ticket, status, voiceAttempt + 1),
                            voiceAttempt == 0 ? 750 : 1250);
                    return;
                }
                publish(State.NEEDS_VOICE, "현재 기본 엔진에서 설치된 한국어 오프라인 음성을 확인하지 못했어요. 음성 데이터를 설치하거나 기본 엔진을 바꾼 뒤 돌아와 주세요."); return;
            }
            selectedVoiceName=engine.getVoice().getName();
            engine.setSpeechRate(0.86f);
            engine.setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build());
            engine.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                private void dispatch(String id, int errorCode) { main.post(() -> {
                    if (!closed && ticket == generation && Objects.equals(id, activeUtterance)) {
                        activeUtterance = null;
                        publish(errorCode == TextToSpeech.ERROR_NOT_INSTALLED_YET ? State.NEEDS_VOICE
                                : errorCode != 0 ? State.ENGINE_ERROR : State.READY, errorCode == TextToSpeech.ERROR_NOT_INSTALLED_YET
                                ? "한국어 음성 데이터 설치를 완료한 뒤 다시 시도해 주세요."
                                : errorCode != 0
                                ? "기기 음성 재생에 실패했어요. 미디어 음량과 음성 설정을 확인하고 다시 시도해 주세요."
                                : "오프라인 음성으로 들을 준비가 됐어요.");
                    }
                }); }
                @Override public void onStart(String id) { main.post(()->{
                    if(!closed && ticket==generation && Objects.equals(id,activeUtterance) && state==State.STARTING)
                        publish(State.SPEAKING,"한국어 소리를 읽고 있어요. 미디어 음량을 조절할 수 있어요.");
                }); }
                @Override public void onDone(String id) { dispatch(id, 0); }
                @Override public void onError(String id) { dispatch(id, TextToSpeech.ERROR); }
                @Override public void onError(String id, int code) { dispatch(id, code); }
            });
            publish(State.READY, "오프라인 음성으로 들을 준비가 됐어요.");
        } catch (RuntimeException error) {
            publish(State.ENGINE_ERROR, "음성 정보를 확인하지 못했어요. 음성 설정에서 기본 엔진을 확인해 주세요.");
        }
    }
    private static boolean eligible(Voice voice) {
        if (voice == null || voice.getLocale() == null) return false;
        Set<String> features = voice.getFeatures();
        return OfflineVoicePolicy.eligible(voice.getLocale().getLanguage(), voice.isNetworkConnectionRequired(), features);
    }
    public boolean speak(String text) {
        if (closed || engine == null || (state != State.READY && state != State.SPEAKING) || text == null || text.trim().isEmpty()) return false;
        try {
            if (!eligible(engine.getVoice())) { publish(State.NEEDS_VOICE, "한국어 오프라인 음성을 다시 확인해 주세요."); return false; }
            activeUtterance = UUID.randomUUID().toString();
            int result = engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, activeUtterance);
            if (result == TextToSpeech.SUCCESS) {
                final String requested=activeUtterance; final int ticket=generation;
                publish(State.STARTING,"소리를 요청했어요. 시작을 기다리고 있어요.");
                main.postDelayed(()->{if(!closed&&ticket==generation&&state==State.STARTING&&Objects.equals(requested,activeUtterance)){
                    activeUtterance=null;try{engine.stop();}catch(RuntimeException ignored){}
                    publish(State.ENGINE_ERROR,"음성 재생 시작이 지연돼요. 다시 시도하거나 기기 음성 설정을 확인해 주세요.");
                }},8000);return true;
            }
        } catch (RuntimeException ignored) { }
        activeUtterance = null;
        publish(State.ENGINE_ERROR, "기기 음성 재생을 시작하지 못했어요. 음성 설정을 확인하고 다시 시도해 주세요."); return false;
    }
    public Intent installVoiceIntent() {
        if (enginePackage == null || enginePackage.isEmpty()) return null;
        Intent intent = new Intent(TextToSpeech.Engine.ACTION_INSTALL_TTS_DATA).setPackage(enginePackage);
        return intent.resolveActivity(context.getPackageManager()) == null ? null : intent;
    }
    public Intent settingsIntent() { return new Intent("com.android.settings.TTS_SETTINGS"); }
    public void stop() {
        activeUtterance = null;
        if (engine != null) try { engine.stop(); } catch (RuntimeException ignored) { }
        if (!closed && (state == State.SPEAKING || state == State.STARTING)) publish(State.READY, "오프라인 음성으로 들을 준비가 됐어요.");
    }
    private void releaseEngine() {
        activeUtterance = null;
        if (engine != null) { try { engine.stop(); engine.shutdown(); } catch (RuntimeException ignored) { } engine = null; }
    }
    public void close() { closed = true; ++generation; main.removeCallbacksAndMessages(null); releaseEngine(); }
}
