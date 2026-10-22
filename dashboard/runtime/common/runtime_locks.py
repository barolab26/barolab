"""Use one Linux lock inode across WSL mount namespaces."""
import hashlib
from pathlib import Path
import sys


def runtime_lock_path(path):
    path=Path(path).resolve()
    if sys.platform=='linux' and len(path.parts)>2 and path.parts[1]=='mnt':
        # DrvFS mounts can expose identical Windows files as different lock inodes.
        key=hashlib.sha256(str(path).encode()).hexdigest()
        return Path.home()/'.barolab/locks'/(path.name+'-'+key[:24]+'.lock')
    return path
