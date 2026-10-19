package com.barolab.voicebasket;

import java.util.HashSet;
import java.util.Set;

/** Main-thread UI still needs a token guard: queued clicks can outlive their views. */
final class SubmissionGuard {
    private final Set<String> finished = new HashSet<>();
    private String pending;
    boolean claim(String token, boolean current) {
        if (!current || token == null || token.isEmpty() || pending != null || finished.contains(token)) return false;
        pending = token; return true;
    }
    void finish(String token, boolean success) {
        if (!token.equals(pending)) return;
        if (success) finished.add(token);
        pending = null;
    }
}
