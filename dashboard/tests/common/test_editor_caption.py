from unittest.mock import Mock
import pytest
from common.visible_naver_editor import write_image_caption


def test_approved_caption_uses_exact_visible_image_and_preserves_other_content():
    page=Mock();frame=page.frame.return_value
    image=frame.locator.return_value.nth.return_value
    image.get_attribute.return_value='image-one'
    image.locator.return_value.count.return_value=1
    native={'document':{'components':[{'@ctype':'image','id':'image-one','fileName':'one.png','caption':None}]}}
    frame.evaluate.return_value=native
    reference={'file':'/approved/one.png','caption':'Approved attribution'}
    write_image_caption(page,reference)
    page.keyboard.type.assert_called_once_with(reference['caption'],delay=1)
    assert native['document']['components'][0]['caption'] is None
    page.reset_mock()
    native['document']['components'][0]['caption']=[{'@ctype':'paragraph','nodes':[{'value':'Approved attribution'}]}]
    write_image_caption(page,reference)
    page.keyboard.type.assert_not_called()
    native['document']['components'][0]['caption'][0]['nodes'][0]['value']='Existing different caption'
    with pytest.raises(ValueError,match='preserved'):write_image_caption(page,reference)
    page.keyboard.type.assert_not_called()


def test_caption_cannot_target_another_image():
    page=Mock();frame=page.frame.return_value
    frame.evaluate.return_value={'document':{'components':[{'@ctype':'image','id':'one','fileName':'one.png','caption':None}]}}
    frame.locator.return_value.nth.return_value.get_attribute.return_value='other-image'
    with pytest.raises(ValueError,match='identity mismatch'):
        write_image_caption(page,{'file':'one.png','caption':'Approved'})
    page.keyboard.type.assert_not_called()


def test_hidden_caption_requests_visible_toolbar_without_keyboard_or_mouse_input():
    page=Mock();frame=page.frame.return_value
    frame.evaluate.return_value={'document':{'components':[{'@ctype':'image','id':'one','fileName':'one.png','caption':None}]}}
    image=frame.locator.return_value.nth.return_value;image.get_attribute.return_value='one'
    field=image.locator.return_value;field.count.return_value=1;field.is_visible.return_value=False
    with pytest.raises(ValueError,match='hidden'):
        write_image_caption(page,{'file':'one.png','caption':'Approved'})
    field.click.assert_not_called();page.keyboard.type.assert_not_called()


def test_missing_caption_error_identifies_the_approved_reference(tmp_path):
    from common.visible_naver_editor import verify_binding
    actual={'document':{'components':[{'@ctype':'documentTitle','title':[{'nodes':[{'value':'Approved title'}]}]},
        {'@ctype':'image','id':'one','fileName':'one.png','caption':None,'originalWidth':100,'originalHeight':100}]}}
    document={'title':'Approved title','presentation':{},'blocks':[{'type':'image','file':'one.png','caption':'Approved attribution'}]}
    with pytest.raises(ValueError,match='caption missing for block-0'):
        verify_binding(Mock(),document,actual,tmp_path,0,[],record=False)
