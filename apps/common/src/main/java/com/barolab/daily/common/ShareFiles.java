package com.barolab.daily.common;
import android.app.Activity;
import android.content.*;
import android.graphics.Bitmap;
import android.net.Uri;
import android.widget.Toast;
import java.io.*;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class ShareFiles {
    private static final ExecutorService IO=Executors.newSingleThreadExecutor();
    private ShareFiles() { }
    public static void shareText(Activity activity,String text) {
        try { activity.startActivity(Intent.createChooser(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,text),"공유할 앱 선택")); }
        catch(ActivityNotFoundException e) { Toast.makeText(activity,"공유할 앱을 찾지 못했어요.",Toast.LENGTH_LONG).show(); }
    }
    public static void sharePng(Activity activity,Bitmap bitmap,String title) {
        if(bitmap==null || bitmap.isRecycled()) return;
        final Bitmap snapshot=bitmap.copy(Bitmap.Config.ARGB_8888,false);
        IO.execute(()->{
            try {
                File directory=new File(activity.getCacheDir(),"shared");
                if(!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Cache unavailable");
                File[] old=directory.listFiles(); long cutoff=System.currentTimeMillis()-86400000L;
                if(old!=null) for(File file:old) if(file.getName().matches("share-[0-9a-f-]{36}\\.png") && file.lastModified()<cutoff) file.delete();
                File file=new File(directory,"share-"+UUID.randomUUID()+".png");
                try(OutputStream output=new FileOutputStream(file)) { if(!snapshot.compress(Bitmap.CompressFormat.PNG,100,output)) throw new IOException("PNG failed"); }
                Uri uri=new Uri.Builder().scheme("content").authority(activity.getPackageName()+".sharedfiles").appendPath(file.getName()).build();
                activity.runOnUiThread(()->{
                    if(activity.isFinishing() || activity.isDestroyed()) return;
                    Intent intent=new Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM,uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    intent.setClipData(ClipData.newUri(activity.getContentResolver(),title,uri));
                    try { activity.startActivity(Intent.createChooser(intent,"공유할 앱 선택")); }
                    catch(ActivityNotFoundException e) { Toast.makeText(activity,"공유할 앱을 찾지 못했어요.",Toast.LENGTH_LONG).show(); }
                });
            } catch(IOException|RuntimeException e) { activity.runOnUiThread(()->{if(!activity.isDestroyed()) Toast.makeText(activity,"이미지를 준비하지 못했어요. 다시 시도해 주세요.",Toast.LENGTH_LONG).show();}); }
            finally { snapshot.recycle(); }
        });
    }
    public static Intent createPngDocumentIntent(String name) {
        return new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("image/png").putExtra(Intent.EXTRA_TITLE,name);
    }
    /** Blocking I/O; call on a background executor. User chooses the destination. */
    public static void writePng(Context context,Uri uri,Bitmap bitmap) throws IOException {
        try(OutputStream output=context.getContentResolver().openOutputStream(uri,"wt")) {
            if(output==null || !bitmap.compress(Bitmap.CompressFormat.PNG,100,output)) throw new IOException("Unable to save PNG");
        }
    }
}
