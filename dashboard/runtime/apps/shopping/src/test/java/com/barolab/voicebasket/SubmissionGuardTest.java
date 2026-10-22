package com.barolab.voicebasket;
import org.junit.Test;
import static org.junit.Assert.*;
public class SubmissionGuardTest {
    @Test public void staleAndDoubleClicksCannotCommit() {SubmissionGuard g=new SubmissionGuard();assertFalse(g.claim("old",false));assertTrue(g.claim("current",true));assertFalse(g.claim("current",true));g.finish("current",true);assertFalse(g.claim("current",true));assertTrue(g.claim("new",true));}
    @Test public void persistenceFailureCanBeRetriedWithoutAcceptingAnotherInFlight() {SubmissionGuard g=new SubmissionGuard();assertTrue(g.claim("review",true));assertFalse(g.claim("other",true));g.finish("wrong",true);assertFalse(g.claim("review",true));g.finish("review",false);assertTrue(g.claim("review",true));}
    @Test public void emptyTokenCannotCommit(){assertFalse(new SubmissionGuard().claim("",true));}
}
