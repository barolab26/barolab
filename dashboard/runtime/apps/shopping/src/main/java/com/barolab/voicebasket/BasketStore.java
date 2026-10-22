package com.barolab.voicebasket;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.List;
import java.util.UUID;
import java.util.Set;

/** Local, atomic snapshots. Neither item content nor audio is sent to app servers. */
final class BasketStore {
    interface Change { void apply(JSONArray lists) throws Exception; }
    private final SharedPreferences prefs;
    private JSONArray lists;
    BasketStore(Context context) throws Exception {
        prefs = context.getSharedPreferences("baskets", Context.MODE_PRIVATE);
        lists = new JSONArray(prefs.getString("lists", "[]"));
    }
    JSONArray all() { return lists; }
    JSONObject find(String id) {
        for (int i=0;i<lists.length();i++) if (id.equals(lists.optJSONObject(i).optString("id"))) return lists.optJSONObject(i);
        return null;
    }
    static JSONObject find(JSONArray data, String id) throws Exception {
        for (int i=0;i<data.length();i++) if (id.equals(data.getJSONObject(i).getString("id"))) return data.getJSONObject(i);
        throw new IllegalArgumentException("목록을 찾을 수 없어요.");
    }
    void change(Change change) throws Exception {
        JSONArray next = new JSONArray(lists.toString()); change.apply(next);
        if (!prefs.edit().putString("undo", lists.toString()).putString("lists", next.toString()).commit()) throw new IllegalStateException("저장하지 못했어요. 다시 시도해 주세요.");
        lists = next;
    }
    boolean canUndo() { return prefs.contains("undo"); }
    void undo() throws Exception {
        if (!canUndo()) return;
        JSONArray previous = new JSONArray(prefs.getString("undo", "[]"));
        if (!prefs.edit().putString("lists", previous.toString()).remove("undo").commit()) throw new IllegalStateException("복원하지 못했어요.");
        lists = previous;
    }
    String create(String title, JSONObject source, boolean template) throws Exception {
        if (lists.length() >= 100) throw new IllegalArgumentException("목록은 100개까지 보관할 수 있어요.");
        String id=UUID.randomUUID().toString();
        JSONObject list=new JSONObject().put("id",id).put("title",valid(title,60)).put("archived",false).put("template",template);
        JSONArray items=new JSONArray();
        if (source != null) for (int i=0;i<source.getJSONArray("items").length();i++) {
            JSONObject item=new JSONObject(source.getJSONArray("items").getJSONObject(i).toString()); item.put("id",UUID.randomUUID().toString()).put("checked",false); items.put(item);
        }
        list.put("items",items);change(data->data.put(list));return id;
    }
    String createSelected(String title, JSONObject source, Set<String> selected, String request) throws Exception {
        if (source == null || selected.isEmpty()) throw new IllegalArgumentException("다시 쓸 항목을 하나 이상 골라 주세요.");
        for (int i=0;i<lists.length();i++) if (request.equals(lists.getJSONObject(i).optString("createRequest"))) return lists.getJSONObject(i).getString("id");
        if (lists.length() >= 100) throw new IllegalArgumentException("목록은 100개까지 보관할 수 있어요.");
        JSONArray items = new JSONArray();
        for (int i=0;i<source.getJSONArray("items").length();i++) {
            JSONObject original=source.getJSONArray("items").getJSONObject(i);
            if (!selected.contains(original.getString("id"))) continue;
            JSONObject item=new JSONObject(original.toString());
            item.put("id",UUID.randomUUID().toString()).put("checked",false);items.put(item);
        }
        if (items.length()!=selected.size()) throw new IllegalArgumentException("원본 목록이 바뀌었어요. 항목을 다시 확인해 주세요.");
        String id=UUID.randomUUID().toString();
        JSONObject list=new JSONObject().put("id",id).put("title",valid(title,60)).put("archived",false).put("template",false).put("items",items).put("createRequest",request);
        change(data->data.put(list));return id;
    }
    int[] previewAdd(String id,List<String> names,boolean merge) throws Exception {
        JSONArray items=find(lists,id).getJSONArray("items");Set<String> existing=new java.util.HashSet<>();
        for(int i=0;i<items.length();i++)existing.add(items.getJSONObject(i).getString("name"));
        int added=0,skipped=0;for(String name:names){if(merge&&!existing.add(name))skipped++;else added++;}
        if(items.length()+added>500)throw new IllegalArgumentException("한 목록은 500개까지 담을 수 있어요.");
        return new int[]{added,skipped};
    }
    void addOnce(String id,List<String> names,boolean merge,String request) throws Exception {
        if(request.equals(find(lists,id).optString("lastAddRequest")))return;
        previewAdd(id,names,merge);
        change(data->{JSONObject list=find(data,id);JSONArray items=list.getJSONArray("items");Set<String> existing=new java.util.HashSet<>();for(int i=0;i<items.length();i++)existing.add(items.getJSONObject(i).getString("name"));
            for(String name:names){if(merge&&!existing.add(name))continue;items.put(new JSONObject().put("id",UUID.randomUUID().toString()).put("name",valid(name,120)).put("quantity","1").put("checked",false));}
            list.put("lastAddRequest",request);
        });
    }
    void add(String id, List<String> names, boolean merge) throws Exception {
        change(data->{ JSONArray items=find(data,id).getJSONArray("items");
            if (items.length()+names.size()>500) throw new IllegalArgumentException("한 목록은 500개까지 담을 수 있어요.");
            for(String name:names) {
                boolean duplicate=false;
                if(merge) for(int i=0;i<items.length();i++) if(name.equals(items.getJSONObject(i).getString("name"))) { duplicate=true;break; }
                if(!duplicate) items.put(new JSONObject().put("id",UUID.randomUUID().toString()).put("name",valid(name,120)).put("quantity","1").put("checked",false));
            }
        });
    }
    static String valid(String value,int max) {
        String text=value==null?"":value.trim();
        if(text.isEmpty()||text.length()>max) throw new IllegalArgumentException("내용을 1~"+max+"자로 입력해 주세요.");return text;
    }
}
