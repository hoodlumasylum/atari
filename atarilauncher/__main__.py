"""Entry point: python -m atarilauncher"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="atari", description="Atari - a console-style game launcher")
    ap.add_argument("--windowed", action="store_true", help="run in a normal window instead of full screen")
    ap.add_argument("--fullscreen", action="store_true", help="force full screen")
    ap.add_argument("--demo", action="store_true", help="show made-up demo games (used for screenshots)")
    ap.add_argument("--screenshot", metavar="PNG", help="save a screenshot after start-up and exit")
    ap.add_argument("--screenshot-keys", default="", help="comma-separated actions to press before the shot")
    ap.add_argument("--size", default="", help="window size WIDTHxHEIGHT (windowed mode)")
    ap.add_argument("--selftest", action="store_true", help="start, load the UI, then exit 0 (for testing)")
    ap.add_argument("--version", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.version:
        from . import __version__
        print(f"atari {__version__}")
        return 0

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow  # noqa: F401  (makes grabWindow available)

    from .backend import Backend

    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Atari")
    app.setDesktopFileName("atari")
    headless = args.screenshot or args.selftest
    backend = Backend(demo=args.demo, enable_gamepad=not headless)
    if args.windowed:
        backend.cfg.fullscreen = False
    if args.fullscreen:
        backend.cfg.fullscreen = True

    engine = QQmlApplicationEngine()
    errors: list[str] = []
    engine.warnings.connect(lambda ws: errors.extend(w.toString() for w in ws))
    engine.rootContext().setContextProperty("backend", backend)
    qml = Path(__file__).parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        print("[atari] could not load the user interface:\n" + "\n".join(errors), file=sys.stderr)
        return 1
    window = engine.rootObjects()[0]
    backend.set_window(window)
    if args.size:
        try:
            w, h = (int(x) for x in args.size.lower().split("x"))
            window.setWidth(w)
            window.setHeight(h)
        except ValueError:
            pass
    app.aboutToQuit.connect(backend.stop_gamepad)

    if args.selftest or args.screenshot:
        def finish():
            if args.screenshot:
                img = window.grabWindow()
                Path(args.screenshot).parent.mkdir(parents=True, exist_ok=True)
                if not img.save(args.screenshot):
                    print("[atari] could not save screenshot", file=sys.stderr)
            if errors:
                print("[atari] QML warnings:\n" + "\n".join(errors), file=sys.stderr)
            app.exit(1 if errors else 0)

        def press_keys():
            os.environ["ATARI_TEST_INPUT"] = "1"
            for action in [a for a in args.screenshot_keys.split(",") if a]:
                backend.send_action(action)
            QTimer.singleShot(800, finish)

        QTimer.singleShot(1200, press_keys)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
