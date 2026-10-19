package com.barolab.voicebasket;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.provider.Settings;
import android.view.*;
import android.widget.*;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.*;
import com.barolab.daily.common.AdConsentBanner;
import com.barolab.daily.common.DailyUi;
import com.barolab.daily.common.ShareFiles;

public final class MainActivity extends ComponentActivity {
    private static final int TEAL=0xff126e70, INK=0xff203c3c, MUTED=0xff536c6a, CORAL=0xffa94935;
    private LinearLayout root,content,banner,tools,dock,itemRows,previewPanel,advancedPanel,reuseRows;
    private TextView listCount,dockMessage,reuseCount;
    private Button commitButton,undoButton,reuseCommit;
    private EditText reuseName;
    private final Map<String,View> rowViews=new LinkedHashMap<>();
    private final Map<String,CheckBox> rowChecks=new LinkedHashMap<>();
    private final SubmissionGuard submissions=new SubmissionGuard();
    private final Set<String> reuseSelection=new LinkedHashSet<>();
    private String reviewToken="",reuseId="",reuseTitle="",reuseToken="";
    private boolean previewSplit,previewMerge,advancedOpen;
    private int viewEpoch;
    private ScrollView scroll;
    private BasketStore store;
    private VoiceInput voice;
    private AdConsentBanner ads;
    private String currentId="", mode="active", draft="", previewSource="";
    private boolean composer, splitConjunctions, mergeDuplicates, voiceActive, stopped, permissionPending;
    private EditText draftInput;
    private TextView voiceStatus;
    private Button voiceButton;
    private List<String> candidates=new ArrayList<>();
    private int textSize=22;
    private interface Task { void run() throws Exception; }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getOnBackPressedDispatcher().addCallback(this,new OnBackPressedCallback(true){@Override public void handleOnBackPressed(){if(!currentId.isEmpty())navigateBack();else{setEnabled(false);getOnBackPressedDispatcher().onBackPressed();}}});
        textSize=getPreferences(0).getInt("textSize",22);
        if(state!=null){ currentId=state.getString("currentId","");mode=state.getString("mode","active");draft=state.getString("draft","");composer=state.getBoolean("composer");splitConjunctions=state.getBoolean("split");mergeDuplicates=state.getBoolean("merge");previewSource=state.getString("previewSource","");ArrayList<String> saved=state.getStringArrayList("candidates");if(saved!=null)candidates=saved;reviewToken=state.getString("reviewToken","");previewSplit=state.getBoolean("previewSplit");previewMerge=state.getBoolean("previewMerge");advancedOpen=state.getBoolean("advancedOpen");reuseId=state.getString("reuseId","");reuseTitle=state.getString("reuseTitle","");reuseToken=state.getString("reuseToken","");ArrayList<String> selected=state.getStringArrayList("reuseSelection");if(selected!=null)reuseSelection.addAll(selected); }
        root=new LinearLayout(this);root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(0xfff7faf8);DailyUi.applyInsets(this,root);
        tools=new LinearLayout(this);tools.setOrientation(LinearLayout.VERTICAL);tools.setPadding(dp(18),dp(8),dp(18),dp(4));root.addView(tools);
        scroll=new ScrollView(this);scroll.setId(R.id.basket_scroll);scroll.setFillViewport(true);content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);content.setPadding(dp(18),dp(8),dp(18),dp(24));scroll.addView(content);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        dock=new LinearLayout(this);dock.setOrientation(LinearLayout.VERTICAL);dock.setPadding(dp(16),dp(7),dp(16),dp(8));dock.setBackground(shape(0xffeff5f0));root.addView(dock);
        root.setOnApplyWindowInsetsListener((view,insets)->{if(Build.VERSION.SDK_INT>=30){android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());android.graphics.Insets ime=insets.getInsets(WindowInsets.Type.ime());view.setPadding(bars.left,bars.top,bars.right,Math.max(bars.bottom,ime.bottom));}else view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
        banner=new LinearLayout(this);banner.setGravity(Gravity.CENTER);banner.setOrientation(LinearLayout.VERTICAL);root.addView(banner);setContentView(root);
        voice=new VoiceInput(this,new VoiceInput.Listener(){public void state(String message,boolean active){voiceActive=active;if(voiceStatus!=null)voiceStatus.setText(message);if(voiceButton!=null)voiceButton.setEnabled(!active);updateCommitDock();}public void result(String text){voiceActive=false;draft=draft.isEmpty()?text:draft+"\n"+text;invalidateReview();if(draftInput!=null){draftInput.setText(draft);draftInput.setSelection(draftInput.length());}if(voiceStatus!=null)voiceStatus.setText("아직 추가되지 않았어요. 고친 뒤 미리보기로 확인해 주세요.");if(voiceButton!=null)voiceButton.setEnabled(true);updateCommitDock();}});
        try{store=new BasketStore(this);}catch(Exception error){content.addView(text("목록 파일을 읽지 못했어요. 앱 데이터를 지우지 말고 지원 문의를 해 주세요.",22,INK));return;}
        LinearLayout adSlot=new LinearLayout(this);adSlot.setOrientation(LinearLayout.VERTICAL);banner.addView(adSlot);
        ads=new AdConsentBanner(this,adSlot,BuildConfig.AD_UNIT_ID);ads.start();render();
    }
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private TextView text(String value,int size,int color){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(color);v.setLineSpacing(dp(3),1.08f);v.setPadding(0,dp(5),0,dp(9));return v;}
    private GradientDrawable shape(int color){GradientDrawable s=new GradientDrawable();s.setColor(color);s.setCornerRadius(dp(15));s.setStroke(dp(1),0xffd4e3df);return s;}
    private Button button(String value,View.OnClickListener action){Button b=new Button(this);b.setText(value);b.setTextSize(17);b.setAllCaps(false);b.setTextColor(TEAL);b.setMinHeight(dp(52));b.setMinimumWidth(0);b.setPadding(dp(12),dp(10),dp(12),dp(10));b.setBackground(shape(Color.WHITE));b.setOnClickListener(action);return b;}
    private Button primary(String value,View.OnClickListener action){Button b=button(value,action);b.setTextColor(Color.WHITE);b.setTypeface(Typeface.DEFAULT,Typeface.BOLD);b.setBackground(shape(TEAL));return b;}
    private void full(LinearLayout parent,View view){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,dp(4),0,dp(5));parent.addView(view,p);}
    private void rowButton(LinearLayout row,View b){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(0,-2,1);p.setMargins(dp(2),dp(3),dp(2),dp(3));row.addView(b,p);}
    private LinearLayout panel(){LinearLayout p=new LinearLayout(this);p.setOrientation(LinearLayout.VERTICAL);p.setPadding(dp(15),dp(12),dp(15),dp(12));p.setBackground(shape(Color.WHITE));full(content,p);return p;}
    private EditText input(String hint,String value,boolean multiline){EditText e=new EditText(this);e.setTextSize(20);e.setTextColor(INK);e.setHint(hint);e.setText(value);e.setSingleLine(!multiline);e.setContentDescription(hint);if(multiline){e.setMinLines(3);e.setGravity(Gravity.TOP);e.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);}return e;}
    private void act(Task task){try{task.run();}catch(Exception e){new AlertDialog.Builder(this).setTitle("확인해 주세요").setMessage(e.getMessage()==null?"작업하지 못했어요. 기존 목록은 유지됩니다.":e.getMessage()).setPositiveButton("확인",null).show();}}
    private void toast(String s){Toast.makeText(this,s,Toast.LENGTH_LONG).show();}
    private JSONObject current(){return store==null?null:store.find(currentId);}
    private String currentMeta(){JSONObject list=current();return list==null?"":list.optString("title")+"|"+list.optBoolean("archived")+"|"+list.optBoolean("template");}
    private void captureDraft(){if(draftInput!=null)draft=draftInput.getText().toString();}
    private void stopVoice(){if(voice!=null)voice.cancel();voiceActive=false;}
    private void render(){
        captureDraft();stopVoice();viewEpoch++;draftInput=null;voiceStatus=null;voiceButton=null;tools.removeAllViews();content.removeAllViews();dock.removeAllViews();commitButton=null;dockMessage=null;reuseName=null;reuseCommit=null;reuseCount=null;dock.setVisibility(View.GONE);itemRows=null;previewPanel=null;rowViews.clear();rowChecks.clear();
        boolean overview=currentId.isEmpty();banner.setVisibility(overview?View.VISIBLE:View.GONE);
        if(getResources().getConfiguration().screenHeightDp>=500){TextView title=text(overview?"말로 장보기":(current()==null?"목록":current().optString("title")),overview?27:23,INK);title.setTypeface(Typeface.DEFAULT,Typeface.BOLD);tools.addView(title);}
        LinearLayout nav=new LinearLayout(this);
        rowButton(nav,button(overview?"사용 안내":(!reuseId.isEmpty()?"선택 취소":composer?"입력 닫기":"목록으로"),v->{if(overview)help();else navigateBack();}));
        rowButton(nav,button("글씨 "+textSize,v->sizeDialog()));
        undoButton=button("되돌리기",v->act(()->{Position before=capturePosition("");String metadata=currentMeta();boolean rows=itemRows!=null&&!composer&&reuseId.isEmpty();store.undo();if(current()==null){currentId="";render();}else if(rows&&metadata.equals(currentMeta())){buildItemRows();undoButton.setEnabled(store.canUndo());restorePosition(before,false,false);}else render();}));undoButton.setEnabled(store.canUndo()&&!composer&&reuseId.isEmpty());rowButton(nav,undoButton);tools.addView(nav);
        if(overview)showOverview();else if(current()==null){currentId="";render();}else if(!reuseId.isEmpty())showReuse();else if(composer)showComposer();else showItems();
    }
    private void leaveList(){captureDraft();if(!draft.trim().isEmpty())new AlertDialog.Builder(this).setTitle("입력 중인 내용이 있어요").setMessage("목록으로 나가면 아직 추가하지 않은 입력을 비웁니다.").setPositiveButton("비우고 나가기",(d,w)->{resetDraft();currentId="";render();}).setNegativeButton("계속 입력",null).show();else{currentId="";composer=false;render();}}
    private void resetDraft(){draft="";previewSource="";reviewToken="";candidates.clear();composer=false;draftInput=null;}
    private void sizeDialog(){String[] names={"보통 · 18","크게 · 22","아주 크게 · 28"};int[] values={18,22,28};int selected=textSize==18?0:textSize==28?2:1;new AlertDialog.Builder(this).setTitle("목록 글씨 크기").setSingleChoiceItems(names,selected,(d,w)->{textSize=values[w];getPreferences(0).edit().putInt("textSize",textSize).apply();d.dismiss();render();}).setNegativeButton("닫기",null).show();}
    private void showOverview(){
        content.addView(text("말로 적고, 확인하고, 하나씩 체크해요",17,MUTED));
        LinearLayout tabs=new LinearLayout(this);String[] modes={"active","archived","template"};String[] labels={"장보기","보관함","템플릿"};for(int i=0;i<3;i++){final String m=modes[i];rowButton(tabs,mode.equals(m)?primary(labels[i],v->{}):button(labels[i],v->{mode=m;render();}));}full(content,tabs);
        full(content,primary("+ 새 장보기 목록",v->nameDialog(null,false)));
        int count=0;JSONArray all=store.all();for(int i=0;i<all.length();i++){JSONObject list=all.optJSONObject(i);boolean matches=mode.equals("template")?list.optBoolean("template"):!list.optBoolean("template")&&list.optBoolean("archived")==mode.equals("archived");if(!matches)continue;count++;LinearLayout card=panel();String id=list.optString("id");JSONArray items=list.optJSONArray("items");int checked=0;for(int j=0;j<items.length();j++)if(items.optJSONObject(j).optBoolean("checked"))checked++;
            card.addView(text(list.optString("title"),textSize,INK));card.addView(text(items.length()+"개 중 "+checked+"개 체크",16,MUTED));
            full(card,button(mode.equals("active")?"목록 열기":"내용 보기",v->{currentId=id;resetDraft();render();}));
            if(!mode.equals("active"))full(card,primary("항목 골라 다시 사용",v->{currentId=id;resetDraft();beginReuse();}));
        }
        if(count==0)content.addView(text(mode.equals("active")?"아직 목록이 없어요. ‘새 장보기 목록’으로 시작해 보세요.":"아직 여기에 보관된 목록이 없어요.",22,MUTED));
        full(content,button("개인정보와 광고 선택",v->help()));
        if(BuildConfig.IS_PREVIEW)content.addView(text("내부 테스트 · Google 테스트 광고",13,MUTED));
    }
    private void nameDialog(JSONObject source,boolean template){
        final String token=UUID.randomUUID().toString();final int epoch=viewEpoch;EditText title=input("목록 이름",source==null?"":source.optString("title")+(template?" 템플릿":" 다시 장보기"),false);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(template?"템플릿으로 저장":"새 장보기 목록").setView(title).setPositiveButton("만들기",null).setNegativeButton("닫기",null).create();
        dialog.setOnShowListener(d->dialog.getButton(-1).setOnClickListener(v->{if(!submissions.claim(token,epoch==viewEpoch))return;boolean success=false;try{String id=store.create(title.getText().toString(),source,template);success=true;dialog.dismiss();currentId=id;resetDraft();render();}catch(Exception error){toast(error.getMessage());}finally{submissions.finish(token,success);}}));dialog.show();
    }
    private void showItems(){
        JSONObject list=current();boolean readOnly=list.optBoolean("archived")||list.optBoolean("template");
        listCount=text("",16,TEAL);listCount.setTypeface(Typeface.DEFAULT,Typeface.BOLD);tools.addView(listCount);
        if(readOnly)content.addView(text(list.optBoolean("template")?"템플릿 원본 · 다시 쓸 항목만 고를 수 있어요":"보관한 원본 · 항목은 그대로 남아 있어요",16,MUTED));
        itemRows=new LinearLayout(this);itemRows.setOrientation(LinearLayout.VERTICAL);itemRows.setBackground(shape(Color.WHITE));full(content,itemRows);buildItemRows();
        dock.setVisibility(View.VISIBLE);LinearLayout actions=new LinearLayout(this);
        rowButton(actions,primary(readOnly?"선택해서 다시 사용":"+ 항목 추가",v->{if(readOnly)beginReuse();else{composer=true;render();}}));
        rowButton(actions,button("목록 작업",v->listActions()));dock.addView(actions);
    }
    private void listActions(){
        JSONObject list=current();if(list==null)return;
        boolean archived=list.optBoolean("archived"),template=list.optBoolean("template");
        List<String> options=new ArrayList<>();options.add("목록 텍스트 공유");
        if(!archived&&!template){options.add("목록 이름 바꾸기");options.add("템플릿으로 저장");options.add("장보기 완료 · 보관");}
        else {options.add("항목 골라 다시 사용");if(archived)options.add("이 목록을 진행 중으로 복원");}
        new AlertDialog.Builder(this).setTitle("목록 작업").setItems(options.toArray(new String[0]),(d,index)->{
            String action=options.get(index);
            if(action.equals("목록 텍스트 공유")){shareList();return;}
            if(action.equals("목록 이름 바꾸기")){rename();return;}
            if(action.equals("템플릿으로 저장")){nameDialog(list,true);return;}
            if(action.equals("항목 골라 다시 사용")){beginReuse();return;}
            if(action.equals("이 목록을 진행 중으로 복원")){act(()->{store.change(data->BasketStore.find(data,currentId).put("archived",false));render();});return;}
            new AlertDialog.Builder(this).setTitle("완료하고 보관할까요?").setMessage("체크하지 않은 항목도 그대로 보관합니다. 다음 장보기에는 필요한 항목만 골라 다시 쓸 수 있어요.").setPositiveButton("보관",(x,w)->act(()->{store.change(data->BasketStore.find(data,currentId).put("archived",true));mode="archived";currentId="";render();})).setNegativeButton("계속 장보기",null).show();
        }).setNegativeButton("닫기",null).show();
    }
    private void shareList(){
        JSONObject list=current();if(list==null)return;stopVoice();banner.setVisibility(View.GONE);StringBuilder out=new StringBuilder(list.optString("title"));JSONArray items=list.optJSONArray("items");
        for(int i=0;i<items.length();i++){JSONObject item=items.optJSONObject(i);out.append("\n").append(item.optBoolean("checked")?"☑ ":"☐ ").append(item.optString("name")).append(" · ").append(item.optString("quantity","1"));}
        try{ShareFiles.shareText(this,out.toString());}catch(RuntimeException e){toast("공유할 앱을 찾지 못했어요.");}
    }
    private void buildItemRows(){
        if(itemRows==null||current()==null)return;itemRows.removeAllViews();rowViews.clear();rowChecks.clear();
        JSONObject list=current();JSONArray items=list.optJSONArray("items");boolean readOnly=list.optBoolean("archived")||list.optBoolean("template");int checked=0;
        for(int i=0;i<items.length();i++)if(items.optJSONObject(i).optBoolean("checked"))checked++;
        listCount.setText("남은 것 "+(items.length()-checked)+"개  ·  구입한 것 "+checked+"개");
        for(boolean completed:new boolean[]{false,true}){
            TextView section=text((completed?"구입한 것 · ":"살 것 · ")+(completed?checked:items.length()-checked),17,completed?MUTED:TEAL);section.setTypeface(Typeface.DEFAULT,Typeface.BOLD);section.setPadding(dp(14),dp(12),dp(14),dp(9));itemRows.addView(section);
            int sectionCount=0;
            for(int i=0;i<items.length();i++){
                JSONObject item=items.optJSONObject(i);if(item.optBoolean("checked")!=completed)continue;sectionCount++;
                String itemId=item.optString("id"),listId=currentId;final int epoch=viewEpoch;
                LinearLayout row=new LinearLayout(this);row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(dp(7),dp(3),dp(3),dp(3));row.setBackgroundColor(completed?0xfff2f6f3:Color.WHITE);
                CheckBox check=new CheckBox(this);check.setText(item.optString("name")+"  ·  "+item.optString("quantity","1"));check.setTextSize(textSize);check.setTextColor(completed?MUTED:INK);check.setButtonTintList(android.content.res.ColorStateList.valueOf(TEAL));check.setMinHeight(dp(58));check.setPadding(dp(5),dp(7),dp(4),dp(7));check.setChecked(completed);check.setEnabled(!readOnly);check.setTag(itemId);
                check.setContentDescription(item.optString("name")+", 수량 "+item.optString("quantity","1")+", "+(completed?"구입함, 다시 누르면 남은 항목으로 복원":"아직 구입 안 함"));
                row.addView(check,new LinearLayout.LayoutParams(0,-2,1));rowViews.put(itemId,row);rowChecks.put(itemId,check);
                check.setOnCheckedChangeListener((b,on)->{
                    if(epoch!=viewEpoch||!listId.equals(currentId))return;
                    Position position=capturePosition(itemId);boolean accessibility=check.isAccessibilityFocused();boolean focused=check.hasFocus();
                    act(()->store.change(data->{JSONArray a=BasketStore.find(data,listId).getJSONArray("items");for(int j=0;j<a.length();j++)if(itemId.equals(a.getJSONObject(j).getString("id")))a.getJSONObject(j).put("checked",on);}));buildItemRows();undoButton.setEnabled(store.canUndo());restorePosition(position,focused,accessibility);itemRows.announceForAccessibility(item.optString("name")+", 목록 상태를 갱신했어요");
                });
                if(!readOnly){Button edit=button("수정",v->editItem(itemId));edit.setTextSize(14);edit.setPadding(dp(4),dp(6),dp(4),dp(6));edit.setMinHeight(dp(48));edit.setContentDescription(item.optString("name")+" 이름과 수량 수정");row.addView(edit,new LinearLayout.LayoutParams(dp(54),-2));}
                itemRows.addView(row);View line=new View(this);line.setBackgroundColor(0xffe2ebe6);itemRows.addView(line,new LinearLayout.LayoutParams(-1,dp(1)));
            }
            if(sectionCount==0){TextView empty=text(completed?"아직 체크한 항목이 없어요":"남은 항목이 없어요. 필요한 것을 추가하거나 완료 보관하세요.",16,MUTED);empty.setPadding(dp(16),dp(5),dp(16),dp(15));itemRows.addView(empty);}
        }
    }
    private static final class Position {int scrollY,screenY;String anchor="";}
    private Position capturePosition(String exclude){
        Position position=new Position();position.scrollY=scroll.getScrollY();int[] viewport=new int[2];scroll.getLocationOnScreen(viewport);
        for(Map.Entry<String,View> entry:rowViews.entrySet()){
            if(entry.getKey().equals(exclude))continue;View row=entry.getValue();int[] location=new int[2];row.getLocationOnScreen(location);
            if(location[1]+row.getHeight()>viewport[1]){position.anchor=entry.getKey();position.screenY=location[1];break;}
        }return position;
    }
    private void restorePosition(Position position,boolean focus,boolean accessibility){
        scroll.post(()->{View anchor=rowViews.get(position.anchor);CheckBox check=rowChecks.get(position.anchor);if(focus&&check!=null)check.requestFocus();if(accessibility&&check!=null)check.performAccessibilityAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_ACCESSIBILITY_FOCUS,null);
            if(anchor==null){scroll.scrollTo(0,position.scrollY);return;}int[] location=new int[2];anchor.getLocationOnScreen(location);scroll.scrollTo(0,scroll.getScrollY()+location[1]-position.screenY);
        });
    }
    private void rename(){EditText field=input("목록 이름",current().optString("title"),false);AlertDialog d=new AlertDialog.Builder(this).setTitle("목록 이름 바꾸기").setView(field).setPositiveButton("저장",null).setNegativeButton("닫기",null).create();d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->act(()->{String value=BasketStore.valid(field.getText().toString(),60);store.change(data->BasketStore.find(data,currentId).put("title",value));d.dismiss();render();})));d.show();}
    private void editItem(String id){
        JSONArray original=current().optJSONArray("items");JSONObject found=null;for(int i=0;i<original.length();i++)if(id.equals(original.optJSONObject(i).optString("id")))found=original.optJSONObject(i);if(found==null)return;
        LinearLayout fields=new LinearLayout(this);fields.setOrientation(LinearLayout.VERTICAL);fields.setPadding(dp(22),0,dp(22),0);EditText name=input("항목 이름",found.optString("name"),false),qty=input("수량 (예: 2개, 1봉)",found.optString("quantity","1"),false);fields.addView(name);fields.addView(qty);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("이름과 수량 확인").setView(fields).setPositiveButton("저장",null).setNeutralButton("항목 삭제",null).setNegativeButton("닫기",null).create();dialog.setOnShowListener(d->{dialog.getButton(-1).setOnClickListener(v->act(()->{String n=BasketStore.valid(name.getText().toString(),120),q=BasketStore.valid(qty.getText().toString(),30);store.change(data->{JSONArray a=BasketStore.find(data,currentId).getJSONArray("items");for(int j=0;j<a.length();j++)if(id.equals(a.getJSONObject(j).getString("id")))a.getJSONObject(j).put("name",n).put("quantity",q);});dialog.dismiss();render();}));dialog.getButton(-3).setTextColor(CORAL);dialog.getButton(-3).setOnClickListener(v->act(()->{store.change(data->{JSONArray a=BasketStore.find(data,currentId).getJSONArray("items");for(int j=a.length()-1;j>=0;j--)if(id.equals(a.getJSONObject(j).getString("id")))a.remove(j);});dialog.dismiss();render();toast("항목을 지웠어요. 위의 되돌리기로 복원할 수 있어요.");}));});dialog.show();
    }
    private void showComposer(){
        content.addView(text("1 입력 수정 → 2 미리보기 → 3 추가",18,TEAL));
        draftInput=input("예: 우유, 달걀\n두부",draft,true);draftInput.setId(R.id.basket_draft);full(content,draftInput);
        draftInput.addTextChangedListener(new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int start,int count,int after){}public void afterTextChanged(android.text.Editable s){}public void onTextChanged(CharSequence s,int start,int before,int count){if(!draft.equals(s.toString())){draft=s.toString();invalidateReview();}}});
        voiceStatus=text("아직 목록에 추가되지 않았어요. 직접 고친 뒤 확인해 주세요.",15,MUTED);voiceStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);content.addView(voiceStatus);
        LinearLayout voiceRow=new LinearLayout(this);voiceButton=button("마이크로 말하기",v->{captureDraft();startVoiceChoice();});rowButton(voiceRow,voiceButton);rowButton(voiceRow,button("끝내기",v->voice.stop()));rowButton(voiceRow,button("취소",v->{stopVoice();voiceButton.setEnabled(true);voiceStatus.setText("음성만 취소했어요. 입력한 글은 그대로입니다.");}));full(content,voiceRow);
        Button advanced=button(advancedOpen?"분리 옵션 닫기 ▴":"분리 옵션 ▾",v->{advancedOpen=!advancedOpen;advancedPanel.setVisibility(advancedOpen?View.VISIBLE:View.GONE);((Button)v).setText(advancedOpen?"분리 옵션 닫기 ▴":"분리 옵션 ▾");});full(content,advanced);
        advancedPanel=new LinearLayout(this);advancedPanel.setOrientation(LinearLayout.VERTICAL);advancedPanel.setVisibility(advancedOpen?View.VISIBLE:View.GONE);full(content,advancedPanel);
        CheckBox conjunctions=new CheckBox(this);conjunctions.setText("독립된 그리고·및·또는·하고도 나누기");conjunctions.setTextSize(16);conjunctions.setChecked(splitConjunctions);conjunctions.setOnCheckedChangeListener((v,b)->{splitConjunctions=b;invalidateReview();});full(advancedPanel,conjunctions);
        CheckBox merge=new CheckBox(this);merge.setText("이름이 정확히 같은 항목은 하나만 유지");merge.setTextSize(16);merge.setChecked(mergeDuplicates);merge.setOnCheckedChangeListener((v,b)->{mergeDuplicates=b;invalidateReview();});full(advancedPanel,merge);
        advancedPanel.addView(text("기본은 쉼표·줄바꿈으로 나눕니다. 붙인 말·수량은 추측하지 않아요. 두 옵션 모두 선택 사항입니다.",14,MUTED));
        previewPanel=new LinearLayout(this);previewPanel.setOrientation(LinearLayout.VERTICAL);previewPanel.setPadding(dp(15),dp(12),dp(15),dp(12));previewPanel.setBackground(shape(0xffeaf3ed));full(content,previewPanel);populatePreview();
        dock.setVisibility(View.VISIBLE);dockMessage=text("",14,MUTED);dockMessage.setMaxLines(2);dock.addView(dockMessage);LinearLayout confirms=new LinearLayout(this);rowButton(confirms,button("미리보기",v->reviewOrCommit(false)));commitButton=primary("확인 후 추가",v->reviewOrCommit(true));rowButton(confirms,commitButton);dock.addView(confirms);updateCommitDock();
    }
    private void invalidateReview(){candidates.clear();previewSource="";reviewToken="";if(previewPanel!=null)previewPanel.setVisibility(View.GONE);updateCommitDock();}
    private boolean reviewCurrent(){return !reviewToken.isEmpty()&&!candidates.isEmpty()&&draft.equals(previewSource)&&splitConjunctions==previewSplit&&mergeDuplicates==previewMerge;}
    private void updateCommitDock(){if(commitButton==null||!composer)return;boolean ready=reviewCurrent();commitButton.setText(ready?"확인한 "+candidates.size()+"개 추가":"확인 후 추가");commitButton.setEnabled(!voiceActive&&ready);if(dockMessage!=null)dockMessage.setText(ready?candidates.size()+"개 확인됨 · 누르면 목록에 저장합니다":"입력한 글은 아직 저장 전 · 먼저 미리보기로 확인");}
    private void populatePreview(){
        if(previewPanel==null)return;previewPanel.removeAllViews();previewPanel.setVisibility(reviewCurrent()?View.VISIBLE:View.GONE);if(!reviewCurrent())return;
        previewPanel.addView(text("추가 전 확인 · "+candidates.size()+"개",20,TEAL));for(int i=0;i<candidates.size();i++)previewPanel.addView(text((i+1)+". "+candidates.get(i),textSize,INK));
        try{int[] count=store.previewAdd(currentId,candidates,mergeDuplicates);previewPanel.addView(text("추가 "+count[0]+"개 · 정확 중복 제외 "+count[1]+"개",16,TEAL));}catch(Exception error){previewPanel.addView(text(error.getMessage(),16,CORAL));}
        previewPanel.addView(text("수량은 1로 시작합니다. 목록에서 직접 바꿀 수 있어요. 원문을 고치면 다시 확인합니다.",14,MUTED));
    }
    private void reviewOrCommit(boolean confirm){
        captureDraft();if(voiceActive)return;
        if(!confirm){act(()->{List<String> parsed=BasketParser.split(draft,splitConjunctions);if(parsed.isEmpty())throw new IllegalArgumentException("추가할 내용을 먼저 입력해 주세요.");store.previewAdd(currentId,parsed,mergeDuplicates);candidates=new ArrayList<>(parsed);previewSource=draft;previewSplit=splitConjunctions;previewMerge=mergeDuplicates;reviewToken=UUID.randomUUID().toString();populatePreview();updateCommitDock();hideKeyboard();scroll.post(()->scroll.smoothScrollTo(0,Math.max(0,previewPanel.getTop()-dp(8))));});return;}
        if(!reviewCurrent()){toast("미리보기를 먼저 확인해 주세요.");return;}
        final String token=reviewToken,listId=currentId;final int epoch=viewEpoch;final List<String> names=new ArrayList<>(candidates);
        if(!submissions.claim(token,epoch==viewEpoch&&reviewCurrent()))return;boolean success=false;
        try{if(!BasketParser.split(draft,splitConjunctions).equals(names))throw new IllegalArgumentException("입력이 바뀌었어요. 다시 확인해 주세요.");int[] count=store.previewAdd(listId,names,mergeDuplicates);store.addOnce(listId,names,mergeDuplicates,token);success=true;resetDraft();hideKeyboard();render();scroll.scrollTo(0,0);toast(count[0]+"개 추가 · 정확 중복 "+count[1]+"개 제외");}
        catch(Exception error){toast(error.getMessage()==null?"저장하지 못했어요. 다시 확인해 주세요.":error.getMessage());}
        finally{submissions.finish(token,success);updateCommitDock();}
    }
    private void hideKeyboard(){android.view.inputmethod.InputMethodManager manager=(android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);if(manager!=null)manager.hideSoftInputFromWindow(root.getWindowToken(),0);}
    private void beginReuse(){
        JSONObject source=current();if(source==null)return;reuseId=currentId;reuseTitle=source.optString("title")+" 다시 장보기";reuseSelection.clear();reuseToken=UUID.randomUUID().toString();composer=false;render();scroll.scrollTo(0,0);
    }
    private void showReuse(){
        JSONObject source=store.find(reuseId);if(source==null){reuseId="";render();return;}
        content.addView(text("필요한 항목만 골라 새 목록으로",21,TEAL));content.addView(text("원본은 바뀌지 않고, 새 목록의 체크만 풀립니다. 수량은 그대로 가져옵니다.",16,MUTED));
        reuseName=input("새 목록 이름",reuseTitle,false);reuseName.setId(R.id.basket_reuse_name);full(content,reuseName);reuseName.addTextChangedListener(new android.text.TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int c){}public void afterTextChanged(android.text.Editable e){}public void onTextChanged(CharSequence s,int a,int b,int c){reuseTitle=s.toString();}});
        LinearLayout select=new LinearLayout(this);rowButton(select,button("전체 선택",v->{JSONArray a=source.optJSONArray("items");for(int i=0;i<a.length();i++)reuseSelection.add(a.optJSONObject(i).optString("id"));renderReuseRows(source);}));rowButton(select,button("선택 비우기",v->{reuseSelection.clear();renderReuseRows(source);}));full(content,select);
        reuseRows=new LinearLayout(this);reuseRows.setOrientation(LinearLayout.VERTICAL);full(content,reuseRows);
        dock.setVisibility(View.VISIBLE);reuseCount=text("",15,TEAL);dock.addView(reuseCount);reuseCommit=primary("선택한 항목으로 새 목록",v->commitReuse());full(dock,reuseCommit);renderReuseRows(source);
    }
    private void renderReuseRows(JSONObject source){
        reuseRows.removeAllViews();JSONArray a=source.optJSONArray("items");for(int i=0;i<a.length();i++){
            JSONObject item=a.optJSONObject(i);String id=item.optString("id");CheckBox choice=new CheckBox(this);choice.setText(item.optString("name")+"  ·  "+item.optString("quantity","1"));choice.setTextSize(textSize);choice.setTextColor(INK);choice.setButtonTintList(android.content.res.ColorStateList.valueOf(TEAL));choice.setMinHeight(dp(58));choice.setChecked(reuseSelection.contains(id));choice.setOnCheckedChangeListener((b,on)->{if(on)reuseSelection.add(id);else reuseSelection.remove(id);updateReuseCount();});full(reuseRows,choice);
        }updateReuseCount();
    }
    private void updateReuseCount(){if(reuseCount!=null)reuseCount.setText("선택 "+reuseSelection.size()+"개 · 원본은 그대로 유지");if(reuseCommit!=null)reuseCommit.setEnabled(!reuseSelection.isEmpty());}
    private void commitReuse(){
        if(reuseName!=null)reuseTitle=reuseName.getText().toString();final String token=reuseToken,sourceId=reuseId;
        if(!submissions.claim(token,!sourceId.isEmpty()&&!reuseSelection.isEmpty()))return;boolean success=false;
        try{String id=store.createSelected(reuseTitle,store.find(sourceId),new LinkedHashSet<>(reuseSelection),token);success=true;reuseId="";reuseSelection.clear();reuseToken="";currentId=id;mode="active";resetDraft();hideKeyboard();render();scroll.scrollTo(0,0);toast("선택한 항목으로 새 목록을 만들었어요.");}
        catch(Exception error){toast(error.getMessage()==null?"새 목록을 만들지 못했어요.":error.getMessage());}
        finally{submissions.finish(token,success);}
    }
    private void startVoiceChoice(){
        if(voiceActive)return;
        if(!voice.available()){voiceStatus.setText("기기에 음성 인식 서비스가 없어요. 키보드로 입력해 주세요.");return;}
        if(voice.onDeviceAvailable())ensureMic(false);
        else new AlertDialog.Builder(this).setTitle("음성 제공자를 사용할까요?").setMessage("이 기기에는 앱에서 사용할 온디바이스 음성 인식이 없어요. 선택한 Android 음성 제공자가 음성을 처리하며 서버 전송과 네트워크 사용이 발생할 수 있습니다. 제공자의 개인정보 정책이 적용됩니다. 원하지 않으면 키보드로 입력할 수 있어요.").setPositiveButton("이번에 음성 사용",(d,w)->ensureMic(true)).setNegativeButton("키보드로 입력",(d,w)->draftInput.requestFocus()).show();
    }
    private void ensureMic(boolean network){
        if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){permissionPending=true;requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},81);return;}
        voice.start(network);
    }
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);if(request==81&&permissionPending){permissionPending=false;if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED){if(voiceStatus!=null)voiceStatus.setText("마이크를 허용했어요. ‘마이크로 말하기’를 다시 누르면 시작합니다.");}else new AlertDialog.Builder(this).setTitle("키보드로 계속 입력할 수 있어요").setMessage("마이크 권한을 허용하지 않아 음성을 시작하지 않았습니다.").setPositiveButton("확인",null).setNeutralButton("앱 권한 설정",(d,w)->startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+getPackageName())))).show();}}
    private void help(){new AlertDialog.Builder(this).setTitle("말로 장보기 · 사용과 개인정보").setMessage("목록과 항목은 이 기기에만 저장하며 앱 서버로 전송하지 않습니다. 앱 데이터 삭제·제거 시 사라지고 자동 백업하지 않습니다. 공유를 선택하면 다른 앱으로 목록이 전달됩니다. 음성은 지원되는 기기에서 온디바이스를 우선하며, 미지원 시 매회 안내 후 선택한 음성 제공자가 처리합니다. 앱은 음성 녹음 파일을 저장하지 않습니다.\n\n광고는 목록 개요 아래에만 표시하고 항목·목록 이름을 광고에 넣지 않습니다. Google 광고·동의 SDK는 식별자·대략적 위치·상호작용·진단 정보를 처리할 수 있습니다.\n\n체크·수정·항목 삭제·보관 직후 위의 ‘되돌리기’로 한 단계 복원합니다. 보관함에서 다시 사용하면 모든 체크를 해제한 새 목록이 생깁니다.").setPositiveButton("닫기",null).setNeutralButton("광고 개인정보 선택",(d,w)->{if(ads!=null)ads.privacyOptions();}).setNegativeButton("웹 개인정보",(d,w)->{try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse("https://barolab-daily-apps.pages.dev/shopping/privacy")));}catch(ActivityNotFoundException e){toast("브라우저에서 barolab-daily-apps.pages.dev 를 열어 주세요.");}}).show();}
    private void navigateBack(){if(!reuseId.isEmpty()){reuseId="";reuseSelection.clear();reuseToken="";render();return;}if(composer){captureDraft();if(draft.trim().isEmpty()){resetDraft();render();}else leaveList();}else leaveList();}
    @Override protected void onSaveInstanceState(Bundle state){captureDraft();state.putString("currentId",currentId);state.putString("mode",mode);state.putString("draft",draft);state.putBoolean("composer",composer);state.putBoolean("split",splitConjunctions);state.putBoolean("merge",mergeDuplicates);state.putString("previewSource",previewSource);state.putStringArrayList("candidates",new ArrayList<>(candidates));state.putString("reviewToken",reviewToken);state.putBoolean("previewSplit",previewSplit);state.putBoolean("previewMerge",previewMerge);state.putBoolean("advancedOpen",advancedOpen);state.putString("reuseId",reuseId);state.putString("reuseTitle",reuseName==null?reuseTitle:reuseName.getText().toString());state.putString("reuseToken",reuseToken);state.putStringArrayList("reuseSelection",new ArrayList<>(reuseSelection));super.onSaveInstanceState(state);}
    @Override protected void onResume(){super.onResume();stopped=false;updateCommitDock();if(ads!=null)ads.resume();}
    @Override protected void onPause(){captureDraft();stopVoice();if(voiceStatus!=null)voiceStatus.setText("음성 입력은 중지됐어요. 필요하면 마이크를 다시 눌러 주세요.");if(voiceButton!=null)voiceButton.setEnabled(true);stopped=true;if(ads!=null)ads.pause();super.onPause();}
    @Override protected void onDestroy(){stopVoice();if(ads!=null)ads.destroy();super.onDestroy();}
}
