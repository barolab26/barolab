package com.barolab.harubible;

import java.util.Set;
import java.util.List;
import java.util.function.Predicate;

/** Pure eligibility rule, independent of vendor engine names and Android callbacks. */
final class OfflineVoicePolicy {
    static <T> boolean selectFirstWorking(List<T> candidates, Predicate<T> attempt) {
        for (T candidate : candidates) {
            try { if (attempt.test(candidate)) return true; }
            catch (RuntimeException ignored) { /* A broken vendor voice must not hide later valid voices. */ }
        }
        return false;
    }
    private OfflineVoicePolicy() { }
    static boolean eligible(String language, boolean requiresNetwork, Set<String> features) {
        return "ko".equals(language) && !requiresNetwork
                && (features == null || !features.contains("notInstalled"));
    }
}
