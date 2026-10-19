package com.barolab.morningcard;
import org.junit.Test;
import static org.junit.Assert.*;
/** Regression: a legal-length paste with hundreds of newlines must not allocate a giant bitmap. */
public class GreetingTextBoundsTest {
 @Test public void rejectsNewlineBombWithinCharacterLimit(){assertFalse(CardState.renderable("\n".repeat(299)+"안"));}
 @Test public void keepsOrdinaryFullLengthText(){assertTrue(CardState.renderable("안".repeat(300)));assertFalse(CardState.renderable("안".repeat(301)));}
 @Test public void preservesAllowedParagraphsWithoutTruncation(){String text="안부\n".repeat(18);assertTrue(CardState.renderable(text));assertFalse(CardState.renderable(text+"\n"));}
}
