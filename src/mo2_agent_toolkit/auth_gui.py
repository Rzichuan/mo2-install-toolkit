from __future__ import annotations

import ctypes
import os
import threading
from webbrowser import open_new_tab as launch_browser
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from .auth import AuthError, validate_and_save

API_PAGE = "https://www.nexusmods.com/users/myaccount?tab=api"
WM_APP_AUTH_DONE = 0x8001
IDC_KEY = 101
IDC_SHOW = 102
IDC_SAVE = 103
IDC_CANCEL = 104
IDC_LINK = 105
IDC_STATUS = 106
IDC_PROGRESS = 107
WM_SETFONT = 0x0030
PBM_SETMARQUEE = 0x040A

# HCURSOR is an alias for HANDLE. Some supported Python/ctypes builds do not
# expose the alias in ctypes.wintypes (notably frozen runtimes), so do not
# import it unconditionally at GUI startup.
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)


@dataclass(frozen=True)
class GuiResult:
    status: str
    configured: bool
    error: AuthError | None = None


def run_auth_gui(secret_path: Path) -> GuiResult:
    if os.name != "nt":
        return GuiResult("error", secret_path.exists(), AuthError(
            "The Nexus credential GUI is only supported on Windows", 3, "unsupported_platform"
        ))

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPCVOID, wintypes.DWORD]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    except OSError:
        dwmapi = None
    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    # ctypes defaults undeclared DLL calls to 32-bit c_int. Every pointer-sized
    # Win32 boundary must be declared explicitly on 64-bit Windows.
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.SetWindowTextW.restype = wintypes.BOOL
    user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.EnableWindow.restype = wintypes.BOOL
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
    user32.InvalidateRect.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    gdi32.GetStockObject.argtypes = [ctypes.c_int]
    gdi32.GetStockObject.restype = wintypes.HANDLE
    gdi32.CreateFontW.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
    ]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadCursorW.restype = HCURSOR
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.IsDialogMessageW.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.MSG)]
    user32.IsDialogMessageW.restype = wintypes.BOOL
    handles: dict[str, int] = {}
    fonts: list[int] = []
    font_roles: dict[str, int] = {}
    control_layouts: list[tuple[int, int, int, int, int, str]] = []
    state: dict[str, object] = {"result": GuiResult("cancelled", secret_path.exists())}

    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass

    try:
        user32.GetDpiForSystem.argtypes = []
        user32.GetDpiForSystem.restype = wintypes.UINT
        dpi = max(96, int(user32.GetDpiForSystem()))
    except (AttributeError, OSError):
        dpi = 96

    def scale(value: int, target_dpi: int | None = None) -> int:
        return max(1, (value * (target_dpi or dpi) + 48) // 96)

    def text(hwnd: int, value: str) -> None:
        user32.SetWindowTextW(hwnd, value)

    def make_font(size: int, weight: int = 400) -> int:
        font = gdi32.CreateFontW(-scale(size), 0, 0, 0, weight, False, False, False, 1, 0, 0, 5, 0, "Segoe UI")
        fonts.append(font)
        return font

    font_roles.update({
        "body": make_font(16),
        "title": make_font(25, 600),
        "small": make_font(14),
    })

    def create(kind: str, label: str, style: int, x: int, y: int, width: int, height: int,
               control_id: int = 0, font: int | None = None, ex_style: int = 0) -> int:
        selected_font = font or font_roles["body"]
        role = next((name for name, handle in font_roles.items() if handle == selected_font), "body")
        hwnd = user32.CreateWindowExW(
            ex_style, kind, label, style, scale(x), scale(y), scale(width), scale(height),
            handles["window"], wintypes.HMENU(control_id), None, None,
        )
        user32.SendMessageW(hwnd, WM_SETFONT, selected_font, True)
        control_layouts.append((hwnd, x, y, width, height, role))
        return hwnd

    def finish_validation(error: AuthError | None) -> None:
        user32.EnableWindow(handles["save"], True)
        user32.EnableWindow(handles["key"], True)
        user32.ShowWindow(handles["progress"], 0)
        user32.SendMessageW(handles["progress"], PBM_SETMARQUEE, False, 0)
        if error is None:
            user32.SetWindowTextW(handles["key"], "")
            state["result"] = GuiResult("success", True)
            user32.DestroyWindow(handles["window"])
        else:
            state["pending_error"] = error
            text(handles["status"], str(error))
            user32.SetFocus(handles["key"])

    @WNDPROC
    def window_proc(hwnd: int, message: int, wparam: int, lparam: int) -> int:
        nonlocal dpi
        if message == 0x02E0:  # WM_DPICHANGED
            new_dpi = max(96, int(wparam & 0xFFFF))
            suggested = ctypes.cast(lparam, ctypes.POINTER(wintypes.RECT)).contents
            dpi = new_dpi
            user32.SetWindowPos(
                hwnd, None, suggested.left, suggested.top,
                suggested.right - suggested.left, suggested.bottom - suggested.top,
                0x0004 | 0x0010,
            )
            old_fonts = list(font_roles.values())
            font_roles.update({
                "body": make_font(16),
                "title": make_font(25, 600),
                "small": make_font(14),
            })
            for control, x, y, width, height, role in control_layouts:
                user32.SetWindowPos(control, None, scale(x), scale(y), scale(width), scale(height), 0x0004 | 0x0010)
                user32.SendMessageW(control, WM_SETFONT, font_roles[role], True)
            for old_font in old_fonts:
                if old_font in fonts:
                    fonts.remove(old_font)
                gdi32.DeleteObject(old_font)
            user32.InvalidateRect(hwnd, None, True)
            return 0
        if message == 0x0002:  # WM_DESTROY
            for font in fonts:
                if font:
                    gdi32.DeleteObject(font)
            user32.PostQuitMessage(0)
            return 0
        if message == WM_APP_AUTH_DONE:
            finish_validation(state.pop("worker_error", None))
            return 0
        if message == 0x0010:  # WM_CLOSE
            user32.DestroyWindow(hwnd)
            return 0
        if message == 0x0111:  # WM_COMMAND
            control_id = wparam & 0xFFFF
            if control_id == IDC_CANCEL:
                user32.DestroyWindow(hwnd)
                return 0
            if control_id == IDC_LINK:
                launch_browser(API_PAGE)
                return 0
            if control_id == IDC_SHOW:
                checked = user32.SendMessageW(handles["show"], 0x00F0, 0, 0) == 1
                user32.SendMessageW(handles["key"], 0x00CC, 0 if checked else ord("●"), 0)
                user32.InvalidateRect(handles["key"], None, True)
                return 0
            if control_id == IDC_SAVE:
                length = user32.GetWindowTextLengthW(handles["key"])
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(handles["key"], buffer, len(buffer))
                key = buffer.value
                if not key.strip():
                    text(handles["status"], "请输入 Nexus API Key。")
                    return 0
                user32.EnableWindow(handles["save"], False)
                user32.EnableWindow(handles["key"], False)
                text(handles["status"], "正在安全连接 Nexus 并验证密钥……")
                user32.ShowWindow(handles["progress"], 5)
                user32.SendMessageW(handles["progress"], PBM_SETMARQUEE, True, 30)

                def worker(value: str) -> None:
                    try:
                        validate_and_save(value, secret_path)
                        state["worker_error"] = None
                    except AuthError as exc:
                        state["worker_error"] = exc
                    except Exception:
                        state["worker_error"] = AuthError("Unexpected authentication error", 10, "internal_error")
                    finally:
                        value = ""
                        user32.PostMessageW(hwnd, WM_APP_AUTH_DONE, 0, 0)

                threading.Thread(target=worker, args=(key,), daemon=True).start()
                key = ""
                return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    instance = kernel32.GetModuleHandleW(None)
    class_name = "MO2AgentToolkitAuthWindow"
    wc = WNDCLASSW(0, window_proc, 0, 0, instance, None, user32.LoadCursorW(None, ctypes.cast(ctypes.c_void_p(32512), wintypes.LPCWSTR)), 16, None, class_name)
    user32.RegisterClassW(ctypes.byref(wc))

    window_width, window_height = scale(660), scale(430)
    screen_width = user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(1)
    x = max(0, (screen_width - window_width) // 2)
    y = max(0, (screen_height - window_height) // 2)
    style = 0x00C00000 | 0x00080000 | 0x00020000 | 0x10000000
    handles["window"] = user32.CreateWindowExW(
        0, class_name, "MO2 Agent Toolkit — Nexus API Key", style,
        x, y, window_width, window_height, None, None, instance, None,
    )
    if not handles["window"]:
        return GuiResult("error", secret_path.exists(), AuthError(
            "Could not create the authentication window", 5, "gui_error"
        ))

    # Enable immersive title-bar styling where supported; failure is harmless.
    try:
        value = ctypes.c_int(0)
        dwmapi.DwmSetWindowAttribute(handles["window"], 20, ctypes.byref(value), ctypes.sizeof(value)) if dwmapi is not None else None
    except (AttributeError, OSError):
        pass

    static = 0x50000000
    create("STATIC", "连接 Nexus Mods", static, 30, 24, 580, 38, font=font_roles["title"])
    create(
        "STATIC",
        "输入你的个人 API Key。验证成功后，密钥将使用 Windows 当前用户加密保存，\n"
        "不会出现在聊天、命令行、配置文件或 Agent 输出中。",
        static, 30, 70, 590, 48, font=font_roles["small"],
    )
    create("STATIC", "Nexus API Key", static, 30, 136, 180, 24, font=font_roles["body"])
    handles["key"] = create("EDIT", "", 0x50310020, 30, 164, 590, 36, IDC_KEY, ex_style=0x00000200)
    user32.SendMessageW(handles["key"], 0x00CC, ord("●"), 0)
    handles["show"] = create("BUTTON", "显示 API Key", 0x50010003, 30, 210, 150, 28, IDC_SHOW, font=font_roles["small"])
    create("BUTTON", "获取 Nexus API Key  ↗", 0x50010000, 420, 207, 200, 32, IDC_LINK, font=font_roles["small"])

    handles["status"] = create(
        "STATIC", "密钥需要联网验证。现有密钥只会在新密钥保存成功后被替换。",
        static, 30, 258, 590, 42, IDC_STATUS, font=font_roles["small"],
    )
    handles["progress"] = create("msctls_progress32", "", 0x40000008, 30, 302, 590, 5, IDC_PROGRESS)
    user32.ShowWindow(handles["progress"], 0)

    handles["save"] = create("BUTTON", "验证并保存", 0x50010001, 350, 336, 130, 38, IDC_SAVE)
    create("BUTTON", "取消", 0x50010000, 490, 336, 130, 38, IDC_CANCEL)

    user32.ShowWindow(handles["window"], 5)
    user32.UpdateWindow(handles["window"])
    user32.SetFocus(handles["key"])
    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        if not user32.IsDialogMessageW(handles["window"], ctypes.byref(message)):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
    return state["result"]
