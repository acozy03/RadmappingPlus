import subprocess
import sys


def run() -> int:
    cmd = [
        sys.executable,
        "-m",
        "djlint",
        "--reformat",
        "--profile=jinja",
        *sys.argv[1:],
    ]
    first = subprocess.run(cmd)
    if first.returncode == 1:
        second = subprocess.run(cmd)
        return second.returncode
    return first.returncode


if __name__ == "__main__":
    raise SystemExit(run())
