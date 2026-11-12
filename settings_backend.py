"""
Ayarlar penceresi (qml/Settings.qml) için Python köprüsü.

Overlay listesini, seçili overlay'in canlı ayarlarını ve genel uygulama
bilgilerini QML'e açar. Tüm değişiklikler anında uygulanır ve config'e yazılır.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from player import CACHE_DIR

AUTOSTART_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "anime-overlay.desktop"

AUTOSTART_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Anime Overlay
Comment=Her pencerenin üstünde duran anime GIF/video overlay'i
Exec={exec_path}
Icon=applications-multimedia
Terminal=false
Categories=Utility;
X-KDE-autostart-after=panel
OnlyShowIn=KDE;
"""


def autostart_enabled() -> bool:
    return AUTOSTART_FILE.is_file()


def set_autostart(enabled: bool) -> bool:
    try:
        if enabled:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            exe = shutil.which("anime-overlay") or str(Path.home() / ".local/bin/anime-overlay")
            AUTOSTART_FILE.write_text(AUTOSTART_TEMPLATE.format(exec_path=exe), encoding="utf-8")
        else:
            AUTOSTART_FILE.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _rss_mb() -> float:
    """Etkin bellek (PSS varsa onu, yoksa RSS'i döndürür)."""
    try:
        for line in Path("/proc/self/smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _dir_size_mb(path: Path) -> float:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except Exception:
        pass
    return total / (1024 * 1024)


class SettingsBackend(QObject):
    """QML tarafındaki `settings` nesnesi."""

    changed = Signal()            # liste / seçili overlay değişti
    previewTickChanged = Signal()  # canlı önizleme karesi
    statsChanged = Signal()

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self._selected = None
        self._tick = 0
        self._stats = ""

        app.frameArrived.connect(self._on_frame)

        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(2000)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()

    # -- yardımcılar ---------------------------------------------------------
    def _overlays(self):
        return self.app.overlays

    def _current(self):
        overlays = self._overlays()
        if not overlays:
            return None
        for ov in overlays:
            if ov.name == self._selected:
                return ov
        ov = overlays[0]
        self._selected = ov.name
        return ov

    def _notify(self):
        self.changed.emit()

    @staticmethod
    def _mode_str(value):
        if value is True:
            return "on"
        if value is False:
            return "off"
        return "auto"

    # -- model ---------------------------------------------------------------
    @Property(list, notify=changed)
    def overlayList(self):
        items = []
        for ov in self._overlays():
            try:
                w, h = ov.player.output_size()
            except Exception:
                w, h = 0, 0
            items.append({
                "name": ov.name,
                "fileName": Path(ov.entry["file"]).name,
                "file": ov.entry["file"],
                "width": w,
                "height": int(ov.entry["height"]),
                "sourceWidth": int(ov.media.get("width", 0)),
                "sourceHeight": int(ov.media.get("height", 0)),
                "paused": bool(ov.paused),
            })
        return items

    @Property(str, notify=changed)
    def currentName(self):
        ov = self._current()
        return ov.name if ov else ""

    @Property(int, notify=changed)
    def currentIndex(self):
        overlays = self._overlays()
        for i, ov in enumerate(overlays):
            if ov.name == self._selected:
                return i
        return 0 if overlays else -1

    @Property(str, notify=changed)
    def currentFile(self):
        ov = self._current()
        return Path(ov.entry["file"]).name if ov else ""

    @Property(str, notify=changed)
    def currentFilePath(self):
        ov = self._current()
        return ov.entry["file"] if ov else ""

    @Property(int, notify=changed)
    def currentHeight(self):
        ov = self._current()
        return int(ov.entry["height"]) if ov else 320

    @Property(int, notify=changed)
    def currentOpacity(self):
        ov = self._current()
        return round(float(ov.entry["opacity"]) * 100) if ov else 100

    @Property(int, notify=changed)
    def currentSpeed(self):
        ov = self._current()
        return round(float(ov.entry["speed"]) * 100) if ov else 100

    @Property(int, notify=changed)
    def currentFps(self):
        ov = self._current()
        return int(ov.entry.get("max_fps", 15)) if ov else 15

    @Property(int, notify=changed)
    def currentX(self):
        ov = self._current()
        return int(ov.entry["x"] or 0) if ov else 0

    @Property(int, notify=changed)
    def currentY(self):
        ov = self._current()
        return int(ov.entry["y"] or 0) if ov else 0

    @Property(bool, notify=changed)
    def currentPaused(self):
        ov = self._current()
        return bool(ov.paused) if ov else False

    @Property(str, notify=changed)
    def currentRemoveWhite(self):
        ov = self._current()
        return self._mode_str(ov.entry.get("remove_white", "auto")) if ov else "auto"

    @Property(list, notify=changed)
    def screens(self):
        return [s.name() for s in self.app.qapp.screens()]

    @Property(int, notify=changed)
    def currentScreenIndex(self):
        ov = self._current()
        names = [s.name() for s in self.app.qapp.screens()]
        if ov is None or ov.screen is None:
            return 0
        try:
            return max(0, names.index(ov.screen.name()))
        except ValueError:
            return 0

    @Property(int, notify=previewTickChanged)
    def previewTick(self):
        return self._tick

    @Property(bool, notify=statsChanged)
    def autostart(self):
        return autostart_enabled()

    @Property(str, notify=statsChanged)
    def stats(self):
        return self._stats

    # -- iç olaylar ----------------------------------------------------------
    def _on_frame(self, name: str):
        ov = self._current()
        if ov is not None and ov.name == name:
            self._tick = (self._tick + 1) % 1000000
            self.previewTickChanged.emit()

    def _update_stats(self):
        if not self.app.settings_visible():
            return
        count = len(self._overlays())
        text = (
            f"{count} overlay · uygulama {_rss_mb():.0f} MB etkin RAM · "
            f"önbellek {_dir_size_mb(CACHE_DIR):.1f} MB"
        )
        if text != self._stats:
            self._stats = text
            self.statsChanged.emit()

    # -- eylemler ------------------------------------------------------------
    @Slot(int)
    def select(self, index: int):
        overlays = self._overlays()
        if 0 <= index < len(overlays):
            self._selected = overlays[index].name
            self._notify()

    @Slot()
    def add(self):
        self.app.add_overlay_dialog()
        overlays = self._overlays()
        if overlays:
            self._selected = overlays[-1].name
        self._notify()

    @Slot()
    def remove(self):
        ov = self._current()
        if ov is None:
            return
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            None,
            "Overlay'i kaldır",
            f"“{ov.name}” listeden kaldırılsın mı?\n\nDosya diskten silinmez.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._selected = None
        self.app.remove_overlay(ov)
        self._notify()

    @Slot()
    def chooseFile(self):
        from PySide6.QtWidgets import QFileDialog

        ov = self._current()
        if ov is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            None, f"{ov.name} için animasyon seç", str(Path.home()), self.app.FILE_FILTER
        )
        if path:
            ov.set_file(path)
            self._notify()

    @Slot(int)
    def setHeight(self, value: int):
        ov = self._current()
        if ov is not None:
            ov.set_height_value(value)
            self._notify()

    @Slot(int)
    def setOpacity(self, percent: int):
        ov = self._current()
        if ov is not None:
            ov.set_opacity_value(percent / 100.0)
            self._notify()

    @Slot(int)
    def setSpeed(self, percent: int):
        ov = self._current()
        if ov is not None:
            ov.set_speed_value(percent / 100.0)
            self._notify()

    @Slot(int)
    def setFps(self, value: int):
        ov = self._current()
        if ov is not None:
            ov.set_max_fps_value(value)
            self._notify()

    @Slot(int, int)
    def setPosition(self, x: int, y: int):
        ov = self._current()
        if ov is not None:
            ov.set_position(x, y)
            self._notify()

    @Slot(int)
    def setScreenIndex(self, index: int):
        ov = self._current()
        if ov is None:
            return
        screens = self.app.qapp.screens()
        if 0 <= index < len(screens):
            ov.set_screen_name(screens[index].name())
            self._notify()

    @Slot(str)
    def setRemoveWhite(self, mode: str):
        ov = self._current()
        if ov is None:
            return
        value = {"on": True, "off": False}.get(mode, "auto")
        ov.set_remove_white(value)
        self._notify()

    @Slot()
    def togglePause(self):
        ov = self._current()
        if ov is not None:
            ov.set_paused(not ov.paused)
            self._notify()

    @Slot()
    def locate(self):
        self.app.locate_current(self._current())

    @Slot()
    def clearCache(self):
        self.app.clear_cache()
        self._notify()

    @Slot(bool)
    def setAutostart(self, enabled: bool):
        set_autostart(bool(enabled))
        self.statsChanged.emit()

    @Slot()
    def closeWindow(self):
        self.app.close_settings()
