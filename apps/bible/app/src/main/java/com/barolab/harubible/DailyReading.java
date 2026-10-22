package com.barolab.harubible;

import java.time.LocalDate;
import java.time.ZonedDateTime;

/** Local calendar rules: no tracking identifier and no network dependency. */
public final class DailyReading {
    private DailyReading() { }
    public static int index(LocalDate date, int size) {
        if (size <= 0) throw new IllegalArgumentException("Empty verse collection");
        return (int) Math.floorMod(date.toEpochDay(), (long) size);
    }
    public static long nextReminder(ZonedDateTime now, int hour, int minute) {
        if (hour < 0 || hour > 23 || minute < 0 || minute > 59) throw new IllegalArgumentException("Invalid reminder time");
        ZonedDateTime candidate = now.toLocalDate().atTime(hour, minute).atZone(now.getZone());
        if (!candidate.isAfter(now)) candidate = now.toLocalDate().plusDays(1).atTime(hour, minute).atZone(now.getZone());
        return candidate.toInstant().toEpochMilli();
    }
}
