package com.barolab.voicebasket;

import org.junit.Test;
import static org.junit.Assert.*;
import java.util.Arrays;

public class BasketParserTest {
    @Test public void explicitDelimitersOnly() {
        assertEquals(Arrays.asList("우유","달걀","두부"),BasketParser.split("우유, \r\n달걀\n\n두부，",false));
    }
    @Test public void conjunctionSplittingIsOptInAndNeverMorphological() {
        assertEquals(Arrays.asList("우유 그리고 달걀"),BasketParser.split("우유 그리고 달걀",false));
        assertEquals(Arrays.asList("우유","달걀","두부"),BasketParser.split("우유 그리고 달걀 및 두부",true));
        assertEquals(Arrays.asList("사과하고 배","하고기름"),BasketParser.split("사과하고 배, 하고기름",true));
    }
    @Test public void quantitiesAndDuplicatesRemainLiteral() {
        assertEquals(Arrays.asList("우유 2개","우유 2개","사과 또는 배"),BasketParser.split("우유 2개,우유 2개,사과 또는 배",false));
    }
    @Test public void whitespaceProducesNoPhantomItems() { assertTrue(BasketParser.split(" ,\n， ",true).isEmpty()); }
    @Test(expected=IllegalArgumentException.class) public void longItemIsRejectedWithoutTruncation() { BasketParser.split(new String(new char[121]).replace('\0','가'),false); }
    @Test(expected=IllegalArgumentException.class) public void over100ItemsIsRejected() { BasketParser.split(String.join(",",java.util.Collections.nCopies(101,"우유")),false); }
}
