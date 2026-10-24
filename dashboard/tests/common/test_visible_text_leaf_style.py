"""Use the actual CSS-reading JS: SmartEditor wraps a native run's text in <b>."""
import ast
import json
from pathlib import Path
import subprocess


def test_computed_bold_reads_text_leaf_and_detects_mixed_native_run():
    from common import visible_naver_editor as editor
    tree=ast.parse(Path(editor.__file__).read_text())
    script=next(n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value.startswith('ids=>'))
    fixture=r'''
const assert=require('node:assert/strict');
const paragraph={style:{lineHeight:'1.8'}};
const normal={fontSize:'24px',fontWeight:'400',color:'rgb(0, 0, 0)',backgroundColor:'rgba(0, 0, 0, 0)',textAlign:'left'};
const bold={...normal,fontWeight:'700'};
let leaves=[];
const outer={className:'se-fs24 se-ff-nanumgothic',style:normal,closest:()=>paragraph};
const document={getElementById:()=>outer,createTreeWalker:()=>{let at=-1;return {nextNode(){at++;this.currentNode=leaves[at];return !!this.currentNode}}}};
const NodeFilter={SHOW_TEXT:4};
const getComputedStyle=e=>e===paragraph?normal:e.style;
const leaf=style=>({nodeValue:'approved text',parentElement:{style}});
'''
    run=fixture+'\nconst measure=('+script+');\n'+r'''
leaves=[leaf(bold)];assert.equal(measure(['run']).run.bold,true);
leaves=[leaf(normal)];assert.equal(measure(['run']).run.bold,false);
leaves=[leaf(bold),leaf(normal)];assert.equal(measure(['run']).run.mixedBold,true);
'''
    result=subprocess.run(['node','-e',run],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_live_null_image_caption_is_empty_without_modifying_native_evidence():
    import copy
    from common.visible_naver_editor import editor_content
    actual={'document':{'components':[{'@ctype':'documentTitle','title':[{'nodes':[{'value':'approved'}]}]},
        {'@ctype':'image','originalWidth':100,'originalHeight':200,'caption':None}]}}
    before=copy.deepcopy(actual)
    result=editor_content(actual)
    assert result['title']=='approved' and result['images'][0]['caption']==''
    assert actual==before
    actual['document']['components'][1]['caption']=[{'nodes':[{'value':'real attribution'}]}]
    assert editor_content(actual)['images'][0]['caption']=='real attribution'
