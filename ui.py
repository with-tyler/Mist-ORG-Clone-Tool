"""
ui.py — Terminal display helpers for POC_DEMO_ORG scripts.

Provides consistent styling for banners, section headers, menus,
status messages, and input prompts. Uses ANSI escape codes only;
no third-party dependencies required.

Log capture
-----------
Call start_log() to begin recording every printed line in plain text.
Call get_log_lines() to retrieve the captured lines as a list of strings.
Call stop_log() to end capture without clearing the buffer.
"""

import os
import sys

# ──────────────────────────────────────────────────────────────────
# ANSI support detection
# ──────────────────────────────────────────────────────────────────

def _ansi_supported() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


_USE_COLOR: bool = _ansi_supported()

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_BLUE   = "\033[34m"
_WHITE  = "\033[97m"


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI code (no-op when color is disabled)."""
    if _USE_COLOR:
        return f"{code}{text}{_RESET}"
    return text


# ──────────────────────────────────────────────────────────────────
# Log-capture buffer
# ──────────────────────────────────────────────────────────────────

_LOG_LINES: list[str] = []
_LOG_ENABLED: bool = False


def start_log() -> None:
    """Enable log capture and clear any previously captured lines."""
    global _LOG_ENABLED, _LOG_LINES
    _LOG_ENABLED = True
    _LOG_LINES = []


def stop_log() -> None:
    """Disable log capture (buffer is preserved)."""
    global _LOG_ENABLED
    _LOG_ENABLED = False


def get_log_lines() -> list[str]:
    """Return a copy of all captured log lines."""
    return list(_LOG_LINES)


def _log(md_line: str) -> None:
    """Append a plain-text/markdown line to the buffer when capture is active."""
    if _LOG_ENABLED:
        _LOG_LINES.append(md_line)


# ──────────────────────────────────────────────────────────────────
# Layout constants
# ──────────────────────────────────────────────────────────────────

WIDTH = 70


def _rule(char: str = "─") -> str:
    return char * WIDTH


# ──────────────────────────────────────────────────────────────────
# Structural elements
# ──────────────────────────────────────────────────────────────────

def banner(title: str, subtitle: str = "") -> None:
    """Print a prominent top-of-run banner."""
    print()
    print(_c(_CYAN + _BOLD, "═" * WIDTH))
    pad = max((WIDTH - len(title)) // 2, 0)
    print(_c(_CYAN + _BOLD, " " * pad + title))
    if subtitle:
        sub_pad = max((WIDTH - len(subtitle)) // 2, 0)
        print(_c(_DIM, " " * sub_pad + subtitle))
    print(_c(_CYAN + _BOLD, "═" * WIDTH))
    print()
    _log(f"# {title}")
    if subtitle:
        _log(f"> {subtitle}")
    _log("")


def section(title: str) -> None:
    """Print a section / phase header with surrounding rules."""
    print()
    print(_c(_BOLD, _rule()))
    print(_c(_BOLD, f"  {title}"))
    print(_c(_BOLD, _rule()))
    _log(f"\n## {title}")
    _log("---")


def divider() -> None:
    """Print a lightweight separator line."""
    print(_c(_DIM, _rule("·")))
    _log("---")


# ──────────────────────────────────────────────────────────────────
# Status / log lines
# ──────────────────────────────────────────────────────────────────

def ok(msg: str) -> None:
    """Success confirmation."""
    print(_c(_GREEN + _BOLD, "  ✓ ") + msg)
    _log(f"✓ {msg}")


def warn(msg: str) -> None:
    """Non-fatal warning."""
    print(_c(_YELLOW + _BOLD, "  ! ") + _c(_YELLOW, msg))
    _log(f"⚠️  {msg}")


def error(msg: str) -> None:
    """Fatal error message."""
    print(_c(_RED + _BOLD, "  ✗ ") + _c(_RED, msg))
    _log(f"✗ {msg}")


def info(msg: str) -> None:
    """Neutral informational line."""
    print("    " + msg)
    _log(f"    {msg}")


def progress(msg: str) -> None:
    """In-progress action indicator."""
    print(_c(_DIM, "  ⋯ ") + _c(_DIM, msg))
    _log(f"⋯ {msg}")


def bullet(label: str, value: str = "") -> None:
    """Print a labelled bullet point."""
    if value:
        print(f"  {_c(_BOLD, '•')} {_c(_BOLD, label)}: {value}")
        _log(f"- **{label}**: {value}")
    else:
        print(f"  {_c(_BOLD, '•')} {label}")
        _log(f"- {label}")


# ──────────────────────────────────────────────────────────────────
# Menus and lists
# ──────────────────────────────────────────────────────────────────

def menu(title: str, options: list[tuple]) -> None:
    """
    Print a formatted numbered menu.

    options: list of (key, label) tuples
    """
    print()
    print(_c(_BOLD, f"  {title}"))
    print(_c(_DIM, "  " + "─" * (WIDTH - 4)))
    for key, label in options:
        print(f"    {_c(_CYAN + _BOLD, str(key))}.  {label}")
    print()


def numbered_list(items: list, name_key: str = "name", id_key: str = "id") -> None:
    """
    Print a numbered list of dicts or plain strings.

    For dicts the name_key field is used as the label, id_key as a dim suffix.
    """
    for idx, item in enumerate(items, start=1):
        if isinstance(item, dict):
            name    = item.get(name_key, "<unnamed>")
            item_id = item.get(id_key)
            suffix  = f"  {_c(_DIM, f'({item_id})')}" if item_id else ""
            print(f"  {_c(_CYAN + _BOLD, str(idx))}.  {name}{suffix}")
        else:
            print(f"  {_c(_CYAN + _BOLD, str(idx))}.  {item}")


def summarize_list(items: list, label: str, name_key: str = "name", max_items: int = 5) -> None:
    """Print a compact bullet summary of a list (used in preflight)."""
    names  = [item.get(name_key, "<unnamed>") if isinstance(item, dict) else str(item) for item in items]
    sample = ", ".join(names[:max_items])
    suffix = f" … (+{len(names) - max_items} more)" if len(names) > max_items else ""
    bullet(label, f"{len(names)}  {sample + suffix}")


# ──────────────────────────────────────────────────────────────────
# Input prompts
# ──────────────────────────────────────────────────────────────────

def ask(label: str, default=None, allow_empty: bool = False) -> str:
    """
    Styled text input prompt.

    Shows a cyan '?' leader, the label, and a dim default hint.
    Returns the entered string (or default when the user presses Enter).
    """
    prompt = _c(_CYAN, "\n  ? ") + _c(_BOLD, label)
    if default is not None:
        prompt += _c(_DIM, f"  [{default}]")
    prompt += "\n    → "
    while True:
        value = input(prompt).strip()
        if not value and default is not None:
            _log(f"> **{label}**: {default} *(default)*")
            return str(default)
        if value or allow_empty:
            _log(f"> **{label}**: {value}")
            return value
        print(warn_str("Value required."))


def ask_yn(label: str, default: bool = True) -> bool:
    """
    Styled yes/no prompt.

    Shows a cyan '?' leader and dim (Y/n) or (y/N) hint.
    Returns True/False.
    """
    hint   = _c(_DIM, " (Y/n)" if default else " (y/N)")
    prompt = _c(_CYAN, "\n  ? ") + _c(_BOLD, label) + hint + "\n    → "
    while True:
        response = input(prompt).strip().lower()
        if not response:
            _log(f"> **{label}**: {'Yes' if default else 'No'} *(default)*")
            return default
        if response in {"y", "yes"}:
            _log(f"> **{label}**: Yes")
            return True
        if response in {"n", "no"}:
            _log(f"> **{label}**: No")
            return False
        print(_c(_YELLOW, "    Please enter y or n."))


# Internal helper so warn() can be called without a side-effect print
# when constructing strings.
def warn_str(msg: str) -> str:
    return _c(_YELLOW + _BOLD, "  ! ") + _c(_YELLOW, msg)
