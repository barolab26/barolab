package com.barolab.harubible;
import org.junit.Test;
import static org.junit.Assert.*;
public class VoiceChoiceTest {
 @Test public void freshReminderOverridesRestoredReadingButRotationDoesNot(){assertTrue(DailyReading.opensToday(DailyReading.OPEN_TODAY,102,101));assertFalse(DailyReading.opensToday(DailyReading.OPEN_TODAY,102,102));assertTrue(DailyReading.opensToday(DailyReading.OPEN_TODAY,0,-1));assertFalse(DailyReading.opensToday(null,103,102));}
 @Test public void missingOrBrokenRecordingFallsBackExactlyOnce(){int[] calls={0,0};VoiceChoice.play("female","psa-23-1",p->{calls[0]++;return false;},()->calls[1]++);assertArrayEquals(new int[]{1,1},calls);}
 @Test public void successfulRecordingAndDeviceChoiceNeverPlayTogether(){int[] calls={0,0};VoiceChoice.play("male","psa-23-1",p->{calls[0]++;return true;},()->calls[1]++);assertArrayEquals(new int[]{1,0},calls);VoiceChoice.play("device","psa-23-1",p->{fail("device must not request a recording");return false;},()->calls[1]++);assertArrayEquals(new int[]{1,1},calls);}
 @Test public void packagedVoicesUseExactVerseIds(){assertEquals("voice/female/psa-23-1.ogg",VoiceChoice.recordedPath("female","psa-23-1"));assertEquals("voice/male/joh-14-27.ogg",VoiceChoice.recordedPath("male","joh-14-27"));}
 @Test public void deviceOrUnknownVoiceFallsBackWithoutAFile(){assertNull(VoiceChoice.recordedPath("device","psa-23-1"));assertNull(VoiceChoice.recordedPath("old-setting","psa-23-1"));assertNull(VoiceChoice.recordedPath("female","../secret"));assertNull(VoiceChoice.recordedPath("male",null));}
 @Test public void notificationLaunchIsDistinctFromOrdinaryResume(){assertTrue(DailyReading.opensToday(DailyReading.OPEN_TODAY));assertFalse(DailyReading.opensToday(null));assertFalse(DailyReading.opensToday("android.intent.action.MAIN"));}
 @Test public void backgroundSelectionKeepsItsBounds(){assertEquals(0,VerseCard.backgroundIndex(-1));assertEquals(5,VerseCard.backgroundIndex(5));assertEquals(5,VerseCard.backgroundIndex(100));}
}
