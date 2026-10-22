package com.barolab.harubible;

import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Only grants read access to explicitly shared PNG cards in the app's cache. */
public final class ShareImageProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    private File card(Uri uri) throws FileNotFoundException {
        if (uri.getPathSegments().size() != 1 || !uri.getLastPathSegment().matches("card-[0-9a-f-]{36}\\.png")) throw new FileNotFoundException("Unknown card");
        File file = new File(new File(getContext().getCacheDir(), "cards"), uri.getLastPathSegment());
        if (!file.isFile()) throw new FileNotFoundException("Card no longer available");
        return file;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read-only card");
        return ParcelFileDescriptor.open(card(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public String getType(Uri uri) { return "image/png"; }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) {
        try {
            File file = card(uri);
            MatrixCursor result = new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE});
            result.addRow(new Object[]{"말씀카드.png", file.length()}); return result;
        } catch (FileNotFoundException e) { return new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}); }
    }
    @Override public Uri insert(Uri u, ContentValues v) { throw new UnsupportedOperationException("Read only"); }
    @Override public int delete(Uri u, String s, String[] a) { throw new UnsupportedOperationException("Read only"); }
    @Override public int update(Uri u, ContentValues v, String s, String[] a) { throw new UnsupportedOperationException("Read only"); }
}
