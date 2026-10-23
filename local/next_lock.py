"""One checkout's .next owner; shared by dev.sh and the release build."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys

PATH = Path(__file__).resolve().parent / ".check-runs/next-output.lock"
_held = set()


def held_fds():
    return tuple(_held)


class OutputLock:
    def __enter__(self):
        PATH.parent.mkdir(exist_ok=True)
        self.file = PATH.open("a+")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError("本 checkout 的 dev/build 已占用 .next，拒绝并发")
        _held.add(self.file.fileno())
        return self

    def __exit__(self, *args):
        _held.discard(self.file.fileno())
        self.file.close()


if __name__ == "__main__":
    try:
        with OutputLock():
            env = dict(os.environ, HGS_NEXT_LOCK_HELD=str(PATH))
            proc = subprocess.Popen(sys.argv[1:], env=env, pass_fds=held_fds(),
                                    start_new_session=True)
            def stop(*_):
                os.killpg(proc.pid, signal.SIGTERM)
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            sys.exit(proc.wait())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
