package com.barolab.voicebasket;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import java.util.ArrayList;

/** One bounded session; explicit network choice is made by the Activity. */
final class VoiceInput {
    interface Listener { void state(String message, boolean active); void result(String text); }
    private final Context context;
    private final Listener listener;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private SpeechRecognizer recognizer;
    private int generation;
    private boolean active;
    VoiceInput(Context context,Listener listener) {this.context=context;this.listener=listener;}
    boolean onDeviceAvailable() {return Build.VERSION.SDK_INT>=31&&SpeechRecognizer.isOnDeviceRecognitionAvailable(context);}
    boolean available() {return onDeviceAvailable()||SpeechRecognizer.isRecognitionAvailable(context);}
    void start(boolean networkAllowed) {
        cancel(); final int ticket=++generation;
        boolean local=onDeviceAvailable();
        if(!local&&!networkAllowed) {listener.state("키보드로 입력하거나 음성 제공자 사용을 선택해 주세요.",false);return;}
        try {
            recognizer=local&&Build.VERSION.SDK_INT>=31?SpeechRecognizer.createOnDeviceSpeechRecognizer(context):SpeechRecognizer.createSpeechRecognizer(context);
            recognizer.setRecognitionListener(new RecognitionListener() {
                boolean valid(){return ticket==generation&&recognizer!=null;}
                public void onReadyForSpeech(Bundle p){if(valid())listener.state("말씀해 주세요. 쉼표나 항목 사이 잠깐 쉬어 말해 보세요.",true);}
                public void onBeginningOfSpeech(){} public void onRmsChanged(float r){} public void onBufferReceived(byte[] b){}
                public void onEndOfSpeech(){if(valid())listener.state("인식 결과를 기다리고 있어요. 취소할 수 있습니다.",true);}
                public void onError(int error){if(!valid())return; finish();listener.state(errorText(error),false);}
                public void onResults(Bundle bundle){if(!valid())return;ArrayList<String> results=bundle.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);finish();if(results!=null&&!results.isEmpty())listener.result(results.get(0));else listener.state("인식된 말이 없어요. 직접 입력해 주세요.",false);}
                public void onPartialResults(Bundle partial){} public void onEvent(int type,Bundle p){}
            });
            Intent intent=new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,RecognizerIntent.LANGUAGE_MODEL_FREE_FORM).putExtra(RecognizerIntent.EXTRA_LANGUAGE,"ko-KR").putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS,false).putExtra(RecognizerIntent.EXTRA_MAX_RESULTS,1);
            if(local)intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE,true);
            active=true;listener.state(local?"기기 안에서 한국어 음성을 준비해요.":"선택한 음성 제공자가 처리합니다. 네트워크가 사용될 수 있어요.",true);recognizer.startListening(intent);
            handler.postDelayed(()->{if(ticket==generation&&active){cancel();listener.state("음성 입력 시간이 지났어요. 입력한 내용을 확인하거나 다시 눌러 주세요.",false);}},45000);
        }catch(RuntimeException error){cancel();listener.state("음성 입력을 시작하지 못했어요. 키보드 입력은 사용할 수 있습니다.",false);}
    }
    void stop(){if(recognizer!=null&&active)try{recognizer.stopListening();listener.state("말하기를 마쳤어요. 인식 결과를 기다리고 있습니다.",true);}catch(RuntimeException e){cancel();listener.state("입력을 마치지 못했어요. 다시 시도해 주세요.",false);}}
    void cancel(){++generation;active=false;handler.removeCallbacksAndMessages(null);if(recognizer!=null){try{recognizer.cancel();}catch(RuntimeException ignored){}finally{try{recognizer.destroy();}catch(RuntimeException ignored){}recognizer=null;}}}
    private void finish(){++generation;active=false;handler.removeCallbacksAndMessages(null);if(recognizer!=null){try{recognizer.destroy();}catch(RuntimeException ignored){}recognizer=null;}}
    private String errorText(int code){
        if(code==SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS)return "마이크 권한이 없어요. 키보드로 입력하거나 기기 설정에서 허용해 주세요.";
        if(code==SpeechRecognizer.ERROR_NO_MATCH||code==SpeechRecognizer.ERROR_SPEECH_TIMEOUT)return "말을 확인하지 못했어요. 직접 입력하거나 다시 말해 주세요.";
        if(code==SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED||code==SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE)return "현재 음성 제공자에 한국어가 준비되지 않았어요. 키보드로 입력해 주세요. 네트워크 음성으로 자동 전환하지 않습니다.";
        return "음성 처리 오류가 발생했어요. 기존 목록은 유지됩니다. 키보드로 입력하거나 다시 시도해 주세요.";
    }
}
