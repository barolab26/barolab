package com.barolab.harubible;

import android.content.*;
import android.graphics.*;
import android.net.Uri;
import android.text.Layout;
import android.text.StaticLayout;
import android.text.TextPaint;
import java.io.File;
import java.io.FileOutputStream;
import java.util.UUID;

public final class VerseCard {
    static final int[] BACKGROUNDS={R.drawable.verse_bg_plum,R.drawable.verse_bg_lotus,R.drawable.verse_bg_pine_snow,R.drawable.verse_bg_sunrise,R.drawable.verse_bg_sea,R.drawable.verse_bg_tea};
    static final String[] BACKGROUND_NAMES={"매화","연꽃","눈 내린 소나무","해돋이","바다","찻잔"};
    static int backgroundIndex(int index){return Math.max(0,Math.min(BACKGROUNDS.length-1,index));}
    private VerseCard() { }
    public static Intent share(Context context, VerseRepository.Verse verse, String translation,int background) throws Exception {
        int width = 1080, padding = 96, contentWidth = width - padding * 2;
        TextPaint body = new TextPaint(Paint.ANTI_ALIAS_FLAG);
        body.setColor(Color.rgb(40, 55, 48)); body.setTextSize(52); body.setTypeface(Typeface.create("serif", Typeface.NORMAL));
        StaticLayout text = StaticLayout.Builder.obtain(verse.text, 0, verse.text.length(), body, contentWidth)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL).setLineSpacing(18, 1.1f).setIncludePad(true).build();
        TextPaint small = new TextPaint(Paint.ANTI_ALIAS_FLAG); small.setColor(Color.rgb(80, 106, 91)); small.setTextSize(30);
        StaticLayout source = StaticLayout.Builder.obtain(translation, 0, translation.length(), small, contentWidth).build();
        int height = Math.max(1350, text.getHeight() + source.getHeight() + 550);
        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap); canvas.drawColor(Color.rgb(249, 246, 238));
        Bitmap photo=BitmapFactory.decodeResource(context.getResources(),BACKGROUNDS[backgroundIndex(background)]);
        if(photo!=null){float scale=Math.max(width/(float)photo.getWidth(),height/(float)photo.getHeight()),w=photo.getWidth()*scale,h=photo.getHeight()*scale;canvas.drawBitmap(photo,null,new RectF((width-w)/2,(height-h)/2,(width+w)/2,(height+h)/2),new Paint(Paint.FILTER_BITMAP_FLAG));photo.recycle();}
        Paint panel=new Paint(Paint.ANTI_ALIAS_FLAG);panel.setColor(0xeffffdf7);canvas.drawRoundRect(64,210,width-64,height-80,24,24,panel);
        Paint accent = new Paint(Paint.ANTI_ALIAS_FLAG); accent.setColor(Color.rgb(48, 93, 80)); canvas.drawRoundRect(96, 96, 164, 108, 6, 6, accent);
        canvas.save(); canvas.translate(padding, 250); text.draw(canvas); canvas.restore();
        TextPaint reference = new TextPaint(small); reference.setTextSize(36);
        canvas.drawText(verse.reference, padding, 330 + text.getHeight(), reference);
        canvas.save(); canvas.translate(padding, height - 96 - source.getHeight()); source.draw(canvas); canvas.restore();
        canvas.drawRoundRect(width/2f-130,height-62,width/2f+130,height-12,12,12,panel);
        small.setTextSize(22);small.setTextAlign(Paint.Align.CENTER);canvas.drawText("오늘의 성경말씀",width/2f,height-30,small);
        File directory = new File(context.getCacheDir(), "cards"); if (!directory.isDirectory() && !directory.mkdirs()) throw new java.io.IOException("Card directory unavailable");
        File[] old = directory.listFiles(); if (old != null) for (File file : old) if (file.getName().matches("card-[0-9a-f-]{36}\\.png") && System.currentTimeMillis() - file.lastModified() > 24L * 60 * 60 * 1000) file.delete();
        File file = new File(directory, "card-" + UUID.randomUUID() + ".png");
        try (FileOutputStream output = new FileOutputStream(file)) { if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) throw new java.io.IOException("Card encoding failed"); }
        bitmap.recycle();
        Uri uri = Uri.parse("content://" + context.getPackageName() + ".cards/" + file.getName());
        Intent intent = new Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        intent.setClipData(ClipData.newRawUri("말씀 카드", uri));
        return intent;
    }
}
