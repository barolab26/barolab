package com.barolab.biglens;

/** Pure geometry. Center is a fraction of the unchanged source image. */
final class PhotoViewport {
    float zoom = 1, centerX = .5f, centerY = .5f;
    float scale(float width,float height,float imageWidth,float imageHeight) {
        return Math.min(width/imageWidth,height/imageHeight)*zoom;
    }
    static float bounded(float value,float min,float max) {
        return Float.isFinite(value) ? Math.max(min,Math.min(max,value)) : min;
    }
    void constrain(float width,float height,float iw,float ih) {
        zoom=bounded(zoom,1,6);
        if(width<=0||height<=0||iw<=0||ih<=0)return;
        float s=scale(width,height,iw,ih);
        centerX=iw*s<=width?.5f:bounded(centerX,width/(2*iw*s),1-width/(2*iw*s));
        centerY=ih*s<=height?.5f:bounded(centerY,height/(2*ih*s),1-height/(2*ih*s));
    }
    void reset(){zoom=1;centerX=centerY=.5f;}
}
