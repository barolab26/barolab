"""Compatibility entry point; use naver_blog_posting.posting for new calls."""
import sys
from pathlib import Path

if __name__ == "__main__":
    import runpy
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    runpy.run_module("naver_blog_posting.posting", run_name="__main__")
else:
    from naver_blog_posting import posting
    sys.modules[__name__] = posting
