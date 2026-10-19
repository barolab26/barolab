package com.barolab.voicebasket;

import java.util.ArrayList;
import java.util.List;

/** Delimiters only. No product, quantity or Korean morphology inference. */
public final class BasketParser {
    private BasketParser() { }
    public static List<String> split(String text, boolean conjunctions) {
        if (text == null || text.trim().isEmpty()) return new ArrayList<>();
        if (text.length() > 12000) throw new IllegalArgumentException("입력은 12,000자까지 나누어 주세요.");
        String source = text.replace("\r\n", "\n").replace('\r', '\n');
        if (conjunctions) source = source.replaceAll("(?U)\\s+(그리고|및|또는|하고)\\s+", "\n");
        List<String> result = new ArrayList<>();
        for (String part : source.split("[,，、\\n]+")) {
            String name = part.trim();
            if (name.isEmpty()) continue;
            if (name.length() > 120) throw new IllegalArgumentException("한 항목은 120자까지 입력해 주세요. 쉼표나 줄바꿈으로 나눌 수 있어요.");
            result.add(name);
            if (result.size() > 100) throw new IllegalArgumentException("한 번에 100개까지 추가할 수 있어요.");
        }
        return result;
    }
}
