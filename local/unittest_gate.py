"""CI host adapter for the same unittest verdict used by local/check.py."""
import json
import os
from urllib.parse import quote, unquote, urlsplit
import subprocess
import sys

from check import parse_unittest_output, verdict, safe_value, redact, _RUN_SECRETS


def main(argv):
    for key, value in os.environ.items():
        if value and any(part in key for part in ("PASSWORD", "SECRET", "TOKEN")):
            _RUN_SECRETS.update((value, quote(value, safe="")))
        if key in ("TEST_DATABASE_URL", "HGS_DATABASE_URL"):
            password = urlsplit(value).password
            if password:
                _RUN_SECRETS.update((password, unquote(password)))
    allowed, xfails = [], []
    for flag, target in (("--allow-skip", allowed), ("--allow-xfail", xfails)):
        while flag in argv:
            pos = argv.index(flag)
            if pos + 1 == len(argv):
                return 3
            target.append(argv[pos + 1])
            del argv[pos:pos + 2]
    proc = subprocess.run([sys.executable, "-m", "unittest", *argv],
                          capture_output=True, text=True)
    sys.stdout.write(redact(proc.stdout))
    sys.stderr.write(redact(proc.stderr))
    parsed = parse_unittest_output(proc.stderr)
    result = verdict(parsed, allowed, xfails)
    print(json.dumps(safe_value({"exit_code": proc.returncode,
                                "unittest": parsed, "verdict": result})))
    return 0 if proc.returncode == 0 and result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
