"""Which UI element was clicked or typed into (Windows UI Automation).

The accessibility tree knows the exact name and type of the control under the pointer
(`Button "New Email"`, `Edit "To"`), which small local vision models would otherwise have to
read from pixels. Lookups run on one background worker thread (COM objects are per-thread),
are requested at the moment of the click (before the UI reacts), and are best-effort with a
time budget: any failure or timeout gives None. On non-Windows systems this is a no-op.
"""

from __future__ import annotations

import sys
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

TIME_BUDGET_S = 0.25
_VALUE_PATTERN_ID = 10002
_CONTROL_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
    50006: "Image", 50007: "ListItem", 50008: "List", 50009: "Menu", 50010: "MenuBar", 50011: "MenuItem",
    50012: "ProgressBar", 50013: "RadioButton", 50014: "ScrollBar", 50015: "Slider", 50016: "Spinner",
    50017: "StatusBar", 50018: "Tab", 50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50022: "ToolTip",
    50023: "Tree", 50024: "TreeItem", 50025: "Custom", 50026: "Group", 50027: "Thumb", 50028: "DataGrid",
    50029: "DataItem", 50030: "Document", 50031: "SplitButton", 50032: "Window", 50033: "Pane", 50034: "Header",
    50035: "HeaderItem", 50036: "Table", 50037: "TitleBar", 50038: "Separator",
}
_GENERIC = {"Pane", "Window", "Custom", "Group", "Control", "Document"}


@dataclass
class Element:
    control: str  # e.g. "Button", "Edit", "MenuItem"
    name: str
    value: str | None = None

    def label(self) -> str:
        name = self.name.replace('"', "'")[:80]
        return f'{self.control} "{name}"' if name else self.control


class Inspector:
    """Asynchronous UI Automation lookups on a dedicated thread."""

    def __init__(self):
        self.enabled = sys.platform == "win32"
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="uia") if self.enabled else None
        self._uia = None
        self._mod = None

    def _client(self):
        if self._uia is None:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen import UIAutomationClient as mod

            self._mod = mod
            self._uia = comtypes.client.CreateObject(mod.CUIAutomation, interface=mod.IUIAutomation)
        return self._uia

    def _describe(self, el) -> Element | None:
        control = _CONTROL_TYPES.get(el.CurrentControlType, "Control")
        name = (el.CurrentName or "").strip()
        value = None
        try:
            pattern = el.GetCurrentPattern(_VALUE_PATTERN_ID)
            if pattern:
                value = pattern.QueryInterface(self._mod.IUIAutomationValuePattern).CurrentValue
        except Exception:
            value = None
        if not name and not value and control in _GENERIC:
            return None  # too generic to help
        return Element(control, name[:120], str(value)[:300] if value else None)

    def _submit(self, fn) -> Future | None:
        if not self.enabled:
            return None

        def safe():
            try:
                return fn()
            except Exception:
                return None

        return self._pool.submit(safe)

    def at(self, x: int, y: int) -> Future | None:
        """Element at screen coordinates (x, y); request it as soon as the click happens."""
        from ctypes.wintypes import POINT

        return self._submit(lambda: self._describe(self._client().ElementFromPoint(POINT(int(x), int(y)))))

    def focused(self) -> Future | None:
        """Element with keyboard focus (e.g. the field just typed into, with its value)."""
        return self._submit(lambda: self._describe(self._client().GetFocusedElement()))

    def warm_up(self) -> None:
        """Load the COM type library in the background (about 1 s the first time)."""
        self._submit(self._client)

    def shutdown(self) -> None:
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)


def result(fut: Future | None, budget: float = TIME_BUDGET_S) -> Element | None:
    if fut is None:
        return None
    try:
        return fut.result(timeout=budget)
    except (FutureTimeout, Exception):
        return None


