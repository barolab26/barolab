package com.barolab.morningcard;
import org.junit.Test;
import static org.junit.Assert.*;
public class GreetingScheduleTest {
 @Test public void photoGridPreservesLegacyThemeIds(){int[] order=GreetingSchedule.backgroundOrder();assertEquals(18,order.length);java.util.Set<Integer> ids=new java.util.HashSet<>();for(int id:order)ids.add(id);assertEquals(18,ids.size());assertEquals(6,order[0]);assertEquals(17,order[11]);assertEquals(0,order[12]);for(int id=0;id<18;id++)assertEquals(id,GreetingSchedule.theme(id));assertEquals(17,GreetingSchedule.theme(99));}
 @Test public void dailyPhotoChangesAtMidnightAndWraps(){java.time.LocalDate d=java.time.LocalDate.of(2026,12,31);assertFalse(GreetingSchedule.changed(d,d));assertTrue(GreetingSchedule.changed(d,d.plusDays(1)));assertNotEquals(GreetingSchedule.dailyTheme(d),GreetingSchedule.dailyTheme(d.plusDays(1)));assertEquals(GreetingSchedule.dailyTheme(d),GreetingSchedule.dailyTheme(d.plusDays(12)));}
 @Test public void weekdayRecommendationsCoverEveryDay(){java.util.Set<String> categories=new java.util.HashSet<>();for(int d=1;d<=7;d++)categories.add(GreetingSchedule.category(d));assertEquals(7,categories.size());}
 @Test public void calendarSeasonsWrapYearWithoutWeatherInference(){assertEquals(3,GreetingSchedule.seasonalTheme(12));assertEquals(3,GreetingSchedule.seasonalTheme(1));assertEquals(3,GreetingSchedule.seasonalTheme(2));assertEquals(0,GreetingSchedule.seasonalTheme(3));assertEquals(1,GreetingSchedule.seasonalTheme(6));assertEquals(2,GreetingSchedule.seasonalTheme(9));}
 @Test(expected=IllegalArgumentException.class)public void rejectsInvalidCalendarMonth(){GreetingSchedule.seasonalTheme(0);}
}
