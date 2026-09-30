"""Geox launcher: clear screen, ASCII banner, then pick Web UI or CLI.

Invoked by run_geox.bat as `python -m geox.launch`.
`python -m geox.launch --cli ...` skips the menu and goes straight to the CLI.
"""

import os
import sys

# unlock ANSI colors in the Windows console
os.system("")

# make block characters safe on any console codepage
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

GREEN, GREY, CYAN, RESET, BOLD = "\033[92m", "\033[90m", "\033[96m", "\033[0m", "\033[1m"

BANNER = r"""
   █████████  ██████████    ███████    █████ █████
  ███░░░░░███░░███░░░░░█  ███░░░░░███ ░░███ ░░███
 ███     ░░░  ░███  █ ░  ███     ░░███ ░░███ ███
░███          ░██████   ░███      ░███  ░░█████
░███    █████ ░███░░█   ░███      ░███   ███░███
░░███  ░░███  ░███ ░   █░░███     ███   ███ ░░███
 ░░█████████  ██████████ ░░░███████░   █████ █████
  ░░░░░░░░░  ░░░░░░░░░░    ░░░░░░░    ░░░░░ ░░░░░
"""


def _clear():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _read_key():
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            arrow = msvcrt.getch()
            return {"H": "up", "P": "down"}.get(arrow.decode(errors="ignore"), "")
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b"\x03":
            raise KeyboardInterrupt
        return ""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch == "\x1b":
        return {"[A": "up", "[B": "down"}.get(sys.stdin.read(2), "")
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x03":
        raise KeyboardInterrupt
    return ""


def _menu(options, subtitle):
    idx = 0
    while True:
        _clear()
        print(GREEN + BANNER + RESET)
        print(f"  {BOLD}spoof the GPS of a phone connected to this PC{RESET}\n")
        print(f"  {CYAN}{subtitle}{RESET}\n")
        for i, opt in enumerate(options):
            if i == idx:
                print(f"   {GREEN}>> {opt}{RESET}")
            else:
                print(f"      {GREY}{opt}{RESET}")
        print(f"\n   {GREY}up/down arrows to move - Enter to select - Ctrl+C to quit{RESET}")
        key = _read_key()
        if key == "up":
            idx = (idx - 1) % len(options)
        elif key == "down":
            idx = (idx + 1) % len(options)
        elif key == "enter":
            return idx


def main():
    args = sys.argv[1:]
    if "--cli" in args:
        from .cli import main as cli_main

        rest = args[args.index("--cli") + 1:] or ["--help"]
        return cli_main(rest) or 0

    try:
        choice = _menu(
            [
                "Web UI  (map interface, recommended)",
                "Command line  (terminal only)",
            ],
            "how do you want to run Geox?",
        )
    except KeyboardInterrupt:
        return 0

    if choice == 0:
        from .server import main as server_main

        sys.argv = [sys.argv[0]] + [a for a in args if a.startswith("--")]
        server_main()
        return 0

    from .cli import main as cli_main

    print(f"{GREY}tip: python -m geox --location \"Paris\" --movement roam 25 4.5{RESET}")
    return cli_main(args or ["--help"]) or 0


if __name__ == "__main__":
    sys.exit(main())
