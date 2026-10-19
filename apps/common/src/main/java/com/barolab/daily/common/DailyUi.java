package com.barolab.daily.common;
import android.app.Activity;
import android.os.Build;
import android.view.*;
public final class DailyUi {
 private DailyUi() { }
 public static void applyInsets(Activity activity,View root) {
  int left=root.getPaddingLeft(),top=root.getPaddingTop(),right=root.getPaddingRight(),bottom=root.getPaddingBottom();
  if(Build.VERSION.SDK_INT>=30) activity.getWindow().setDecorFitsSystemWindows(false);
  int flags=View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
  if(Build.VERSION.SDK_INT>=27) flags|=View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
  activity.getWindow().getDecorView().setSystemUiVisibility(flags);
  root.setOnApplyWindowInsetsListener((view,insets)->{
   if(Build.VERSION.SDK_INT>=30) {android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());view.setPadding(left+bars.left,top+bars.top,right+bars.right,bottom+bars.bottom);}
   else view.setPadding(left+insets.getSystemWindowInsetLeft(),top+insets.getSystemWindowInsetTop(),right+insets.getSystemWindowInsetRight(),bottom+insets.getSystemWindowInsetBottom());
   return insets;
  });root.requestApplyInsets();
 }
}
