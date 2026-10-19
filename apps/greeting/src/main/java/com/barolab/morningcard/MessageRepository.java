package com.barolab.morningcard;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.*;
final class MessageRepository {
 static final class Message {final String id,category,text;Message(String id,String category,String text){this.id=id;this.category=category;this.text=text;} }
 final List<Message> messages=new ArrayList<>();
 MessageRepository(Context c) throws Exception {String raw;try(InputStream in=c.getAssets().open("messages.json");ByteArrayOutputStream bytes=new ByteArrayOutputStream()){byte[] b=new byte[4096];int n;while((n=in.read(b))!=-1)bytes.write(b,0,n);raw=bytes.toString(StandardCharsets.UTF_8.name());} JSONArray a=new JSONObject(raw).getJSONArray("messages");for(int i=0;i<a.length();i++){JSONObject j=a.getJSONObject(i);messages.add(new Message(j.getString("id"),j.getString("category"),j.getString("text")));}if(messages.size()<60)throw new IOException("Reviewed collection incomplete");}
 Message daily(LocalDate day){String category=GreetingSchedule.category(day.getDayOfWeek().getValue());List<Message> choices=new ArrayList<>();for(Message m:messages)if(m.category.equals(category))choices.add(m);return choices.get(Math.floorMod(day.toEpochDay(),choices.size()));}
 static String categoryLabel(String c){switch(c){case"morning":return"아침 인사";case"gratitude":return"감사";case"health_check_in":return"건강 안부";case"encouragement":return"응원";case"seasonal":return"계절 인사";case"evening":return"저녁 인사";default:return"편안한 안부";}}
}
