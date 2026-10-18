package com.barolab.biglens;

import android.Manifest;
import android.app.AlertDialog;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.*;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.*;
import android.widget.*;
import androidx.activity.ComponentActivity;
import androidx.camera.core.Camera;
import androidx.camera.core.*;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;
import com.barolab.daily.common.AdConsentBanner;
import com.barolab.daily.common.DailyUi;
import com.barolab.daily.common.ShareFiles;
import com.google.common.util.concurrent.ListenableFuture;
import java.util.Locale;
import java.util.concurrent.*;

/** Camera frames stay on device; the consent-gated banner is separate from camera controls. */
public final class MainActivity extends ComponentActivity {
    private static final int NAVY = Color.rgb(16,28,48), PANEL = Color.rgb(28,43,66), AMBER = Color.rgb(255,203,96), WHITE = Color.rgb(244,247,251);
    private static final int CAMERA_REQUEST = 40, SAVE_REQUEST = 41;
    private AdConsentBanner ads;
    private PreviewView preview;
    private FrozenImageView still;
    private LinearLayout permissionPanel, presets;
    private ScrollView permissionOverlay;
    private TextView status, zoomLabel;
    private Button freeze, light, contrast, save, focus, photoReset;
    private SeekBar zoom;
    private ProcessCameraProvider provider;
    private Camera camera;
    private Bitmap frozen;
    private boolean active, frozenMode, dragging, streamReady, savePending;
    private int session, focusGeneration, filterMode;
    private final Handler main = new Handler(Looper.getMainLooper());
    private float minZoom = 1, maxZoom = 1, chosenZoom = 1;
    private final ExecutorService files = Executors.newSingleThreadExecutor();
    private static final class Retained {
        final Bitmap frame; final int mode; final boolean pending; final float[] position;
        Retained(Bitmap frame, int mode, boolean pending, float[] position) { this.frame=frame;this.mode=mode;this.pending=pending;this.position=position; }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(NAVY); getWindow().setNavigationBarColor(NAVY);
        if (state != null) chosenZoom = state.getFloat("zoom", 1f);
        Object old = getLastCustomNonConfigurationInstance();
        if (old instanceof Retained) { Retained r = (Retained)old; frozen = r.frame; frozenMode = frozen != null; filterMode = r.mode; savePending = r.pending; }
        LinearLayout root = column(); root.setBackgroundColor(NAVY); DailyUi.applyInsets(this, root);
        getWindow().getDecorView().setSystemUiVisibility(getWindow().getDecorView().getSystemUiVisibility() & ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR & ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        LinearLayout heading = row(); heading.setPadding(dp(16), dp(6), dp(16), dp(6));
        TextView title = label(largeText()?"돋보기":"큰글씨 돋보기", 23, AMBER); title.setContentDescription("큰글씨 돋보기");title.setTypeface(null, Typeface.BOLD); heading.addView(title, new LinearLayout.LayoutParams(0,-2,1));
        heading.addView(button("사용 안내", v -> startActivity(new Intent(this, HelpActivity.class)))); root.addView(heading);
        boolean wide = getResources().getConfiguration().screenWidthDp > getResources().getConfiguration().screenHeightDp;
        LinearLayout area = new LinearLayout(this); area.setOrientation(wide ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL); root.addView(area, new LinearLayout.LayoutParams(-1,0,1));
        FrameLayout viewfinder = new FrameLayout(this); viewfinder.setBackgroundColor(Color.BLACK);
        preview = new PreviewView(this); preview.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE); preview.setScaleType(PreviewView.ScaleType.FILL_CENTER); viewfinder.addView(preview, new FrameLayout.LayoutParams(-1,-1));
        still = new FrozenImageView(this); still.setVisibility(View.GONE);  viewfinder.addView(still, new FrameLayout.LayoutParams(-1,-1));
        permissionPanel = column(); permissionPanel.setPadding(dp(24),dp(12),dp(24),dp(12)); permissionPanel.setGravity(Gravity.CENTER); permissionPanel.setBackgroundColor(NAVY);
        permissionOverlay = new ScrollView(this); permissionOverlay.setFillViewport(true); permissionOverlay.setBackgroundColor(NAVY); permissionOverlay.addView(permissionPanel); viewfinder.addView(permissionOverlay,new FrameLayout.LayoutParams(-1,-1));
        if (wide) area.addView(viewfinder, new LinearLayout.LayoutParams(0,-1,1)); else area.addView(viewfinder, new LinearLayout.LayoutParams(-1,0,1));
        ScrollView controlsScroll = new ScrollView(this); LinearLayout controls = column(); controls.setPadding(dp(16),dp(6),dp(16),dp(10)); controlsScroll.addView(controls);
        if (wide) area.addView(controlsScroll, new LinearLayout.LayoutParams(dp(Math.min(320,getResources().getConfiguration().screenWidthDp / 2)),-1)); else area.addView(controlsScroll, new LinearLayout.LayoutParams(-1,-2));
        status = label("카메라를 준비해 주세요", 14, WHITE); controls.addView(status);
        zoomLabel = label("확대 배율 · 기기 지원 범위 확인 중", 15, AMBER); controls.addView(zoomLabel);
        zoom = new SeekBar(this); zoom.setMax(1000); zoom.setContentDescription("카메라 확대 배율"); controls.addView(zoom, new LinearLayout.LayoutParams(-1,dp(56)));
        zoom.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar bar,int value,boolean user) { if (user) { if(frozenMode) still.setPhotoZoom(1+value/200f); else applyZoom(ZoomRange.ratio(value,minZoom,maxZoom)); } }
            @Override public void onStartTrackingTouch(SeekBar bar) { dragging = true; }
            @Override public void onStopTrackingTouch(SeekBar bar) { dragging = false; }
        });
        presets = row(); controls.addView(presets);
        LinearLayout primary = row(); freeze = button("화면 정지", v -> toggleFreeze()); freeze.setTextColor(NAVY); freeze.setBackground(shape(AMBER)); add(primary,freeze); light = button(largeText()?"확인":"조명 확인 중",v -> toggleLight()); add(primary,light); focus=button("초점 맞추기",v -> requestFocusAt(preview.getWidth()/2f,preview.getHeight()/2f));add(primary,focus);controls.addView(primary);
        LinearLayout secondary = row(); contrast = button("사진 색상",v -> chooseFilter()); add(secondary,contrast); save = button("사진 전체 저장",v -> saveFrame()); add(secondary,save); controls.addView(secondary);
        photoReset=button("사진 원래 크기",v -> still.reset());controls.addView(photoReset);
        still.setChanged(() -> { if(frozenMode) { zoomLabel.setText(String.format(Locale.KOREAN,"정지 사진 %.1f배 · 끌어서 이동",still.photoZoom()));if(!dragging)zoom.setProgress(Math.round((still.photoZoom()-1)*200)); } });
        if(old instanceof Retained)still.restore(((Retained)old).position);
        GestureDetector taps=new GestureDetector(this,new GestureDetector.SimpleOnGestureListener(){@Override public boolean onDown(MotionEvent e){return true;}@Override public boolean onSingleTapUp(MotionEvent e){preview.performClick();requestFocusAt(e.getX(),e.getY());return true;}});preview.setOnTouchListener((v,e)->taps.onTouchEvent(e));
        LinearLayout bannerHost = column(); bannerHost.setPadding(0, dp(10), 0, dp(4)); root.addView(bannerHost);
        ads = new AdConsentBanner(this, bannerHost, BuildConfig.AD_UNIT_ID); ads.start();
        setContentView(root); preview.getPreviewStreamState().observe(this, value -> { streamReady = value == PreviewView.StreamState.STREAMING; updateControls(); });
        if (frozenMode) showFrozen(); else permissionExplanation();
    }
    private boolean largeText(){return getResources().getConfiguration().fontScale>=1.5f;}
    private LinearLayout column() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); return l; }
    private LinearLayout row() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.HORIZONTAL); l.setGravity(Gravity.CENTER_VERTICAL); return l; }
    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private TextView label(String value,int size,int color) { TextView t = new TextView(this); t.setText(value); t.setTextSize(size); t.setTextColor(color); t.setPadding(0,dp(3),0,dp(5)); return t; }
    private GradientDrawable shape(int color) { GradientDrawable d = new GradientDrawable(); d.setColor(color); d.setCornerRadius(dp(12)); return d; }
    private Button button(String value,View.OnClickListener action) { Button b = new Button(this); b.setText(value); b.setAllCaps(false); b.setTextSize(15); b.setTextColor(WHITE); b.setMinHeight(dp(56)); b.setMinimumWidth(0); b.setPadding(dp(10),dp(8),dp(10),dp(8)); b.setStateListAnimator(null); b.setBackground(shape(PANEL)); b.setOnClickListener(action); return b; }
    private void add(LinearLayout row,Button b) { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0,-2,1); p.setMargins(dp(3),dp(4),dp(3),dp(4)); row.addView(b,p); }
    private boolean permitted() { return checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED; }
    private void permissionExplanation() {
        if (frozenMode) return;
        permissionOverlay.setVisibility(View.VISIBLE); permissionPanel.removeAllViews();
        permissionPanel.addView(label("작은 글씨를 화면으로 크게",24,AMBER));
        permissionPanel.addView(label("돋보기에는 카메라 권한이 필요합니다. 영상은 기기 안에서만 보여주며 자동 저장하거나 업로드하지 않습니다.",17,WHITE));
        permissionPanel.addView(button(permitted() ? "카메라 다시 연결" : "카메라 권한 허용 · 다시 시도",v -> { if (permitted()) startCamera(); else requestPermissions(new String[]{Manifest.permission.CAMERA},CAMERA_REQUEST); }));
        permissionPanel.addView(button("기기 권한 설정",v -> {
            try { startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName()))); }
            catch (ActivityNotFoundException | SecurityException e) { toast("설정에서 이 앱의 카메라 권한을 확인해 주세요."); }
        })); updateControls();
    }
    private void startCamera() {
        if (!active || frozenMode || !permitted()) return;
        int ticket = ++session; status.setText("카메라 연결 중…"); streamReady = false; permissionOverlay.setVisibility(View.GONE); updateControls();
        ListenableFuture<ProcessCameraProvider> future = ProcessCameraProvider.getInstance(this);
        future.addListener(() -> {
            if (!active || ticket != session || frozenMode || isDestroyed()) return;
            try {
                provider = future.get(); provider.unbindAll();
                if (!provider.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA)) { cameraError("사용할 수 있는 후면 카메라가 없습니다."); return; }
                Preview useCase = new Preview.Builder().build(); useCase.setSurfaceProvider(preview.getSurfaceProvider());
                camera = provider.bindToLifecycle(this,CameraSelector.DEFAULT_BACK_CAMERA,useCase);
                camera.getCameraInfo().getZoomState().observe(this,z -> {
                    if (camera == null || ticket != session || frozenMode) return;
                    minZoom = z.getMinZoomRatio(); maxZoom = z.getMaxZoomRatio();
                    zoomLabel.setText(String.format(Locale.KOREAN,"%.1f배 · 지원 %.1f~%.1f배",z.getZoomRatio(),minZoom,maxZoom));
                    if (!dragging) zoom.setProgress(ZoomRange.progress(z.getZoomRatio(),minZoom,maxZoom));
                    rebuildPresets();
                });
                camera.getCameraInfo().getTorchState().observe(this,t -> { if (ticket == session && camera != null) updateLightLabel(t == TorchState.ON,camera.getCameraInfo().hasFlashUnit()); });
                camera.getCameraInfo().getCameraState().observe(this,c -> { if (ticket == session && c.getError() != null) cameraError("카메라가 잠시 중단됐습니다. 다른 카메라 앱을 닫거나 절전·발열 상태를 확인하고 다시 연결해 주세요."); });
                ZoomState z = camera.getCameraInfo().getZoomState().getValue();
                if (z != null) { minZoom = z.getMinZoomRatio(); maxZoom = z.getMaxZoomRatio(); applyZoom(chosenZoom); }
                status.setText("실시간 · 읽을 곳을 눌러 초점 맞추기"); updateControls();
            } catch (Exception e) { cameraError("카메라에 연결하지 못했습니다. 권한·카메라 사용 중인 앱·절전 상태를 확인해 주세요."); }
        },ContextCompat.getMainExecutor(this));
    }
    private void rebuildPresets() {
        presets.removeAllViews();
        for (float value : new float[]{1,2,4,8}) if (value >= minZoom && value <= maxZoom) add(presets,button(String.format(Locale.KOREAN,"%.0f배",value),v -> applyZoom(value)));
    }
    private void applyZoom(float value) {
        if (camera == null || frozenMode || !active) return;
        chosenZoom = ZoomRange.clamp(value,minZoom,maxZoom); int ticket = session;
        ListenableFuture<Void> task = camera.getCameraControl().setZoomRatio(chosenZoom);
        task.addListener(() -> { try { task.get(); } catch (Exception e) { if (ticket == session && active) status.setText("배율을 적용하지 못했습니다. 지원 범위 안에서 다시 조절해 주세요."); } },ContextCompat.getMainExecutor(this));
    }
    private void toggleLight() {
        if (camera == null || frozenMode || !camera.getCameraInfo().hasFlashUnit()) return;
        Integer state = camera.getCameraInfo().getTorchState().getValue(); int ticket = session;
        ListenableFuture<Void> task = camera.getCameraControl().enableTorch(state == null || state != TorchState.ON);
        task.addListener(() -> { try { task.get(); } catch (Exception e) { if (ticket == session && active) status.setText("조명을 켜지 못했습니다. 배터리·발열 상태를 확인해 주세요."); } },ContextCompat.getMainExecutor(this));
    }
    private void toggleFreeze() {
        if (frozenMode) { frozenMode = false; filterMode = 0; still.setFrame(null); still.reset(); still.setVisibility(View.GONE); frozen = null; preview.setVisibility(View.VISIBLE); startCamera(); return; }
        if (!streamReady || camera == null) return;
        try {
            Bitmap frame = preview.getBitmap(); if (frame == null) { toast("영상이 준비된 뒤 다시 정지해 주세요."); return; }
            int edge = Math.max(frame.getWidth(),frame.getHeight());
            if (edge > 2048) { float factor = 2048f / edge; frame = Bitmap.createScaledBitmap(frame,Math.max(1,Math.round(frame.getWidth()*factor)),Math.max(1,Math.round(frame.getHeight()*factor)),true); }
            frozen = frame; still.reset(); frozenMode = true; closeCamera(); showFrozen();
        } catch (OutOfMemoryError e) { toast("메모리가 부족해 화면을 정지하지 못했어요. 다른 앱을 닫고 다시 시도해 주세요."); }
    }
    private void showFrozen() { permissionOverlay.setVisibility(View.GONE); preview.setVisibility(View.GONE); still.setVisibility(View.VISIBLE); still.setFrame(frozen); status.setText("정지 사진 · 저장은 선택 색상의 사진 전체"); applyContrast(); updateControls(); }
    private ColorMatrixColorFilter contrastFilter() { ColorMatrix gray = new ColorMatrix(); gray.setSaturation(0); ColorMatrix boost = new ColorMatrix(new float[]{1.8f,0,0,0,-70,0,1.8f,0,0,-70,0,0,1.8f,0,-70,0,0,0,1,0}); gray.postConcat(boost); return new ColorMatrixColorFilter(gray); }
    private ColorMatrixColorFilter selectedFilter() {
        if(filterMode==1)return contrastFilter();
        if(filterMode==2){ColorMatrix gray=new ColorMatrix();gray.setSaturation(0);gray.postConcat(new ColorMatrix(new float[]{-1,0,0,0,255,0,-1,0,0,255,0,0,-1,0,255,0,0,0,1,0}));return new ColorMatrixColorFilter(gray);}
        return null;
    }
    private String filterName(){return new String[]{"원본","고대비","흑백 반전"}[filterMode];}
    private void applyContrast() { still.setFilter(selectedFilter()); contrast.setText(largeText()?filterName():"사진 색상 · "+filterName());contrast.setContentDescription("정지 사진 색상 바꾸기, 현재 "+filterName()); }
    private void chooseFilter(){if(!frozenMode)return;new AlertDialog.Builder(this).setTitle("정지 사진 색상").setSingleChoiceItems(new String[]{"원본","고대비","흑백 반전"},filterMode,(d,w)->{filterMode=w;applyContrast();d.dismiss();}).setNegativeButton("닫기",null).show();}
    private void requestFocusAt(float x,float y) {
        if(!active||frozenMode||camera==null||!streamReady)return;
        int ticket=session, generation=++focusGeneration;
        try {
            FocusMeteringAction action=new FocusMeteringAction.Builder(preview.getMeteringPointFactory().createPoint(x,y),FocusMeteringAction.FLAG_AF|FocusMeteringAction.FLAG_AE).setAutoCancelDuration(4,TimeUnit.SECONDS).build();
            if(!camera.getCameraInfo().isFocusMeteringSupported(action)){status.setText("이 카메라는 누른 위치 초점을 지원하지 않아요. 거리를 조금 바꿔 주세요.");return;}
            status.setText("초점 맞추는 중…");
            ListenableFuture<FocusMeteringResult> task=camera.getCameraControl().startFocusAndMetering(action);
            main.postDelayed(()->{if(active&&!frozenMode&&ticket==session&&generation==focusGeneration){++focusGeneration;status.setText("초점을 확인하지 못했어요. 거리를 바꾸고 다시 눌러 주세요.");}},6000);
            task.addListener(()->{if(!active||frozenMode||ticket!=session||generation!=focusGeneration)return;++focusGeneration;try{status.setText(task.get().isFocusSuccessful()?"초점 완료 · 화면 정지로 편하게 읽으세요":"초점 완료를 확인하지 못했어요. 거리를 바꿔 다시 눌러 주세요.");}catch(Exception e){status.setText("초점을 적용하지 못했어요. 다시 눌러 주세요.");}},ContextCompat.getMainExecutor(this));
        }catch(RuntimeException e){status.setText("초점을 요청하지 못했어요. 카메라 상태를 확인해 주세요.");}
    }
    private void updateControls() {
        if (freeze == null) return;
        boolean live = active && camera != null && !frozenMode;
        freeze.setEnabled(frozenMode || (live && streamReady)); freeze.setText(largeText()?(frozenMode?"재개":"정지"):frozenMode ? "실시간으로" : "화면 정지");freeze.setContentDescription(frozenMode?"정지 사진 닫고 실시간 카메라 다시 보기":"실시간 화면을 사진으로 정지하기");
        zoom.setEnabled(frozenMode || (live && maxZoom > minZoom)); zoom.setContentDescription(frozenMode?"정지 사진 확대 배율":"카메라 확대 배율"); photoReset.setVisibility(frozenMode?View.VISIBLE:View.GONE);focus.setEnabled(live&&streamReady);focus.setText(largeText()?"초점":"초점 맞추기");focus.setContentDescription("실시간 화면 중앙에 초점 맞추기. 화면의 읽을 곳을 직접 눌러도 됩니다."); presets.setVisibility(frozenMode ? View.GONE : View.VISIBLE);
        for (int i=0;i<presets.getChildCount();i++) presets.getChildAt(i).setEnabled(live);
        light.setEnabled(live && camera.getCameraInfo().hasFlashUnit());
        if (frozenMode) {light.setText(largeText()?"꺼짐":"조명 꺼짐");light.setContentDescription("정지 사진을 보는 동안 조명 꺼짐");}
        contrast.setEnabled(frozenMode); if(!frozenMode)contrast.setText("사진 색상");save.setText(largeText()?"저장":"사진 전체 저장");save.setContentDescription("선택한 색상으로 정지 사진 전체 저장, 현재 확대 부분만 자르지 않습니다.");save.setEnabled(frozenMode && !savePending);
    }
    private void updateLightLabel(boolean on,boolean supported){light.setText(largeText()?(supported?(on?"켜짐":"꺼짐"):"없음"):supported?(on?"조명 끄기":"조명 켜기"):"조명 미지원");light.setContentDescription(!supported?"이 카메라는 조명을 지원하지 않아요":on?"조명 켜짐, 누르면 끄기":"조명 꺼짐, 누르면 켜기");}
    private void cameraError(String message) { closeCamera(); permissionExplanation(); status.setText(message); }
    private void closeCamera() { ++session; ++focusGeneration; main.removeCallbacksAndMessages(null); streamReady = false; if (camera != null) { camera.getCameraInfo().getZoomState().removeObservers(this); camera.getCameraInfo().getTorchState().removeObservers(this); camera.getCameraInfo().getCameraState().removeObservers(this); camera.getCameraControl().cancelFocusAndMetering(); camera.getCameraControl().enableTorch(false); } if (provider != null) provider.unbindAll(); camera = null; updateControls(); }
    private void saveFrame() {
        if (frozen == null || savePending) return;
        try { savePending = true; updateControls(); startActivityForResult(ShareFiles.createPngDocumentIntent("돋보기-"+System.currentTimeMillis()+".png"),SAVE_REQUEST); }
        catch (ActivityNotFoundException | SecurityException e) { savePending = false; updateControls(); toast("파일 저장 화면을 열지 못했어요. 기기 파일 앱을 확인해 주세요."); }
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data); if (request != SAVE_REQUEST) return;
        savePending = false; updateControls(); if (result != RESULT_OK || data == null || data.getData() == null) return;
        if (frozen == null) { toast("정지 화면이 유지되지 않았어요. 다시 정지한 뒤 저장해 주세요."); return; }
        try {
            Bitmap copy = Bitmap.createBitmap(frozen.getWidth(),frozen.getHeight(),Bitmap.Config.ARGB_8888); Paint paint = new Paint(); paint.setColorFilter(selectedFilter()); new Canvas(copy).drawBitmap(frozen,0,0,paint); Uri destination = data.getData();
            files.execute(() -> { boolean ok; try { ShareFiles.writePng(getApplicationContext(),destination,copy); ok=true; } catch (Exception e) { ok=false; } finally { copy.recycle(); } final boolean saved=ok; runOnUiThread(() -> { if (!isDestroyed()) toast(saved ? "선택한 색상으로 사진 전체를 저장했어요." : "저장하지 못했어요. 저장 위치의 권한과 여유 공간을 확인해 주세요."); }); });
        } catch (OutOfMemoryError e) { toast("저장할 메모리가 부족해요. 다른 앱을 닫고 다시 시도해 주세요."); }
    }
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results) { super.onRequestPermissionsResult(request,permissions,results); if (request==CAMERA_REQUEST) { if (permitted()) startCamera(); else { permissionExplanation(); status.setText("카메라 권한이 없어 확대 화면을 열지 않았습니다. 다시 허용하거나 기기 권한 설정을 확인해 주세요."); } } }
    @Override protected void onResume() { super.onResume(); if (ads != null) ads.resume(); active=true; if (frozenMode) showFrozen(); else if (permitted()) startCamera(); else permissionExplanation(); }
    @Override protected void onPause() { if (ads != null) ads.pause(); active=false; closeCamera(); super.onPause(); }
    @Override protected void onDestroy() { if (ads != null) ads.destroy(); closeCamera(); files.shutdown(); super.onDestroy(); }
    @Override protected void onSaveInstanceState(Bundle out) { out.putFloat("zoom",chosenZoom); super.onSaveInstanceState(out); }
    @Override public Object onRetainCustomNonConfigurationInstance() { return new Retained(frozen,filterMode,savePending,still.position()); }
    private void toast(String message) { Toast.makeText(this,message,Toast.LENGTH_LONG).show(); }
}
