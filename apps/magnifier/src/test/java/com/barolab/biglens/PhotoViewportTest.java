package com.barolab.biglens;
import org.junit.Test;
import static org.junit.Assert.*;
public class PhotoViewportTest {
 @Test public void fitCentersLetterboxedAxis(){PhotoViewport p=new PhotoViewport();p.centerX=0;p.centerY=1;p.constrain(400,600,800,400);assertEquals(.5f,p.centerX,.001f);assertEquals(.5f,p.centerY,.001f);assertEquals(.5f,p.scale(400,600,800,400),.001f);}
 @Test public void panCannotRevealBlankEdges(){PhotoViewport p=new PhotoViewport();p.zoom=4;p.centerX=-1;p.centerY=2;p.constrain(400,400,800,800);assertEquals(.125f,p.centerX,.001f);assertEquals(.875f,p.centerY,.001f);}
 @Test public void rotationKeepsFeasibleNormalizedCenter(){PhotoViewport p=new PhotoViewport();p.zoom=4;p.centerX=.4f;p.centerY=.6f;p.constrain(400,800,800,800);p.constrain(800,400,800,800);assertEquals(.4f,p.centerX,.001f);assertEquals(.6f,p.centerY,.001f);}
 @Test public void invalidAndResetAreBounded(){PhotoViewport p=new PhotoViewport();p.zoom=Float.NaN;p.centerX=Float.POSITIVE_INFINITY;p.constrain(400,400,800,800);assertEquals(1,p.zoom,.001f);p.zoom=20;p.constrain(400,400,800,800);assertEquals(6,p.zoom,.001f);p.reset();assertEquals(.5f,p.centerX,.001f);assertEquals(1,p.zoom,.001f);}
}
