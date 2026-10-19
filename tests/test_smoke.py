import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.main import greet  # noqa: E402


def test_greet():
    assert greet("world") == "hello, world"


def test_main_importable():
    import src.main as m

    assert callable(m.main)