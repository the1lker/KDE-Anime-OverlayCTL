#!/usr/bin/env python3
"""
anime-overlay — KDE Plasma (Wayland) üzerinde her pencerenin üstünde duran,
tıklamaları geçiren GIF / WebP / video overlay'i.

  anime-overlay              uygulamayı çalıştır
  anime-overlay ctl settings ayarlar penceresini aç
  anime-overlay ctl toggle   göster/gizle
  anime-overlay ctl move     konumlandırma modu
  anime-overlay ctl reload   config'i yeniden yükle
  anime-overlay ctl quit     çık
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

from PySide6.QtCore import QMargins, QObject, QTimer, Qt, QUrl, Slot, Signal, QFileSystemWatcher
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from player import FfmpegPlayer, FrameStore, prepare_media, prune_cache
from settings_backend import SettingsBackend

APP_DIR = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "anime-overlay"
CONFIG_PATH = CONFIG_DIR / "config.toml"
QML_PATH = APP_DIR / "qml" / "Overlay.qml"
SETTINGS_QML_PATH = APP_DIR / "qml" / "Settings.qml"
SOCKET_NAME = f"anime-overlay-{os.getuid()}"

FILE_FILTER = (
    "Animasyonlar (*.gif *.webp *.apng *.png *.mp4 *.webm *.mkv *.mov *.m4v);;"
    "Tüm dosyalar (*)"
)

HEADER = """\
# anime-overlay yapılandırması
#
# Bu dosya uygulama tarafından yönetilir: konum, boyut ve opaklık değişiklikleri
# buraya yazılır. Elle de düzenleyebilirsin; kaydettiğinde uygulama otomatik
# yeniden yükler (uygulama açıkken düzenlersen birkaç saniye içinde uygulanır).
#
# [[overlay]] başına ayarlar:
#   file         = animasyon dosyası (gif/webp/mp4/webm/...)
#   x, y         = sol üst köşe (mantıksal piksel); boş bırakılırsa sağ alt
#   height       = yükseklik (piksel)
#   opacity      = 0.0 - 1.0
#   speed        = oynatma hızı (1.0 normal)
#   max_fps      = saniyedeki en fazla kare (varsayılan 15; oyunlarda CPU'yu azaltır)
#   screen       = ekran adı (kscreen-doctor -o ile bakılır), boşsa birincil
#   remove_white = "auto" | true | false  (beyaz arka planı sil)
"""


# --------------------------------------------------------------------------- #
# yardımcılar
# --------------------------------------------------------------------------- #

def expand(path: str) -> str:
    return str(Path(path).expanduser())


def parse_remove_white(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "yes", "1", "on"):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "no", "0", "off"):
        return False
    return "auto"


def load_config() -> list[dict]:
    if not CONFIG_PATH.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(HEADER)
        return []
    data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    entries = []
    for i, e in enumerate(data.get("overlay") or []):
        if not e.get("file"):
            continue
        entries.append({
            "name": str(e.get("name") or f"overlay{i + 1}"),
            "file": expand(str(e["file"])),
            "x": e.get("x"),
            "y": e.get("y"),
            "height": int(e.get("height", 320)),
            "opacity": max(0.0, min(1.0, float(e.get("opacity", 1.0)))),
            "speed": max(0.1, min(8.0, float(e.get("speed", 1.0)))),
            "max_fps": max(1, min(60, int(e.get("max_fps", 15)))),
            "screen": e.get("screen") or None,
            "remove_white": parse_remove_white(e.get("remove_white", "auto")),
        })
    return entries


def _toml_str(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_toml(entries: list[dict]) -> str:
    out = [HEADER]
    for e in entries:
        out.append("[[overlay]]")
        out.append(f"name = {_toml_str(e['name'])}")
        out.append(f"file = {_toml_str(e['file'])}")
        out.append(f"x = {int(e['x'])}")
        out.append(f"y = {int(e['y'])}")
        out.append(f"height = {int(e['height'])}")
        out.append(f"opacity = {float(e['opacity']):.2f}")
        out.append(f"speed = {float(e['speed']):.2f}")
        out.append(f"max_fps = {int(e.get('max_fps', 15))}")
        if e.get("screen"):
            out.append(f"screen = {_toml_str(e['screen'])}")
        rw = e.get("remove_white", "auto")
        out.append(f"remove_white = {str(rw).lower() if isinstance(rw, bool) else _toml_str(rw)}")
        out.append("")
    return "\n".join(out)


def make_icon() -> QIcon:
    for name in ("applications-multimedia", "video-x-generic", "multimedia-player"):
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#59f7c8"))
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("#101418"))
    f = QFont()
    f.setPixelSize(40)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignCenter, "♪")
    p.end()
    return QIcon(pix)


class Geo(QObject):
    """QML için QMargins üretir (Qt.margins QML'de yok)."""

    @Slot(int, int, result=QMargins)
    def margins(self, x: int, y: int) -> QMargins:
        return QMargins(int(x), int(y), 0, 0)


# --------------------------------------------------------------------------- #
# Overlay
# --------------------------------------------------------------------------- #

class Overlay:
    def __init__(self, app: "AnimeOverlay", entry: dict, index: int):
        self.app = app
        self.entry = entry
        self.name = entry["name"]
        self.index = index
        self.tick = 0
        self.window = None
        self.edit = False
        self.visible = True
        self.last_image = None
        self._apply_timer = None

        self.screen = app.pick_screen(entry.get("screen"))
        self.media = prepare_media(
            entry["file"],
            remove_white=entry.get("remove_white", "auto"),
        )
        self.player = FfmpegPlayer(
            self.name, self.media, entry["height"], entry["speed"],
            max_fps=int(entry.get("max_fps", 15)),
        )
        self.player.frameReady.connect(self._on_frame)
        self.player.failed.connect(self._on_player_error)
        self.player.start()

        if entry.get("x") is None or entry.get("y") is None:
            self._default_position()

        self._build_window()

    # -- konum --------------------------------------------------------------
    def _default_position(self):
        geo = self.screen.availableGeometry()
        w, h = self.player.output_size()
        step = self.index * 36
        self.entry["x"] = geo.x() + geo.width() - w - 40 - step
        self.entry["y"] = geo.y() + geo.height() - h - 40 - step

    def _clamp_position(self):
        geo = self.screen.availableGeometry()
        w, h = self.player.output_size()
        self.entry["x"] = max(geo.x() - w + 32, min(int(self.entry["x"]), geo.x() + geo.width() - 32))
        self.entry["y"] = max(geo.y(), min(int(self.entry["y"]), geo.y() + geo.height() - 32))

    # -- pencere ------------------------------------------------------------
    def _build_window(self):
        if self.window is not None:
            try:
                self.window.setProperty("visible", False)
                self.window.deleteLater()
            except RuntimeError:
                pass
            self.window = None

        self._clamp_position()
        w, h = self.player.output_size()
        props = {
            "mediaName": self.name,
            "mediaKey": self.name,
            "frameTick": self.tick,
            "winX": int(self.entry["x"]),
            "winY": int(self.entry["y"]),
            "winWidth": int(w),
            "winHeight": int(h),
            "overlayOpacity": float(self.entry["opacity"]),
            "editMode": bool(self.edit),
        }
        obj = self.app.component.createWithInitialProperties(props)
        if obj is None:
            self.app.notify("Overlay hatası", self.app.component.errorString()[:400])
            return
        try:
            obj.setScreen(self.screen)
        except Exception:
            pass
        if self.visible:
            obj.setProperty("visible", True)
        self.window = obj

    def _resize_window(self):
        w, h = self.player.output_size()
        if self.window is not None:
            self.window.setProperty("winWidth", int(w))
            self.window.setProperty("winHeight", int(h))

    # -- oynatma ------------------------------------------------------------
    def _on_frame(self, key: str, image):
        self.app.frames.set_frame(key, image)
        self.last_image = image
        if self.window is not None:
            self.tick = (self.tick + 1) % 1000000
            self.window.setProperty("frameTick", self.tick)
        self.app.frameArrived.emit(self.name)

    def _on_player_error(self, message: str):
        self.app.notify(f"{self.name}: oynatma hatası", message or "bilinmeyen hata")

    # -- eylemler -----------------------------------------------------------
    def set_edit(self, edit: bool):
        if self.edit == edit:
            return
        self.edit = edit
        self._build_window()

    def save_position_from_window(self):
        if self.window is not None:
            self.entry["x"] = int(self.window.property("winX"))
            self.entry["y"] = int(self.window.property("winY"))
            self._clamp_position()

    def change_height(self, delta: int):
        self.set_height_value(int(self.entry["height"]) + delta)

    def change_opacity(self, delta: float):
        self.set_opacity_value(float(self.entry["opacity"]) + delta)

    def change_speed(self, delta: float):
        self.set_speed_value(float(self.entry["speed"]) + delta)

    # -- ayar penceresinden gelen değerler ----------------------------------
    def _apply_soon(self):
        """Boyut/hız/fps değişimlerini 220 ms sonra tek seferde uygular."""
        if self._apply_timer is None:
            self._apply_timer = QTimer(self.app)
            self._apply_timer.setSingleShot(True)
            self._apply_timer.setInterval(220)
            self._apply_timer.timeout.connect(self._apply_pending)
        self._apply_timer.start()

    def _apply_pending(self):
        self.player.configure(
            height=self.entry["height"],
            speed=self.entry["speed"],
            max_fps=self.entry["max_fps"],
        )
        self._resize_window()

    def set_height_value(self, height):
        limit = max(120, int(self.media["height"]) * 4)
        self.entry["height"] = max(48, min(int(height), limit))
        self._apply_soon()
        self.app.write_config()

    def set_opacity_value(self, opacity):
        value = round(max(0.05, min(1.0, float(opacity))), 2)
        self.entry["opacity"] = value
        if self.window is not None:
            self.window.setProperty("overlayOpacity", value)
        self.app.write_config()

    def set_speed_value(self, speed):
        value = round(max(0.1, min(8.0, float(speed))), 2)
        self.entry["speed"] = value
        self._apply_soon()
        self.app.write_config()

    def set_max_fps_value(self, fps):
        self.entry["max_fps"] = max(1, min(60, int(fps)))
        self._apply_soon()
        self.app.write_config()

    def set_screen_name(self, name):
        self.entry["screen"] = name or None
        self.screen = self.app.pick_screen(name)
        self._build_window()
        self.app.write_config()

    def set_position(self, x, y):
        self.entry["x"] = int(x)
        self.entry["y"] = int(y)
        self._clamp_position()
        if self.window is not None:
            self.window.setProperty("winX", int(self.entry["x"]))
            self.window.setProperty("winY", int(self.entry["y"]))
        self.app.write_config()

    def set_paused(self, paused: bool):
        if paused:
            self.player.pause()
        else:
            self.player.resume()
        self.app.settings_changed()

    def toggle_pause(self):
        self.set_paused(not self.player.paused)

    @property
    def paused(self) -> bool:
        return self.player.paused

    def set_visible(self, visible: bool):
        self.visible = visible
        if self.window is not None:
            self.window.setProperty("visible", visible)
        if visible:
            self.player.resume()
        else:
            self.player.pause()

    # -- dosya / medya -------------------------------------------------------
    def _load_media(self, path: str | None = None, mode=None) -> bool:
        path = path or self.entry["file"]
        if mode is None:
            mode = self.entry.get("remove_white", "auto")
        self.app.notify("Hazırlanıyor", Path(path).name)
        QApplication.processEvents()
        try:
            media = prepare_media(path, remove_white=mode)
        except Exception as exc:
            self.app.notify("Dönüştürme hatası", str(exc)[:400])
            return False
        self.media = media
        self.entry["file"] = str(Path(path).resolve())
        self.entry["remove_white"] = mode
        self.player.stop()
        self.player.deleteLater()
        self.player = FfmpegPlayer(
            self.name, self.media, self.entry["height"], self.entry["speed"],
            max_fps=int(self.entry.get("max_fps", 15)),
        )
        self.player.frameReady.connect(self._on_frame)
        self.player.failed.connect(self._on_player_error)
        self.player.start()
        self._resize_window()
        self.app.write_config()
        return True

    def set_file(self, path: str):
        if path:
            self._load_media(path)

    def set_remove_white(self, mode):
        self._load_media(mode=mode)

    def select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            None, f"{self.name} için animasyon seç", str(Path.home()), FILE_FILTER
        )
        self.set_file(path)

    def destroy(self):
        try:
            self.player.stop()
        except Exception:
            pass
        if self.window is not None:
            try:
                self.window.setProperty("visible", False)
                self.window.deleteLater()
            except RuntimeError:
                pass
            self.window = None


# --------------------------------------------------------------------------- #
# Uygulama
# --------------------------------------------------------------------------- #

class AnimeOverlay(QObject):
    frameArrived = Signal(str)   # bir overlay yeni kare üretti
    dataChanged = Signal()       # overlay/ayar verisi değişti

    def __init__(self, argv):
        super().__init__()
        self.qapp = QApplication(argv)
        self.qapp.setApplicationName("anime-overlay")
        self.qapp.setApplicationDisplayName("Anime Overlay")
        self.qapp.setDesktopFileName("anime-overlay")
        self.qapp.setQuitOnLastWindowClosed(False)

        self.engine = QQmlApplicationEngine()
        self.engine.addImportPath("/usr/lib/qt6/qml")
        self.frames = FrameStore()
        self.engine.addImageProvider("frames", self.frames)
        self.geo = Geo()
        self.engine.rootContext().setContextProperty("geo", self.geo)
        self.engine.rootContext().setContextProperty("backend", self)

        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(QML_PATH)))

        self.overlays: list[Overlay] = []
        self.hidden = False
        self.edit_mode = False
        self._written: str | None = None
        self._save_timer = None
        self._return_to_settings = False

        self.settings = SettingsBackend(self)
        self.engine.rootContext().setContextProperty("settings", self.settings)
        self.dataChanged.connect(lambda: self.settings.changed.emit())
        self.settings_component = None
        self.settings_window = None

        had_config = CONFIG_PATH.exists()

        self._build_tray()
        self._start_ipc()

        self.watcher = QFileSystemWatcher([str(CONFIG_PATH)], self)
        self.watcher.fileChanged.connect(self._on_config_file_changed)

        QTimer.singleShot(0, self.reload_all)
        if not had_config or os.environ.get("ANIME_OVERLAY_OPEN_SETTINGS") == "1":
            QTimer.singleShot(900, self.open_settings)

    # -- tepsi --------------------------------------------------------------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_icon(), self.qapp)
        self.tray.setToolTip("Anime Overlay")
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._rebuild_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _rebuild_menu(self):
        self.menu.clear()

        title = QAction("Anime Overlay", self.menu)
        title.setEnabled(False)
        self.menu.addAction(title)
        self.menu.addSeparator()

        for overlay in self.overlays:
            sub = QMenu(f"{overlay.name}  ({overlay.media['width']}×{overlay.media['height']})", self.menu)
            sub.setIcon(make_icon())

            act = sub.addAction("Dosya seç…")
            act.triggered.connect(overlay.select_file)

            info = sub.addAction(f"Boyut: {overlay.entry['height']} px")
            info.setEnabled(False)

            sub.addAction("Boyut +20 px").triggered.connect(lambda _=False, o=overlay: o.change_height(20))
            sub.addAction("Boyut −20 px").triggered.connect(lambda _=False, o=overlay: o.change_height(-20))
            sub.addAction("Opaklık +10%").triggered.connect(lambda _=False, o=overlay: o.change_opacity(0.1))
            sub.addAction("Opaklık −10%").triggered.connect(lambda _=False, o=overlay: o.change_opacity(-0.1))
            sub.addAction("Hız +0.25×").triggered.connect(lambda _=False, o=overlay: o.change_speed(0.25))
            sub.addAction("Hız −0.25×").triggered.connect(lambda _=False, o=overlay: o.change_speed(-0.25))
            sub.addSeparator()
            sub.addAction("Duraklat / Devam").triggered.connect(overlay.toggle_pause)
            sub.addAction("Kaldır").triggered.connect(lambda _=False, o=overlay: self.remove_overlay(o))

            self.menu.addMenu(sub)

        if not self.overlays:
            empty = QAction("(henüz animasyon yok)", self.menu)
            empty.setEnabled(False)
            self.menu.addAction(empty)

        self.menu.addSeparator()

        prefs = QAction("Ayarlar…", self.menu)
        prefs.triggered.connect(self.open_settings)
        self.menu.addAction(prefs)

        move = QAction("Konumlandır", self.menu)
        move.setCheckable(True)
        move.setChecked(self.edit_mode)
        move.triggered.connect(self.set_edit_mode)
        self.menu.addAction(move)

        hide = QAction("Göster" if self.hidden else "Gizle", self.menu)
        hide.triggered.connect(self.toggle_hidden)
        self.menu.addAction(hide)

        pause = QAction("Tümünü duraklat / devam", self.menu)
        pause.triggered.connect(self.toggle_pause_all)
        self.menu.addAction(pause)

        self.menu.addSeparator()
        add = QAction("Yeni animasyon ekle…", self.menu)
        add.triggered.connect(self.add_overlay_dialog)
        self.menu.addAction(add)

        reload_act = QAction("Yeniden yükle", self.menu)
        reload_act.triggered.connect(self.reload_all)
        self.menu.addAction(reload_act)

        self.menu.addSeparator()
        quit_act = QAction("Çık", self.menu)
        quit_act.triggered.connect(self.quit)
        self.menu.addAction(quit_act)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle_hidden()

    def notify(self, title: str, message: str):
        if self.tray is not None:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 4000)
        print(f"[{title}] {message}", file=sys.stderr)

    # -- overlay yaşam döngüsü ---------------------------------------------
    def reload_all(self):
        for overlay in list(self.overlays):
            overlay.destroy()
        self.overlays = []
        try:
            entries = load_config()
        except Exception as exc:
            self.notify("Config hatası", str(exc)[:400])
            self._rebuild_menu()
            return

        used = set()
        for i, entry in enumerate(entries):
            entry["name"] = self._unique_name(entry["name"], used)
            used.add(entry["name"])
            try:
                overlay = Overlay(self, entry, i)
            except Exception as exc:
                self.notify(f"{entry['name']}: yüklenemedi", str(exc)[:400])
                continue
            self.overlays.append(overlay)
        if self.hidden:
            for overlay in self.overlays:
                overlay.set_visible(False)
        if self.edit_mode:
            for overlay in self.overlays:
                overlay.set_edit(True)
        self._rebuild_menu()
        if self.settings_visible():
            self._set_overlay_windows_visible(False)

    @staticmethod
    def _unique_name(base: str, used: set[str]) -> str:
        name = base or "overlay"
        i = 2
        while name in used:
            name = f"{base}-{i}"
            i += 1
        return name

    def add_overlay_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Animasyon seç", str(Path.home()), FILE_FILTER
        )
        if not path:
            return
        self.add_overlay_file(path)

    def add_overlay_file(self, path: str):
        used = {o.name for o in self.overlays}
        name = self._unique_name(Path(path).stem.replace(" ", "-"), used)
        self.notify("Hazırlanıyor", Path(path).name)
        QApplication.processEvents()
        entry = {
            "name": name,
            "file": str(Path(path).resolve()),
            "x": None,
            "y": None,
            "height": 320,
            "opacity": 1.0,
            "speed": 1.0,
            "max_fps": 15,
            "screen": self.qapp.primaryScreen().name() if self.qapp.primaryScreen() else None,
            "remove_white": "auto",
        }
        try:
            overlay = Overlay(self, entry, len(self.overlays))
        except Exception as exc:
            self.notify("Eklenemedi", str(exc)[:400])
            return
        self.overlays.append(overlay)
        self.write_config()
        self._rebuild_menu()

    def remove_overlay(self, overlay: Overlay):
        overlay.destroy()
        if overlay in self.overlays:
            self.overlays.remove(overlay)
        self.write_config()
        self._rebuild_menu()

    # -- eylemler -----------------------------------------------------------
    def set_edit_mode(self, enabled=None):
        if enabled is None:
            enabled = not self.edit_mode
        enabled = bool(enabled)
        if enabled == self.edit_mode:
            return
        if not enabled:
            # son konumları pencerelerden al
            for overlay in self.overlays:
                overlay.save_position_from_window()
        self.edit_mode = enabled
        for overlay in self.overlays:
            overlay.set_edit(self.edit_mode)
        if not self.edit_mode:
            self.write_config()
        self._rebuild_menu()
        if self.edit_mode:
            self.notify("Konumlandırma", "Overlay'leri fareyle sürükle, bitince tepsi → Konumlandır.")
        elif self._return_to_settings:
            self._return_to_settings = False
            QTimer.singleShot(150, self.open_settings)

    def toggle_hidden(self):
        self.hidden = not self.hidden
        for overlay in self.overlays:
            overlay.set_visible(not self.hidden)
        self._rebuild_menu()

    def toggle_pause_all(self):
        if any(not o.paused for o in self.overlays):
            for o in self.overlays:
                o.player.pause()
        else:
            for o in self.overlays:
                o.player.resume()

    @Slot(str, int, int)
    def savePosition(self, name: str, x: int, y: int):
        for overlay in self.overlays:
            if overlay.name == name:
                overlay.entry["x"] = int(x)
                overlay.entry["y"] = int(y)
                overlay._clamp_position()
                self.write_config()
                return

    def write_config(self):
        """Config'i 250 ms gecikmeyle yazar (slider sürüklerken disk yorulmasın)."""
        if self._save_timer is None:
            self._save_timer = QTimer(self)
            self._save_timer.setSingleShot(True)
            self._save_timer.setInterval(250)
            self._save_timer.timeout.connect(self._flush_config)
        self._save_timer.start()

    def _flush_config(self):
        try:
            text = render_toml([o.entry for o in self.overlays])
            self._written = text
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(text, encoding="utf-8")
            if str(CONFIG_PATH) not in self.watcher.files():
                self.watcher.addPath(str(CONFIG_PATH))
        except Exception as exc:
            self.notify("Config yazılamadı", str(exc)[:300])
        self.dataChanged.emit()

    def settings_changed(self):
        self.dataChanged.emit()

    # -- ayar penceresi ------------------------------------------------------
    def settings_visible(self) -> bool:
        try:
            return bool(self.settings_window is not None
                        and self.settings_window.property("visible"))
        except RuntimeError:
            self.settings_window = None
            return False

    def _set_overlay_windows_visible(self, visible: bool):
        for overlay in self.overlays:
            if overlay.window is not None:
                try:
                    overlay.window.setProperty("visible", bool(visible and overlay.visible))
                except RuntimeError:
                    pass

    def open_settings(self):
        if self.settings_component is None:
            self.settings_component = QQmlComponent(
                self.engine, QUrl.fromLocalFile(str(SETTINGS_QML_PATH))
            )
        if self.settings_component.isError():
            msg = self.settings_component.errorString()
            print(msg, file=sys.stderr)
            self.notify("Ayarlar açılamadı", msg[:600])
            return
        if self.settings_window is None:
            self.settings_window = self.settings_component.create()
            if self.settings_window is None:
                self.notify("Ayarlar açılamadı", self.settings_component.errorString()[:400])
                return
        self._return_to_settings = False
        if self.edit_mode:
            self.set_edit_mode(False)
        self._set_overlay_windows_visible(False)
        self.settings_window.setProperty("visible", True)
        try:
            self.settings_window.requestActivate()
        except Exception:
            pass
        self.settings._update_stats()
        self.dataChanged.emit()

    def close_settings(self):
        if self.settings_window is not None:
            try:
                self.settings_window.setProperty("visible", False)
            except RuntimeError:
                self.settings_window = None
        self._set_overlay_windows_visible(True)

    def locate_current(self, overlay):
        if overlay is None:
            return
        if self.settings_window is not None:
            try:
                self.settings_window.setProperty("visible", False)
            except RuntimeError:
                self.settings_window = None
        self._set_overlay_windows_visible(True)
        self._return_to_settings = True
        self.set_edit_mode(True)
        self.notify("Konumlandırma", "Overlay'i sürükle; bitirmek için tepsi → Konumlandır.")

    def clear_cache(self):
        from player import CACHE_DIR

        removed = 0
        try:
            for path in CACHE_DIR.glob("*.webm"):
                path.unlink(missing_ok=True)
                path.with_suffix(".json").unlink(missing_ok=True)
                removed += 1
        except Exception as exc:
            self.notify("Önbellek temizlenemedi", str(exc)[:300])
            return
        self.notify("Önbellek temizlendi", f"{removed} dosya silindi. Animasyonlar yeniden hazırlanacak.")

    def _on_config_file_changed(self, path: str):
        if str(CONFIG_PATH) not in self.watcher.files():
            QTimer.singleShot(400, lambda: self.watcher.addPath(str(CONFIG_PATH)))
        try:
            text = CONFIG_PATH.read_text(encoding="utf-8")
        except Exception:
            return
        if self._written is not None and text == self._written:
            return
        QTimer.singleShot(150, self.reload_all)

    def pick_screen(self, name):
        screens = self.qapp.screens()
        if name:
            for screen in screens:
                if screen.name() == name:
                    return screen
        return self.qapp.primaryScreen() or (screens[0] if screens else None)

    # -- IPC ----------------------------------------------------------------
    def _start_ipc(self):
        QLocalServer.removeServer(SOCKET_NAME)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        self.server.listen(SOCKET_NAME)

    def _on_connection(self):
        conn = self.server.nextPendingConnection()
        if conn is None:
            return

        done = {"v": False}

        def handle():
            if done["v"]:
                return
            done["v"] = True
            raw = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            cmd = raw.lower()
            reply = "ok"
            if cmd in ("toggle", "show-hide"):
                self.toggle_hidden()
            elif cmd == "hide":
                if not self.hidden:
                    self.toggle_hidden()
            elif cmd == "show":
                if self.hidden:
                    self.toggle_hidden()
            elif cmd == "move":
                self.set_edit_mode()
            elif cmd == "settings":
                self.open_settings()
            elif cmd == "settings-close":
                self.close_settings()
            elif cmd == "reload":
                self.reload_all()
            elif cmd == "pause":
                if any(not o.paused for o in self.overlays):
                    self.toggle_pause_all()
            elif cmd == "quit":
                self.quit()
            elif cmd.startswith("add "):
                self.add_overlay_file(raw[4:].strip())
            elif cmd.startswith("remove "):
                target = raw[7:].strip()
                for overlay in list(self.overlays):
                    if overlay.name == target:
                        self.remove_overlay(overlay)
                        break
            elif cmd == "list":
                reply = "\n".join(f"{o.name}\t{o.entry['file']}\t{o.entry['x']},{o.entry['y']}" for o in self.overlays)
            elif cmd.startswith(("height ", "opacity ", "speed ", "fps ")):
                import shlex

                parts = shlex.split(raw)
                if len(parts) != 3:
                    reply = "kullanım: height|opacity|speed|fps <isim> <değer>"
                else:
                    key, name, value = parts
                    found = None
                    for o in self.overlays:
                        if o.name == name:
                            found = o
                            break
                    if found is None:
                        reply = "overlay bulunamadı"
                    else:
                        try:
                            if key == "height":
                                found.set_height_value(int(float(value)))
                            elif key == "opacity":
                                found.set_opacity_value(float(value) / 100.0)
                            elif key == "speed":
                                found.set_speed_value(float(value) / 100.0)
                            else:
                                found.set_max_fps_value(int(float(value)))
                        except ValueError:
                            reply = "geçersiz değer"
            else:
                reply = "bilinmeyen komut"
            conn.write((reply + "\n").encode())
            conn.flush()
            conn.disconnectFromServer()

        conn.readyRead.connect(handle)
        QTimer.singleShot(1500, handle)

    def quit(self):
        for overlay in self.overlays:
            overlay.destroy()
        self._flush_config()
        self.tray.hide()
        self.qapp.quit()

    def run(self) -> int:
        return self.qapp.exec()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def ctl(command: str, quiet: bool = False) -> int:
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(1500):
        if not quiet:
            print("anime-overlay çalışmıyor", file=sys.stderr)
        return 1
    sock.write((command + "\n").encode())
    sock.flush()
    sock.waitForReadyRead(5000)
    print(bytes(sock.readAll()).decode("utf-8", "replace").strip())
    sock.disconnectFromServer()
    return 0


def main() -> int:
    argv = sys.argv
    if len(argv) > 1 and argv[1] in ("settings", "ayarlar"):
        # Çalışıyorsa ayar penceresini aç; çalışmıyorsa başlatıp aç.
        from PySide6.QtCore import QCoreApplication
        _app = QCoreApplication(argv[:1])
        if ctl("settings", quiet=True) == 0:
            return 0
        import subprocess
        env = dict(os.environ, ANIME_OVERLAY_OPEN_SETTINGS="1")
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve())],
            start_new_session=True, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return 0

    if len(argv) > 1 and argv[1] == "ctl":
        from PySide6.QtCore import QCoreApplication
        _app = QCoreApplication(argv[:1])
        return ctl(" ".join(argv[2:]) or "list")

    # tek örnek kilidi (otomatik başlatma + elle başlatma çakışmasın)
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    lock_path = runtime / "anime-overlay.lock"
    lock_file = open(lock_path, "w")
    try:
        import fcntl
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # zaten çalışıyor: varsa gizliyse göster
        from PySide6.QtCore import QCoreApplication
        _app = QCoreApplication(argv[:1])
        ctl("show")
        return 0

    # oyunlar/uygulamalar CPU'yu bizden önce alsın
    try:
        os.nice(5)
    except Exception:
        pass
    try:
        prune_cache()
    except Exception as exc:
        print(f"önbellek temizliği: {exc}", file=sys.stderr)

    app = AnimeOverlay(argv)
    app._lock_file = lock_file  # GC'ye karşı canlı tut
    return app.run()

if __name__ == "__main__":
    sys.exit(main())
