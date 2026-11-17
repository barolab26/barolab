package com.barolab.harubible;

final class VoiceChoice {
    static final String[] IDS={"female","male","device"};
    static final String[] LABELS={"차분한 여성 목소리","따뜻한 남성 목소리","기기 기본 음성"};
    static void play(String choice,String verseId,java.util.function.Predicate<String> recording,Runnable device){String path=recordedPath(choice,verseId);if(path==null||!recording.test(path))device.run();}
    static int index(String choice){for(int i=0;i<IDS.length;i++)if(IDS[i].equals(choice))return i;return 2;}
    static String recordedPath(String choice,String verseId){
        if(index(choice)==2||verseId==null||!verseId.matches("[a-z0-9]+(?:-[a-z0-9]+)*"))return null;
        return "voice/"+choice+"/"+verseId+".ogg";
    }
}
