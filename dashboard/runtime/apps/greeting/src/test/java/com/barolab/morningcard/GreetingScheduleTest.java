package com.barolab.morningcard;
import org.junit.Test;
import static org.junit.Assert.*;
public class GreetingScheduleTest {
 @Test public void weekdayRecommendationsCoverEveryDay(){java.util.Set<String> categories=new java.util.HashSet<>();for(int d=1;d<=7;d++)categories.add(GreetingSchedule.category(d));assertEquals(7,categories.size());}
 @Test public void calendarSeasonsWrapYearWithoutWeatherInference(){assertEquals(3,GreetingSchedule.seasonalTheme(12));assertEquals(3,GreetingSchedule.seasonalTheme(1));assertEquals(3,GreetingSchedule.seasonalTheme(2));assertEquals(0,GreetingSchedule.seasonalTheme(3));assertEquals(1,GreetingSchedule.seasonalTheme(6));assertEquals(2,GreetingSchedule.seasonalTheme(9));}
 @Test(expected=IllegalArgumentException.class)public void rejectsInvalidCalendarMonth(){GreetingSchedule.seasonalTheme(0);}
}
