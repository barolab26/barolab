package com.barolab.voicebasket;
import org.junit.Test;
import static org.junit.Assert.*;
public class VoiceInputTest {
 @Test public void singleVoiceEntryCannotReopenMicDuringRecordingPermissionOrBackground(){assertTrue(VoiceInput.canStart(false,false,false));assertFalse(VoiceInput.canStart(true,false,false));assertFalse(VoiceInput.canStart(false,true,false));assertFalse(VoiceInput.canStart(false,false,true));}
}
