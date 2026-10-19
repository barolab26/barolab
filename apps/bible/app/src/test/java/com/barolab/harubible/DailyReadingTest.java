package com.barolab.harubible;
import org.junit.Test;
import static org.junit.Assert.*;
import java.time.*;

public class DailyReadingTest {
    @Test public void verseIsStableAndCyclesAcrossCalendarDays() {
        LocalDate today = LocalDate.of(2026, 10, 14);
        assertEquals(DailyReading.index(today, 30), DailyReading.index(today.plusDays(30), 30));
        assertNotEquals(DailyReading.index(today, 30), DailyReading.index(today.plusDays(1), 30));
        assertTrue(DailyReading.index(LocalDate.of(1900, 1, 1), 30) >= 0);
    }
    @Test public void reminderMovesToTomorrowAfterChosenTime() {
        ZonedDateTime now = ZonedDateTime.of(2026, 10, 14, 9, 0, 0, 0, ZoneId.of("Asia/Seoul"));
        assertEquals(LocalDate.of(2026, 10, 15), Instant.ofEpochMilli(DailyReading.nextReminder(now, 8, 0)).atZone(now.getZone()).toLocalDate());
        assertEquals(LocalDate.of(2026, 10, 14), Instant.ofEpochMilli(DailyReading.nextReminder(now, 10, 0)).atZone(now.getZone()).toLocalDate());
    }
    @Test public void springClockChangeStillSchedulesInFuture() {
        ZonedDateTime now = ZonedDateTime.of(2026, 3, 8, 0, 30, 0, 0, ZoneId.of("America/New_York"));
        assertTrue(DailyReading.nextReminder(now, 2, 30) > now.toInstant().toEpochMilli());
    }
    @Test public void equalCurrentMinuteSchedulesTomorrowRatherThanImmediately() {
        ZonedDateTime now = ZonedDateTime.of(2026, 10, 14, 8, 0, 0, 0, ZoneId.of("Asia/Seoul"));
        long result = DailyReading.nextReminder(now, 8, 0);
        ZonedDateTime expected = ZonedDateTime.of(2026, 10, 15, 8, 0, 0, 0, ZoneId.of("Asia/Seoul"));
        assertEquals(expected.toInstant().toEpochMilli(), result);
        assertTrue(result > now.toInstant().toEpochMilli());
    }
    @Test(expected = IllegalArgumentException.class) public void invalidTimeIsRejected() { DailyReading.nextReminder(ZonedDateTime.now(), 24, 0); }
    @Test(expected = IllegalArgumentException.class) public void emptyContentIsRejected() { DailyReading.index(LocalDate.now(), 0); }
}
