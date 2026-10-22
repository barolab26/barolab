package com.barolab.harubible;
import org.junit.Test;
import java.util.Collections;
import static org.junit.Assert.*;
public class OfflineVoicePolicyTest {
    @Test public void acceptsInstalledOfflineKoreanWhenVendorHasNoFeatureSet() {
        assertTrue(OfflineVoicePolicy.eligible("ko", false, null));
    }
    @Test public void rejectsNetworkEvenWhenKoreanLanguageIsSupported() {
        assertFalse(OfflineVoicePolicy.eligible("ko", true, Collections.emptySet()));
    }
    @Test public void rejectsAdvertisedButNotDownloadedVoice() {
        assertFalse(OfflineVoicePolicy.eligible("ko", false, Collections.singleton("notInstalled")));
    }
    @Test public void rejectsOtherLanguageAndMissingLanguage() {
        assertFalse(OfflineVoicePolicy.eligible("en", false, null));
        assertFalse(OfflineVoicePolicy.eligible(null, false, null));
    }
    @Test public void failedAndThrowingFirstVoicesDoNotHideLaterWorkingVoice() {
        java.util.List<String> visited = new java.util.ArrayList<>();
        assertTrue(OfflineVoicePolicy.selectFirstWorking(java.util.Arrays.asList("rejected", "broken", "working", "unused"), name -> {
            visited.add(name);
            if (name.equals("broken")) throw new IllegalStateException("vendor voice failure");
            return name.equals("working");
        }));
        assertEquals(java.util.Arrays.asList("rejected", "broken", "working"), visited);
    }
    @Test public void noWorkingVoiceDoesNotReportReady() {
        assertFalse(OfflineVoicePolicy.selectFirstWorking(java.util.Arrays.asList("a", "b"), name -> false));
        assertFalse(OfflineVoicePolicy.selectFirstWorking(Collections.emptyList(), name -> true));
    }
}
