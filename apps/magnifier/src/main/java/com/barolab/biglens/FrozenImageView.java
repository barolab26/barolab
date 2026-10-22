package com.barolab.biglens;

import android.content.Context;
import android.graphics.*;
import android.view.*;

/** Canvas transforms only: gestures never resample or mutate the source bitmap. */
final class FrozenImageView extends View {
    private Bitmap image;
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG|Paint.FILTER_BITMAP_FLAG);
    private final PhotoViewport viewport=new PhotoViewport();
    private final ScaleGestureDetector pinch;
    private final GestureDetector drag;
    private Runnable changed;
    FrozenImageView(Context context){
        super(context);setFocusable(true);setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);setContentDescription("정지 사진. 두 손가락으로 확대하고 끌어서 이동하세요. 아래 확대 조절과 원래 크기 버튼, 접근성 스크롤 동작으로도 조작할 수 있습니다.");
        pinch=new ScaleGestureDetector(context,new ScaleGestureDetector.SimpleOnScaleGestureListener(){
            @Override public boolean onScale(ScaleGestureDetector d){zoomAt(viewport.zoom*d.getScaleFactor(),d.getFocusX(),d.getFocusY());return true;}
        });
        drag=new GestureDetector(context,new GestureDetector.SimpleOnGestureListener(){
            @Override public boolean onDown(android.view.MotionEvent e){return true;}
            @Override public boolean onSingleTapUp(android.view.MotionEvent e){performClick();return true;}
            @Override public boolean onScroll(android.view.MotionEvent a,android.view.MotionEvent b,float dx,float dy){
                if(image!=null&&!pinch.isInProgress()&&b.getPointerCount()==1){float s=scale();if(s>0){viewport.centerX+=dx/(s*image.getWidth());viewport.centerY+=dy/(s*image.getHeight());redraw();}}return true;
            }
        });
    }
    void setFrame(Bitmap bitmap){image=bitmap;redraw();}
    void setFilter(ColorFilter filter){paint.setColorFilter(filter);invalidate();}
    void setChanged(Runnable listener){changed=listener;}
    float[] position(){return new float[]{viewport.zoom,viewport.centerX,viewport.centerY};}
    void restore(float[] state){if(state!=null&&state.length==3){viewport.zoom=state[0];viewport.centerX=state[1];viewport.centerY=state[2];}redraw();}
    float photoZoom(){return viewport.zoom;}
    void reset(){viewport.reset();redraw();}
    void setPhotoZoom(float value){zoomAt(value,getWidth()/2f,getHeight()/2f);}
    private float scale(){return image==null||getWidth()==0||getHeight()==0?0:viewport.scale(getWidth(),getHeight(),image.getWidth(),image.getHeight());}
    private void zoomAt(float value,float x,float y){
        float before=scale();float target=PhotoViewport.bounded(value,1,6);
        if(image!=null&&before>0){float after=before*target/viewport.zoom;
            viewport.centerX+=(x-getWidth()/2f)*(1/before-1/after)/image.getWidth();
            viewport.centerY+=(y-getHeight()/2f)*(1/before-1/after)/image.getHeight();
        }viewport.zoom=target;redraw();
    }
    private void redraw(){if(image!=null)viewport.constrain(getWidth(),getHeight(),image.getWidth(),image.getHeight());invalidate();if(changed!=null)changed.run();}
    @Override protected void onSizeChanged(int w,int h,int oldw,int oldh){super.onSizeChanged(w,h,oldw,oldh);redraw();}
    @Override protected void onDraw(Canvas canvas){super.onDraw(canvas);if(image==null||image.isRecycled())return;float s=scale();canvas.save();canvas.translate(getWidth()/2f-viewport.centerX*image.getWidth()*s,getHeight()/2f-viewport.centerY*image.getHeight()*s);canvas.scale(s,s);canvas.drawBitmap(image,0,0,paint);canvas.restore();}
    @Override public boolean onTouchEvent(MotionEvent e){if(image==null)return false;pinch.onTouchEvent(e);drag.onTouchEvent(e);return true;}
    @Override public void onInitializeAccessibilityNodeInfo(android.view.accessibility.AccessibilityNodeInfo info){
        super.onInitializeAccessibilityNodeInfo(info);info.setClassName("android.widget.ImageView");info.setScrollable(viewport.zoom>1);
        if(viewport.zoom>1){info.addAction(android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_LEFT);info.addAction(android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_RIGHT);info.addAction(android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_UP);info.addAction(android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN);info.addAction(android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_FORWARD);info.addAction(android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_BACKWARD);}
    }
    @Override public boolean performAccessibilityAction(int action,android.os.Bundle args){
        if(image!=null&&viewport.zoom>1){float s=scale(),dx=0,dy=0;
            if(action==android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_LEFT.getId())dx=-getWidth()*.6f;
            else if(action==android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_RIGHT.getId())dx=getWidth()*.6f;
            else if(action==android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_UP.getId()||action==android.view.accessibility.AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)dy=-getHeight()*.6f;
            else if(action==android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction.ACTION_SCROLL_DOWN.getId()||action==android.view.accessibility.AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)dy=getHeight()*.6f;
            else return super.performAccessibilityAction(action,args);
            if(s>0){viewport.centerX+=dx/(s*image.getWidth());viewport.centerY+=dy/(s*image.getHeight());redraw();sendAccessibilityEvent(android.view.accessibility.AccessibilityEvent.TYPE_VIEW_SCROLLED);return true;}
        }return super.performAccessibilityAction(action,args);
    }
    @Override public boolean performClick(){super.performClick();return true;}
}
