"""Test bootstrap.

custom_components/tesira/__init__.py imports Home Assistant, which we don't
want as a dependency for the plain protocol-parsing unit tests. Load
const.py and client.py directly under a synthetic package name so their
relative imports resolve without ever executing the real __init__.py.
"""
import importlib.util
import sys
import types
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "tesira"
_PKG_NAME = "tesira_under_test"

if _PKG_NAME not in sys.modules:
    pkg = types.ModuleType(_PKG_NAME)
    pkg.__path__ = [str(_PKG_DIR)]
    sys.modules[_PKG_NAME] = pkg

    for module_name in ("const", "client"):
        spec = importlib.util.spec_from_file_location(
            f"{_PKG_NAME}.{module_name}", _PKG_DIR / f"{module_name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        module.__package__ = _PKG_NAME
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
