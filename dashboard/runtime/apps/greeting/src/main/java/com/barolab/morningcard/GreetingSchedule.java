package com.barolab.morningcard;
final class GreetingSchedule {
 private GreetingSchedule() { }
 static String category(int weekday){switch(weekday){case 1:return"encouragement";case 2:return"health_check_in";case 3:return"morning";case 4:return"gratitude";case 5:return"weather_free";case 6:return"seasonal";case 7:return"evening";default:throw new IllegalArgumentException("weekday");}}
 static int seasonalTheme(int month){if(month<1||month>12)throw new IllegalArgumentException("month");return month>=3&&month<=5?0:month>=6&&month<=8?1:month>=9&&month<=11?2:3;}
}
