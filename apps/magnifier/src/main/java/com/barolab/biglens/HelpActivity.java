package com.barolab.biglens;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.widget.*;
import com.barolab.daily.common.AdConsentBanner;
import com.barolab.daily.common.DailyUi;

/** Ads are opt-in on this help page only, never inside the live magnifier. */
public final class HelpActivity extends Activity {
    private AdConsentBanner ads;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setPadding(20,12,20,12); root.setBackgroundColor(Color.rgb(16,28,48)); DailyUi.applyInsets(this,root);
        getWindow().getDecorView().setSystemUiVisibility(getWindow().getDecorView().getSystemUiVisibility() & ~android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR & ~android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        Button back = new Button(this); back.setText("돋보기로 돌아가기"); back.setOnClickListener(v -> finish()); root.addView(back);
        ScrollView scroll = new ScrollView(this); LinearLayout content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); int padding = Math.round(16 * getResources().getDisplayMetrics().density); content.setPadding(padding,0,padding,padding); scroll.addView(content); root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        section(content,"작은 글씨, 이렇게 보세요","1. 카메라 권한을 허용하고 글씨와 거리를 조절하세요. 너무 가까우면 초점이 흐려질 수 있습니다. 읽을 곳을 누르거나 ‘초점 맞추기’로 다시 요청하세요. 지원하지 않는 기기는 거리를 조절해 주세요.\n2. 확대 막대나 지원 배율 버튼으로 조절하세요. 최대 배율은 기기마다 다르고, 확대할수록 화질이 낮아질 수 있어요.\n3. ‘화면 정지’로 화면을 잡아두면 카메라와 조명이 꺼집니다. 정지 후 두 손가락이나 확대 막대로 더 크게 보고 끌어서 이동하세요. ‘사진 원래 크기’로 전체를 봅니다. 사진 확대는 해상도를 높이지 않습니다. ‘실시간으로’로 돌아갑니다.");
        section(content,"조명과 고대비","후면 조명이 있는 기기에서만 조명을 켤 수 있어요. 배터리·발열·절전 상태에 따라 켜지지 않을 수 있습니다.\n‘사진 색상’에서 원본·고대비·흑백 반전을 선택합니다. 정지 사진에만 적용하고 선택한 모드로 사진 전체를 저장합니다. 색상·판독 결과를 보증하지 않습니다.");
        section(content,"정지 화면 저장","‘사진 전체 저장’을 누른 뒤 기기 파일 선택 화면에서 위치를 고릅니다. 취소하면 저장하지 않습니다. 카메라 원본 전체가 아니라 정지할 당시 장면 전체를 선택한 색상으로 PNG 저장합니다. 사진 확대 후 현재 보이는 부분만 잘라 저장하지 않으며, 긴 변은 최대 2048픽셀입니다.\n저장 위치가 클라우드 제공자라면 사용자가 고른 제공자의 처리 정책이 적용됩니다. 앱이 자동 업로드하지 않습니다.");
        section(content,"권한과 문제 해결","카메라 허용을 거절해도 앱을 종료하지 않습니다. 다시 허용하거나 ‘기기 권한 설정’에서 변경할 수 있어요. 카메라 연결에 실패하면 다른 카메라 앱을 닫고 다시 시도하세요. 후면 카메라가 없으면 실시간 돋보기를 사용할 수 없습니다.\n회전 때 정지 화면은 메모리에 유지하지만 앱이 종료되면 사라질 수 있으니 필요한 화면은 직접 저장하세요.");
        section(content,"개인정보와 광고","카메라 영상은 기기 안에서만 표시합니다. 얼굴 인식, 원격 분석, 자동 촬영·업로드를 하지 않습니다. 마이크·사진첩 권한을 요구하지 않습니다. 회원가입과 자체 분석·크래시 SDK는 없습니다.\n메인 화면 하단에는 조작 버튼과 여백을 둔 배너가 표시될 수 있습니다. Google 광고·동의 SDK의 동의 확인 후 비맞춤 배너를 요청하며 광고가 없어도 모든 기본 기능을 사용할 수 있습니다. 도움말 하단 배너는 아래 버튼으로 선택합니다. 확대·정지·저장 조작을 가로막는 전면 광고는 없습니다. 광고 SDK는 IP·대략적 위치·기기 식별자·상호작용·진단 정보를 처리할 수 있으며, 영상·저장 이미지는 광고 요청에 넣지 않습니다.");
        section(content,"안전한 사용","눈이나 태양, 강한 광원을 확대해 바라보지 마세요. 의학적 진단이나 중요한 의약품 식별을 보증하는 앱이 아닙니다. 작은 글씨를 보기 위한 보조 도구입니다.");
        Button policy = new Button(this); policy.setText("웹 개인정보처리방침"); policy.setOnClickListener(v -> {
            try { startActivity(new android.content.Intent(android.content.Intent.ACTION_VIEW,android.net.Uri.parse("https://barolab-daily-apps.pages.dev/magnifier/privacy"))); }
            catch (android.content.ActivityNotFoundException | SecurityException e) { android.widget.Toast.makeText(this,"브라우저에서 barolab-daily-apps.pages.dev/magnifier/privacy 를 확인해 주세요.",android.widget.Toast.LENGTH_LONG).show(); }
        }); content.addView(policy);
        Button optIn = new Button(this); optIn.setText("도움말 하단 광고 표시 선택"); content.addView(optIn);
        LinearLayout banner = new LinearLayout(this); banner.setOrientation(LinearLayout.VERTICAL); banner.setGravity(android.view.Gravity.CENTER); root.addView(banner);
        optIn.setOnClickListener(v -> { if (ads == null) { ads = new AdConsentBanner(this,banner,BuildConfig.AD_UNIT_ID); ads.start(); optIn.setText("광고 개인정보 선택"); } else ads.privacyOptions(); });
        setContentView(root);
    }
    private void section(LinearLayout parent,String title,String body) { TextView t = new TextView(this); t.setText(title); t.setTextSize(22); t.setTextColor(Color.rgb(255,203,96)); t.setPadding(0,22,0,8); parent.addView(t); TextView b = new TextView(this); b.setText(body); b.setTextSize(17); b.setTextColor(Color.rgb(244,247,251)); b.setLineSpacing(5,1.15f); parent.addView(b); }
    @Override protected void onResume() { super.onResume(); if (ads != null) ads.resume(); }
    @Override protected void onPause() { if (ads != null) ads.pause(); super.onPause(); }
    @Override protected void onDestroy() { if (ads != null) ads.destroy(); super.onDestroy(); }
}
