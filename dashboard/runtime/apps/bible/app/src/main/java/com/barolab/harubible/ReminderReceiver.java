package com.barolab.harubible;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.Build;
import java.time.ZonedDateTime;

public final class ReminderReceiver extends BroadcastReceiver {
    static final String CHANNEL = "daily_reading";
    private static final String ACTION = "com.barolab.harubible.DAILY_REMINDER";
    static android.content.SharedPreferences prefs(Context c) { return c.getSharedPreferences("reading", Context.MODE_PRIVATE); }
    private static PendingIntent alarm(Context c) {
        return PendingIntent.getBroadcast(c, 410, new Intent(c, ReminderReceiver.class).setAction(ACTION), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
    public static boolean canNotify(Context c) {
        NotificationManager manager = c.getSystemService(NotificationManager.class);
        NotificationChannel channel = manager.getNotificationChannel(CHANNEL);
        return (Build.VERSION.SDK_INT < 33 || c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
                && manager.areNotificationsEnabled() && (channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE);
    }
    public static void schedule(Context c) {
        AlarmManager manager = c.getSystemService(AlarmManager.class);
        manager.cancel(alarm(c));
        if (!prefs(c).getBoolean("reminder_enabled", false) || !canNotify(c)) return;
        long next = DailyReading.nextReminder(ZonedDateTime.now(), prefs(c).getInt("hour", 8), prefs(c).getInt("minute", 0));
        manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next, alarm(c));
    }
    @Override public void onReceive(Context c, Intent intent) {
        if (ACTION.equals(intent.getAction()) && prefs(c).getBoolean("reminder_enabled", false) && canNotify(c)) {
            NotificationManager manager = c.getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, "하루 말씀 알림", NotificationManager.IMPORTANCE_DEFAULT));
            PendingIntent open = PendingIntent.getActivity(c, 411, new Intent(c, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification notification = new Notification.Builder(c, CHANNEL).setSmallIcon(com.barolab.harubible.R.drawable.ic_bible)
                    .setContentTitle("오늘의 성경말씀").setContentText("오늘 말씀을 읽을 시간이에요.")
                    .setContentIntent(open).setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).build();
            try { manager.notify(410, notification); } catch (SecurityException ignored) { /* Permission can change between checks. */ }
        }
        schedule(c);
    }
}
