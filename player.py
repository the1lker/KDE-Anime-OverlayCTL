"""
Medya hazırlama (ffmpeg ile önbellek) ve kare kare oynatma.

Akış:
  kaynak (gif/webp/mp4/webm/...)  --ffmpeg-->  ~/.cache/anime-overlay/<hash>.webm
  cache .webm  --ffmpeg -re -stream_loop-->  RGBA kareler (pipe)
  kareler  -->  FrameStore (QQuickImageProvider)  -->  QML Image

Şeffaflık (VP9 alpha) `libvpx-vp9` decoder ile korunur. Opaque kaynaklarda
isteğe bağlı olarak "beyaz arka planı sil" (kenardan bağlı beyaz bölgeler)
uygulanır; karakterin içindeki beyazlar korunur.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path

from PySide6.QtCore import QMutex, QMutexLocker, QObject, QProcess, QSize, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "anime-overlay"
MAX_CACHE_HEIGHT = 480          # önbelleğe alınan videonun en fazla yüksekliği
MAX_CACHE_FILES = 20            # önbellekte tutulacak dosya sayısı
MAX_CACHE_BYTES = 200 * 1024 * 1024
WHITE = 238                     # "beyaz" eşiği

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


def ensure_dirs():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def prune_cache():
    """Eski önbellek dosyalarını temizler (tavsiye edilen sınırlar)."""
    ensure_dirs()
    for tmp in CACHE_DIR.glob("*.tmp.webm"):
        tmp.unlink(missing_ok=True)
    webms = sorted(CACHE_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
    total = 0
    for i, path in enumerate(webms):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if i < MAX_CACHE_FILES and total + size <= MAX_CACHE_BYTES:
            total += size
            continue
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# ffprobe
# --------------------------------------------------------------------------- #

def probe_media(path: str) -> dict:
    """Kaynak medya hakkında temel bilgi."""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,pix_fmt",
         "-of", "json", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout
    info = json.loads(out or b"{}")
    streams = info.get("streams") or []
    if not streams:
        raise RuntimeError(f"Video akışı bulunamadı: {path}")
    s = streams[0]
    w, h = int(s["width"]), int(s["height"])
    fps = s.get("r_frame_rate") or "25/1"
    try:
        num, den = (int(x) for x in fps.split("/"))
        if num <= 0 or den <= 0:
            raise ValueError
    except Exception:
        num, den = 25, 1
    return {
        "width": w,
        "height": h,
        "fps": f"{num}/{den}",
        "fps_value": num / den,
        "pix_fmt": s.get("pix_fmt", ""),
    }


# --------------------------------------------------------------------------- #
# ffmpeg yardımcıları
# --------------------------------------------------------------------------- #

def _iter_rgba_frames(path: str, w: int, h: int):
    """ffmpeg ile dosyayı RGBA karelerine çevirip tek tek verir."""
    import numpy as np

    cmd = [FFMPEG, "-v", "error", "-i", str(path),
           "-vf", f"scale={w}:{h},format=rgba",
           "-pix_fmt", "rgba", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = w * h * 4
    try:
        while True:
            buf = proc.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 4)
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        proc.wait()


def _even(n: int) -> int:
    return max(2, int(n) - (int(n) % 2))


def _scaled_size(w: int, h: int, max_h: int) -> tuple[int, int]:
    out_h = min(int(h), int(max_h))
    out_w = _even(round(w * out_h / h))
    return out_w, _even(out_h)


def _ffmpeg_transcode(src: str, dst: Path, w: int, h: int, alpha: bool):
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src), "-an",
           "-vf", f"scale={w}:{h}",
           "-c:v", "libvpx-vp9", "-row-mt", "1",
           "-deadline", "realtime", "-cpu-used", "8",
           "-crf", "32", "-b:v", "0"]
    if alpha:
        cmd += ["-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
                "-metadata:s:v:0", "alpha_mode=1"]
    else:
        cmd += ["-pix_fmt", "yuv420p"]
    cmd += [str(dst)]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg dönüştürme hatası: " + r.stderr.decode("utf-8", "replace")[-500:])


def _background_mask(white: "np.ndarray") -> "np.ndarray":
    """
    Kare içinde beyaz olan ve görüntü kenarına bağlı olan bölge.
    Satır bazlı run + union-find ile hızlı ve tam sonuç verir.
    Karakterin içindeki beyazlar (göz, yüz, kıyafet) korunur.
    """
    import numpy as np

    h, w = white.shape
    parent: list[int] = []
    is_border: list[bool] = []
    runs: list[tuple[int, int, int, int]] = []
    prev: list[tuple[int, int, int]] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for y in range(h):
        row = white[y]
        if not row.any():
            prev = []
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        cur: list[tuple[int, int, int]] = []
        j = 0
        for s, e in zip(starts, ends):
            idx = len(parent)
            parent.append(idx)
            is_border.append(bool(y == 0 or y == h - 1 or s == 0 or e == w))
            while j < len(prev) and prev[j][1] <= s:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < e:
                union(idx, prev[k][2])
                k += 1
            cur.append((int(s), int(e), idx))
            runs.append((y, int(s), int(e), idx))
        prev = cur

    if not runs:
        return np.zeros_like(white)

    border_roots = {find(i) for i, b in enumerate(is_border) if b}
    mask = np.zeros_like(white)
    for y, s, e, idx in runs:
        if find(idx) in border_roots:
            mask[y, s:e] = True
    return mask


def _has_real_alpha(src: str) -> bool:
    """Kaynakta gerçekten saydam piksel var mı? (ilk birkaç kareye bak)."""
    cmd = [FFMPEG, "-v", "error", "-i", str(src), "-frames:v", "3",
           "-vf", "scale=96:-2,format=rgba", "-pix_fmt", "rgba",
           "-f", "rawvideo", "pipe:1"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = r.stdout
    if not data:
        return False
    # genişlik 96, yükseklik bilinmiyor -> ffprobe'dan değil, çerçeve boyundan
    # kesin boyutu bilmek için ilk kareyi çözemiyoruz; alfa baytlarını tara
    return any(data[i] < 250 for i in range(3, len(data), 4))


def _border_white(src: str) -> bool:
    """Köşeler beyaza yakın mı? (arka plan silme için ön koşul)"""
    import numpy as np

    cmd = [FFMPEG, "-v", "error", "-i", str(src), "-frames:v", "1",
           "-vf", "scale=96:-2,format=rgba", "-pix_fmt", "rgba",
           "-f", "rawvideo", "pipe:1"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = r.stdout
    if len(data) < 96 * 2 * 4:
        return False
    # yüksekliği bul: boy / (96*4)
    h = len(data) // (96 * 4)
    if h < 2:
        return False
    arr = np.frombuffer(data[: 96 * h * 4], np.uint8).reshape(h, 96, 4)
    corners = [arr[0, 0], arr[0, 95], arr[h - 1, 0], arr[h - 1, 95]]
    white = sum(1 for c in corners if c[0] >= 235 and c[1] >= 235 and c[2] >= 235)
    return white >= 3


def _key_out_white(src: str, dst: Path, w: int, h: int, fps: str):
    """
    Beyaz arka planı siler. Her karede, kenara bağlı beyaz bölge saydam olur;
    karakterin içindeki beyaz alanlar (yüz, gözler, kıyafet) korunur.
    """
    enc = subprocess.Popen(
        [FFMPEG, "-y", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", fps, "-i", "pipe:0",
         "-an", "-vf", "format=yuva420p",
         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
         "-metadata:s:v:0", "alpha_mode=1", "-row-mt", "1",
         "-deadline", "realtime", "-cpu-used", "8", "-crf", "32", "-b:v", "0",
         str(dst)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    frames = 0
    try:
        for raw in _iter_rgba_frames(src, w, h):
            frames += 1
            frame = raw.copy()
            white = ((frame[..., 0] >= WHITE)
                     & (frame[..., 1] >= WHITE)
                     & (frame[..., 2] >= WHITE))
            m = _background_mask(white)
            if m.any():
                near = ((frame[..., 0] >= WHITE - 14)
                        & (frame[..., 1] >= WHITE - 14)
                        & (frame[..., 2] >= WHITE - 14))
                # anti-aliased beyaz halkayı 2 piksel temizle
                for _ in range(2):
                    nb = m.copy()
                    nb[1:, :] |= m[:-1, :]
                    nb[:-1, :] |= m[1:, :]
                    nb[:, 1:] |= m[:, :-1]
                    nb[:, :-1] |= m[:, 1:]
                    m = nb & (near | m)
                frame[..., 3][m] = 0
            enc.stdin.write(frame.tobytes())
    finally:
        try:
            enc.stdin.close()
        except Exception:
            pass
    err = enc.stderr.read().decode("utf-8", "replace")
    enc.wait()
    if enc.returncode != 0 or frames == 0:
        raise RuntimeError("ffmpeg alpha kodlama hatası: " + (err[-500:] or "kare okunamadı"))


# --------------------------------------------------------------------------- #
# Önbellek
# --------------------------------------------------------------------------- #

def prepare_media(src: str, max_height: int = MAX_CACHE_HEIGHT,
                  remove_white: str = "auto") -> dict:
    """
    Kaynağı oynatılabilir hale getirir (gerekirse önbelleğe dönüştürür).
    Dönen sözlük: {path, width, height, fps, alpha, keyed}
    """
    ensure_dirs()
    src = str(Path(src).expanduser().resolve())
    if not os.path.isfile(src):
        raise FileNotFoundError(src)

    info = probe_media(src)
    src_w, src_h = info["width"], info["height"]
    fps = info["fps"]
    out_w, out_h = _scaled_size(src_w, src_h, max_height)

    real_alpha = _has_real_alpha(src)
    if remove_white is True:
        keying = True
    elif remove_white is False:
        keying = False
    else:  # "auto"
        keying = (not real_alpha) and _border_white(src)
    if real_alpha:
        keying = False  # gerçek alfa varsa dokunma

    st = os.stat(src)
    h = hashlib.sha1()
    h.update(f"v2|{src}|{st.st_size}|{st.st_mtime_ns}|{out_w}x{out_h}|{keying}|{WHITE}".encode())
    base = h.hexdigest()[:16]
    cache = CACHE_DIR / f"{base}.webm"
    meta_path = CACHE_DIR / f"{base}.json"

    if cache.is_file() and meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
            meta["keyed"] = meta.get("keyed", keying)
            return meta
        except Exception:
            pass

    tmp = cache.with_suffix(".tmp.webm")
    if keying:
        _key_out_white(src, tmp, out_w, out_h, fps)
    else:
        _ffmpeg_transcode(src, tmp, out_w, out_h, alpha=real_alpha)

    os.replace(tmp, cache)
    meta = {
        "path": str(cache),
        "width": out_w,
        "height": out_h,
        "fps": fps,
        "alpha": bool(real_alpha or keying),
        "keyed": bool(keying),
    }
    meta_path.write_text(json.dumps(meta))
    return meta


# --------------------------------------------------------------------------- #
# Kare deposu (QML image provider)
# --------------------------------------------------------------------------- #

class FrameStore(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.Image)
        self._mutex = QMutex()
        self._images: dict[str, QImage] = {}

    def set_frame(self, key: str, image: QImage):
        with QMutexLocker(self._mutex):
            self._images[key] = image

    def requestImage(self, image_id: str, size: QSize, requested_size: QSize):
        key = image_id.split("/")[0]
        with QMutexLocker(self._mutex):
            img = self._images.get(key)
            if img is None:
                img = QImage()
        if requested_size.isValid() and not img.isNull():
            img = img.scaled(requested_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if size is not None and not img.isNull():
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img


# --------------------------------------------------------------------------- #
# Oynatıcı
# --------------------------------------------------------------------------- #

class FfmpegPlayer(QObject):
    """Önbellekteki webm dosyasını ffmpeg ile kare kare oynatır."""

    frameReady = Signal(str, QImage)
    failed = Signal(str)

    def __init__(self, key: str, meta: dict, height: int, speed: float = 1.0,
                 max_fps: int = 15, parent=None):
        super().__init__(parent)
        self.key = key
        self.meta = meta
        self.height = int(height)
        self.speed = float(speed or 1.0)
        self.max_fps = int(max_fps or 15)
        self._proc: QProcess | None = None
        self._buf = bytearray()
        self._paused = False
        self._alive = False

    # -- boyut --------------------------------------------------------------
    def output_size(self) -> tuple[int, int]:
        h = max(16, min(int(self.height), int(self.meta["height"]) * 4))
        w = _even(round(self.meta["width"] * h / self.meta["height"]))
        return w, _even(h)

    def source_fps(self) -> float:
        try:
            num, den = (int(x) for x in str(self.meta.get("fps", "25/1")).split("/"))
            return num / den if den else 25.0
        except Exception:
            return 25.0

    # -- yaşam döngüsü ------------------------------------------------------
    def start(self):
        self.stop()
        self._alive = True
        w, h = self.output_size()
        filters = []
        if abs(self.speed - 1.0) > 0.001:
            filters.append(f"setpts=PTS/{self.speed:.4f}")
        filters.append(f"scale={w}:{h}:flags=fast_bilinear")
        if self.max_fps > 0 and self.source_fps() > self.max_fps + 0.01:
            filters.append(f"fps={self.max_fps}")
        filters.append("format=rgba")
        vf = ",".join(filters)
        # nice: oyun/uygulamalar CPU'yu bizden önce alsın
        cmd = ["nice", "-n", "5",
               FFMPEG, "-v", "error", "-re", "-stream_loop", "-1",
               "-c:v", "libvpx-vp9", "-i", self.meta["path"],
               "-an", "-vf", vf, "-pix_fmt", "rgba", "-f", "rawvideo", "pipe:1"]
        self._buf.clear()
        p = QProcess(self)
        p.setProgram(cmd[0])
        p.setArguments(cmd[1:])
        p.setProcessChannelMode(QProcess.SeparateChannels)
        p.readyReadStandardOutput.connect(self._on_read)
        p.finished.connect(self._on_finished)
        self._proc = p
        p.start()
        if self._paused:
            self._paused = False
        p.waitForStarted(3000)

    def stop(self):
        self._alive = False
        if self._proc is not None:
            p = self._proc
            self._proc = None
            try:
                p.readyReadStandardOutput.disconnect(self._on_read)
            except Exception:
                pass
            p.kill()
            p.waitForFinished(1500)
            p.deleteLater()

    def restart(self):
        was_paused = self._paused
        self._paused = False
        self.start()
        if was_paused:
            self.pause()

    def configure(self, height=None, speed=None, max_fps=None):
        """Birden fazla ayarı tek yeniden başlatmayla uygular."""
        changed = False
        if height is not None and int(height) != self.height:
            self.height = int(height)
            changed = True
        if speed is not None and abs(float(speed) - self.speed) > 0.001:
            self.speed = float(speed)
            changed = True
        if max_fps is not None and int(max_fps) != self.max_fps:
            self.max_fps = int(max_fps)
            changed = True
        if changed:
            self.restart()

    def set_height(self, height: int):
        self.configure(height=height)

    def set_speed(self, speed: float):
        self.configure(speed=speed)

    def set_max_fps(self, max_fps: int):
        self.configure(max_fps=max_fps)

    def pause(self):
        if self._proc is None or self._paused:
            return
        self._paused = True
        try:
            os.kill(int(self._proc.processId()), signal.SIGSTOP)
        except Exception:
            pass

    def resume(self):
        if self._proc is None or not self._paused:
            return
        self._paused = False
        try:
            os.kill(int(self._proc.processId()), signal.SIGCONT)
        except Exception:
            pass

    @property
    def paused(self) -> bool:
        return self._paused

    # -- kare okuma ---------------------------------------------------------
    def _on_read(self):
        if self._proc is None:
            return
        self._buf.extend(bytes(self._proc.readAllStandardOutput()))
        w, h = self.output_size()
        n = w * h * 4
        while len(self._buf) >= n:
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
            img = QImage(chunk, w, h, w * 4, QImage.Format_RGBA8888).copy()
            self.frameReady.emit(self.key, img)

    def _on_finished(self, code, status):
        if self._proc is None:
            return
        err = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace").strip()
        self._proc = None
        if not self._alive:
            return
        self.failed.emit(err or f"ffmpeg beklenmedik şekilde kapandı ({code})")
        # kısa bir bekleme sonrası yeniden dene
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, self._retry)

    def _retry(self):
        if self._alive:
            self.start()
