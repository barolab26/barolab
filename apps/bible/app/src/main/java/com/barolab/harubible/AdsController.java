package com.barolab.harubible;

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.widget.LinearLayout;
import com.google.ads.mediation.admob.AdMobAdapter;
import com.google.android.gms.ads.*;
import com.google.android.ump.*;

/** No verse, prayer, favorite, content URL or religious segment enters an ad request. */
public final class AdsController {
    private final Activity activity;
    private final LinearLayout container;
    private final ConsentInformation consent;
    private AdView ad;
    private boolean initialized, disposed;
    private boolean active() { return !disposed && !activity.isFinishing() && !activity.isDestroyed(); }
    public AdsController(Activity activity, LinearLayout container) {
        this.activity = activity; this.container = container;
        consent = UserMessagingPlatform.getConsentInformation(activity);
    }
    public void start() {
        if (!active()) return;
        consent.requestConsentInfoUpdate(activity, new ConsentRequestParameters.Builder().build(), () -> {
            if (!active()) return;
            UserMessagingPlatform.loadAndShowConsentFormIfRequired(activity, error -> {
                    if (active() && error == null && consent.canRequestAds()) load();
                });
        }, error -> { if (active()) container.setVisibility(View.GONE); });
    }
    private void load() {
        if (initialized || !active() || !consent.canRequestAds()) return;
        initialized = true;
        MobileAds.initialize(activity, status -> activity.runOnUiThread(() -> {
            if (!active() || !consent.canRequestAds()) return;
            ad = new AdView(activity); ad.setAdSize(AdSize.BANNER); ad.setAdUnitId(BuildConfig.BANNER_AD_UNIT_ID);
            ad.setAdListener(new AdListener() {
                @Override public void onAdLoaded() { if (active()) container.setVisibility(View.VISIBLE); }
                @Override public void onAdFailedToLoad(LoadAdError error) { if (active()) container.setVisibility(View.GONE); }
            });
            container.addView(ad);
            Bundle extras = new Bundle(); extras.putString("npa", "1");
            ad.loadAd(new AdRequest.Builder().addNetworkExtrasBundle(AdMobAdapter.class, extras).build());
        }));
    }
    public void privacyOptions() {
        if (!active()) return;
        if (consent.getPrivacyOptionsRequirementStatus() == ConsentInformation.PrivacyOptionsRequirementStatus.REQUIRED)
            UserMessagingPlatform.showPrivacyOptionsForm(activity, error -> {
                if (!active()) return;
                if (ad != null) { ad.destroy(); ad = null; }
                container.removeAllViews(); container.setVisibility(View.GONE); initialized = false;
                if (error == null && consent.canRequestAds()) load();
            });
        else new android.app.AlertDialog.Builder(activity).setMessage("현재 별도로 표시할 광고 개인정보 선택 양식이 없습니다. 광고가 없어도 모든 말씀 기능을 사용할 수 있습니다.").setPositiveButton("확인", null).show();
    }
    public void pause() { if (ad != null) ad.pause(); }
    public void resume() { if (ad != null) ad.resume(); }
    public void destroy() { disposed = true; if (ad != null) { ad.destroy(); ad = null; } }
}
