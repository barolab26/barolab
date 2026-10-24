from pathlib import Path
from unittest.mock import Mock
from common import ego_executor


def test_complex_visual_review_uses_explicit_independent_high_without_changing_doctor_default(tmp_path,monkeypatch):
    from common import ego_screen,llm_client,llm_settings
    folder=tmp_path;screen=folder/'ego-screen-review/screen-000.png';screen.parent.mkdir();screen.write_bytes(b'screenshot fixture')
    monkeypatch.setattr(ego_screen,'run',lambda *a,**k:{'turns':[{'screenshot':screen.name}],'observations':[]})
    monkeypatch.setattr(llm_settings,'get_agent_brain',lambda role:{'provider':'codex','model':'observed-model','reasoningEffort':'high'})
    def review(prompt,**kwargs):
        assert kwargs['agent_slot']=='doctor' and kwargs['provider']=='codex'
        assert kwargs['reasoning_effort']=='high' and kwargs['model_override']=='observed-model'
        kwargs['observer']('codex','observed-model','returned',actual_model='observed-model',reasoning_effort='high')
        return {'approved':True,'pcWholeDocumentVisualReview':True,'mobileWholeDocumentVisualReview':False,'defects':[],'limitations':['mobile unobserved']}
    monkeypatch.setattr(llm_client,'generate_json',review)
    result=ego_executor.review_screen_editor(Mock(),{'presentation':{}},folder,9334)
    assert result['mobileWholeDocumentVisualReview'] is False
    assert result['reviewRoute'][-1]['actualModel']=='observed-model'
    assert result['reviewLatencyMs']>=0
