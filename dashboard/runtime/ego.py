"""Legacy EGO commands delegate to the single durable dispatcher."""
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--naver-catch-up',action='store_true')
    parser.add_argument('--cf-catch-up',action='store_true')
    args=parser.parse_args()
    if args.naver_catch_up or args.cf_catch_up:
        channel='naver_blog_posting' if args.naver_catch_up else 'cf_posting'
        flag='--catch-up' if args.naver_catch_up else '--catch-up-today-once'
        return subprocess.run([sys.executable,'-B',str(ROOT/channel/'posting.py'),flag,'--limit','1'],cwd=ROOT).returncode
    return subprocess.run(['systemctl','--user','start','barolab-memory-review.service'],timeout=30).returncode


if __name__=='__main__':sys.exit(main())
