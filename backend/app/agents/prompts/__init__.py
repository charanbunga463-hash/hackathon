"""Prompt loading.

Prompts live in .txt files next to this module so they can be reviewed and
edited without touching Python. They are cached after first read.
"""

from __future__ import annotations

import functools
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent

KNOWN_PROMPTS = {
    "investigation",
    "diagnosis",
    "patch_generation",
    "patch_review",
    "verification",
    "retry",
}


@functools.lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    path = PROMPT_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt {name!r} not found at {path}")
    return path.read_text(encoding="utf-8").strip()


def available_prompts() -> list[str]:
    return sorted(p.stem for p in PROMPT_DIR.glob("*.txt"))
