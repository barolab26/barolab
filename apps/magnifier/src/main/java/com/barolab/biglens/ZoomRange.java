package com.barolab.biglens;

/** Hardware bounds, never a promise that every phone supports a fixed multiple. */
final class ZoomRange {
    private ZoomRange() { }
    static float clamp(float value, float min, float max) {
        if (!Float.isFinite(min) || !Float.isFinite(max) || min <= 0 || max < min) return 1f;
        return Math.max(min, Math.min(max, Float.isFinite(value) ? value : min));
    }
    static float ratio(int progress, float min, float max) {
        if (min <= 0 || max < min) return 1f;
        return clamp((float)(min * Math.pow(max / min, Math.max(0, Math.min(1000, progress)) / 1000d)), min, max);
    }
    static int progress(float ratio, float min, float max) {
        if (min <= 0 || max <= min) return 0;
        return Math.max(0, Math.min(1000, (int)Math.round(1000 * Math.log(clamp(ratio, min, max) / min) / Math.log(max / min))));
    }
}
