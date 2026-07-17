"""启动早期闪屏。

Win32 自定义窗口在部分环境下会 access violation，导致进程直接退出。
默认改为安全空实现；需要时可设 AE_ENABLE_WIN_SPLASH=1 尝试原生闪屏。
"""

from __future__ import annotations

import os
import sys
import threading


class StartupSplash:
    """启动提示。默认无窗口；可选启用 Win32 闪屏。"""

    def __init__(self, text: str = "正在启动，请稍候…") -> None:
        self._text = text
        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._wndproc = None
        self._class_name = ""
        self._brush = None

    def show(self) -> None:
        if sys.platform != "win32":
            return
        if os.environ.get("AE_ENABLE_WIN_SPLASH") != "1":
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_safe, name="StartupSplash", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def set_text(self, text: str) -> None:
        self._text = text
        hwnd = self._hwnd
        if not hwnd:
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            user32.SetWindowTextW(hwnd, text)
            user32.InvalidateRect(hwnd, None, True)
        except Exception:
            pass

    def close(self) -> None:
        self._closed.set()
        hwnd = self._hwnd
        if hwnd:
            try:
                import ctypes

                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._hwnd = None
        self._cleanup_class()

    def _cleanup_class(self) -> None:
        if not self._class_name:
            return
        try:
            import ctypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hinst = kernel32.GetModuleHandleW(None)
            user32.UnregisterClassW(self._class_name, hinst)
        except Exception:
            pass
        if self._brush:
            try:
                import ctypes

                ctypes.windll.gdi32.DeleteObject(self._brush)
            except Exception:
                pass
            self._brush = None

    def _run_safe(self) -> None:
        try:
            self._run()
        except Exception:
            pass
        finally:
            self._ready.set()

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes as wt

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wt.UINT),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE),
                ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR),
            ]

        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hdc", wt.HDC),
                ("fErase", wt.BOOL),
                ("rcPaint", wt.RECT),
                ("fRestore", wt.BOOL),
                ("fIncUpdate", wt.BOOL),
                ("rgbReserved", ctypes.c_char * 32),
            ]

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM
        )

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32
        user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == 0x000F:
                ps = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                rect = wt.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                gdi32.SetBkMode(hdc, 1)
                gdi32.SetTextColor(hdc, 0x00333333)
                user32.DrawTextW(
                    hdc,
                    self._text,
                    -1,
                    ctypes.byref(rect),
                    0x00000001 | 0x00000004 | 0x00000020,
                )
                user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == 0x0010:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == 0x0002:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wnd_proc)
        self._class_name = f"AutomatedEditStartupSplash_{os.getpid()}_{id(self)}"
        hinst = kernel32.GetModuleHandleW(None)
        self._brush = gdi32.CreateSolidBrush(0x00F5F5F5)

        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p).value
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = None
        wc.hCursor = user32.LoadCursorW(None, 32512)
        wc.hbrBackground = self._brush
        wc.lpszMenuName = None
        wc.lpszClassName = self._class_name

        if not user32.RegisterClassW(ctypes.byref(wc)):
            self._ready.set()
            return

        width, height = 360, 140
        x = max(0, (user32.GetSystemMetrics(0) - width) // 2)
        y = max(0, (user32.GetSystemMetrics(1) - height) // 2)
        hwnd = user32.CreateWindowExW(
            0x00000008,
            self._class_name,
            self._text,
            0x80000000 | 0x00800000 | 0x10000000,
            x,
            y,
            width,
            height,
            None,
            None,
            hinst,
            None,
        )
        self._hwnd = hwnd
        self._ready.set()
        if not hwnd:
            return

        user32.ShowWindow(hwnd, 5)
        user32.UpdateWindow(hwnd)
        msg = wt.MSG()
        while not self._closed.is_set():
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self._hwnd = None


_splash: StartupSplash | None = None


def show_startup_splash(text: str = "正在启动，请稍候…") -> StartupSplash:
    global _splash
    close_startup_splash()
    _splash = StartupSplash(text)
    _splash.show()
    return _splash


def close_startup_splash() -> None:
    global _splash
    if _splash is not None:
        _splash.close()
        _splash = None
