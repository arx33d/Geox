"""First-run setup display: installs Geox's libraries with a progress bar.

Runs under the Python that the launcher just prepared (venv or private
runtime).  Installs the requirements one by one so progress is real, not
decorative: every tick of the bar is a component that finished installing.
"""

import os
import subprocess
import sys

# unlock ANSI colors in the Windows console
os.system("")

GREEN, GREY, CYAN, RESET = "\033[92m", "\033[90m", "\033[96m", "\033[0m"
BAR_WIDTH = 40


def render(pct, label):
    fill = int(BAR_WIDTH * pct / 100)
    bar = GREEN + "#" * fill + RESET + GREY + "-" * (BAR_WIDTH - fill) + RESET
    sys.stdout.write(f"\r[{bar}] {pct:3d}%  {CYAN}{label}{RESET}   ")
    sys.stdout.flush()


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reqs = []
    with open(os.path.join(root, "requirements.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                reqs.append(line)
    if not reqs:
        return 0

    print("Installing Geox components")
    render(0, "starting")
    for i, req in enumerate(reqs):
        name = req.split(";")[0].split(">=")[0].split("==")[0].strip()
        render(int(i * 100 / len(reqs)), f"installing {name}")
        p = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--no-warn-script-location", req],
            capture_output=True, text=True,
        )
        if p.returncode != 0:
            render(int(i * 100 / len(reqs)), f"failed: {name}")
            print("\n")
            detail = ((p.stdout or "") + (p.stderr or "")).strip()
            print(detail[-1500:] or "unknown pip error")
            print("\nSetup failed. Check your internet connection and try again.")
            return 1
    render(100, "done")
    print("\nSetup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
