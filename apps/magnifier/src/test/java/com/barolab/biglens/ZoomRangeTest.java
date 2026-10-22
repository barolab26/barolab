package com.barolab.biglens;

import org.junit.Test;
import static org.junit.Assert.*;

public class ZoomRangeTest {
    @Test public void respectsActualHardwareLimits() { assertEquals(2f,ZoomRange.clamp(8,1,2),0.0001f); assertEquals(0.5f,ZoomRange.clamp(0.1f,0.5f,5),0.0001f); }
    @Test public void sliderReachesBothReportedEndpoints() { assertEquals(0.5f,ZoomRange.ratio(0,0.5f,7),0.0001f); assertEquals(7f,ZoomRange.ratio(1000,0.5f,7),0.0001f); }
    @Test public void noZoomHardwareIsValid() { assertEquals(1f,ZoomRange.ratio(900,1,1),0.0001f); assertEquals(0,ZoomRange.progress(1,1,1)); }
    @Test public void nonFiniteRequestsCannotEscapeRange() { assertEquals(1f,ZoomRange.clamp(Float.NaN,1,3),0.0001f); assertEquals(1f,ZoomRange.clamp(Float.POSITIVE_INFINITY,1,3),0.0001f); }
    @Test public void sliderRoundTripDoesNotDrift() { for (int p=0;p<=1000;p+=25) assertEquals(p,ZoomRange.progress(ZoomRange.ratio(p,0.5f,6),0.5f,6),1); }
}
