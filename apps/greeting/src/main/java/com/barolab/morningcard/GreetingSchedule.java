package com.barolab.morningcard;
final class GreetingSchedule {
 static final int THEME_COUNT=18;
 static int theme(int value){return Math.max(0,Math.min(THEME_COUNT-1,value));}
 static int dailyTheme(java.time.LocalDate date){return 6+(int)Math.floorMod(date.toEpochDay(),12L);}
 static boolean changed(java.time.LocalDate previous,java.time.LocalDate now){return previous!=null&&!previous.equals(now);}
 static int[] backgroundOrder(){int[] result=new int[THEME_COUNT];for(int i=0;i<THEME_COUNT;i++)result[i]=i<12?i+6:i-12;return result;}
 private GreetingSchedule() { }
 static String category(int weekday){switch(weekday){case 1:return"encouragement";case 2:return"health_check_in";case 3:return"morning";case 4:return"gratitude";case 5:return"weather_free";case 6:return"seasonal";case 7:return"evening";default:throw new IllegalArgumentException("weekday");}}
 static int seasonalTheme(int month){if(month<1||month>12)throw new IllegalArgumentException("month");return month>=3&&month<=5?0:month>=6&&month<=8?1:month>=9&&month<=11?2:3;}
}
