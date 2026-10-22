package com.barolab.morningcard;
import org.json.*;
final class CardState {
 String text,name;boolean includeName,highContrast;int theme,font;
 CardState(String text,String name,boolean includeName,int theme,int font,boolean highContrast){this.text=text;this.name=name;this.includeName=includeName;this.theme=theme;this.font=font;this.highContrast=highContrast;}
 JSONObject json()throws JSONException{return new JSONObject().put("text",text).put("name",name).put("includeName",includeName).put("theme",theme).put("font",font).put("highContrast",highContrast);}
 static CardState from(JSONObject j){return new CardState(j.optString("text"),j.optString("name"),j.optBoolean("includeName"),Math.max(0,Math.min(8,j.optInt("theme"))),Math.max(52,Math.min(76,j.optInt("font",64))),j.optBoolean("highContrast",true));}
 static boolean renderable(String text){if(text==null||text.length()>300)return false;int breaks=0;for(int i=0;i<text.length();i++)if(text.charAt(i)=='\n'&&++breaks>18)return false;return true;}
 String plain(){return text+(includeName&&!name.trim().isEmpty()?"\n\n"+name.trim()+" 드림":"");}
}
