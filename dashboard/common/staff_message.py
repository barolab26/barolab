"""Decode a model's accidental message envelope for display, preserving other JSON."""
import json


def display_message(value):
    for _ in range(3):
        if not isinstance(value,str) or len(value)>16000:return value
        text=value.strip()
        if text.startswith('```json\n') and text.endswith('```'):text=text[8:-3].strip()
        elif text.startswith('```\n') and text.endswith('```'):text=text[4:-3].strip()
        try:decoded=json.loads(text)
        except (ValueError,TypeError):return value
        if not isinstance(decoded,dict) or set(decoded)!={'message'} or not isinstance(decoded['message'],str):return value
        value=decoded['message']
    return value
