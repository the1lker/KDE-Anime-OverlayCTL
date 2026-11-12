# anime-overlay

KDE Plasma 6 (Wayland) üzerinde **her pencerenin üstünde** duran, fare
tıklamalarını altındaki uygulamaya geçiren GIF / WebP / video overlay'i.

- Tam ekran oyunların üstünde kalır (`wlr-layer-shell` overlay katmanı)
- Tıklamaları yutar/yakalamaz: altındaki pencere çalışmaya devam eder
- Şeffaf arka plan: GIF/WebP ve VP9 alpha video desteklenir
- Beyaz arka planlı GIF/videolar için otomatik "arka planı sil"
- Çoklu overlay, sürükle-bırak konumlandırma, tepsi menüsü, canlı config
- **Kirigami ayar penceresi**: TOML düzenlemeye gerek yok
- Oyuna enjeksiyon yapmaz → anti-cheat (VAC) açısından güvenli

## Gereksinimler

Arch / Plasma 6 Wayland üzerinde hazır:

```
qt6-declarative  layer-shell-qt  pyside6  ffmpeg  python-numpy  kirigami
```

## Kurulum

```bash
cd ~/Projects/kde-anime-overlay
./install.sh
```

Bu komut `~/.local/bin/anime-overlay` bağlantısını, uygulama menüsü girdisini
ve otomatik başlatmayı kurar. Elle başlatmak için:

```bash
~/.local/bin/anime-overlay
# ~/.local/bin PATH'te ise: anime-overlay
```

`~/.local/bin` PATH'te değilse kabuk profiline ekleyebilirsin:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

İlk çalıştırmada henüz config yoksa **ayar penceresi kendiliğinden açılır**.
Tepsi ikonu: **sol tık** göster/gizle, **sağ tık** menü.

Terminal kullanmadan:

- **Uygulama menüsü → Anime Overlay** → başlatır (zaten oturum açılışında
  otomatik başlıyor).
- **Uygulama menüsü → Anime Overlay Ayarları** → çalışmıyorsa başlatıp ayar
  penceresini açar.
- Tepsi ikonu → **Ayarlar…**

Terminalden:

```bash
anime-overlay            # başlat
anime-overlay settings   # başlat (gerekirse) + ayar penceresini aç
```

## Ayar penceresi

Tepsi → **Ayarlar…** (veya `anime-overlay ctl settings`).

| Bölüm | Ne yapar |
|---|---|
| Sol liste | Overlay'ler, canlı boyut bilgisi; **＋ Yeni animasyon…** |
| Canlı önizleme | Seçili animasyonu gerçek zamanlı gösterir |
| Dosya değiştir… | GIF/WebP/MP4/WebM seçer, yeniden hazırlar |
| Boyut / Opaklık / Hız | 64–800 px, %5–100, 0.25–4× — anında uygulanır |
| Kare hızı sınırı | 5–30 fps; oyunlarda decode yükünü azaltır |
| Ekran | Çoklu monitörde overlay'in hangi ekranda duracağı |
| Beyaz arka plan | Otomatik / Arka planı sil / Dokunma |
| Konum X / Y | Piksel cinsinden konum (veya aşağıdaki düğme) |
| Konumlandır (sürükle) | Pencereyi gizler, overlay'i fareyle taşırsın |
| Genel | Otomatik başlatma, önbelleği temizle, canlı RAM/önbellek bilgisi |

Her değişiklik anında uygulanır ve ~250 ms içinde config'e yazılır. Pencereyi
kapatmak uygulamayı kapatmaz; overlay'ler geri gelir.

## Tepsi menüsü

| Menü | Açıklama |
|---|---|
| *Ayarlar…* | Ayar penceresini açar |
| *Yeni animasyon ekle…* | GIF/WebP/MP4/WebM seç |
| *Konumlandır* | Overlay'ler sürüklenebilir olur; bitince tekrar tıkla |
| *Gizle / Göster* | Hepsini gizle |
| *Tümünü duraklat* | Oynatmayı durdurur (CPU ~0) |
| *<isim>* alt menüsü | Dosya değiştir, boyut, opaklık, hız, kaldır |

## Komut satırı

```bash
anime-overlay ctl toggle                   # göster/gizle
anime-overlay ctl move                     # konumlandırma modu
anime-overlay ctl pause                    # duraklat/devam
anime-overlay ctl reload                   # config'i yeniden yükle
anime-overlay ctl list                     # overlay listesi
anime-overlay ctl settings                 # ayar penceresini aç
anime-overlay ctl settings-close           # ayar penceresini kapat
anime-overlay ctl add /yol/dosya.gif
anime-overlay ctl remove miku
anime-overlay ctl height miku 360          # boyut (px)
anime-overlay ctl opacity miku 80          # opaklık (%)
anime-overlay ctl speed miku 150           # hız (%, 100 = normal)
anime-overlay ctl fps miku 15              # kare hızı sınırı
anime-overlay ctl quit                     # çık
```

## Yapılandırma

`~/.config/anime-overlay/config.toml` (uygulama açıkken düzenleyebilirsin,
otomatik yeniden yüklenir; ayar penceresi de buraya yazar):

```toml
[[overlay]]
name = "miku"
file = "/home/kullanici/Görseller/miku.gif"
x = 1612              # sol üst köşe (mantıksal piksel)
y = 880
height = 320          # yükseklik (piksel)
opacity = 1.0
speed = 1.0
max_fps = 15          # kare hızı sınırı
screen = "eDP-1"      # kscreen-doctor -o
remove_white = "auto" # "auto" | true | false
```

`x`/`y` yazılmazsa sağ alt köşeye yerleşir. Konumlandırma modunda sürükleyince
değerler otomatik yazılır.

### Beyaz arka planı silme

`remove_white = "auto"` → kaynak tamamen opaksa ve köşeler beyazsa, her karede
**görüntü kenarına bağlı** beyaz bölgeler saydam yapılır. Karakterin içindeki
beyazlar (yüz, gözler, gömlek) korunur. Beyaz arka planlı GIF'ler için birebir
bu ayar kullanılır; gerçek şeffaflığa sahip dosyalarda hiçbir şey değiştirilmez.

## Performans

Varsayılanlar hafif tutulur:

- 320 px yükseklik, **15 fps** üst sınır (`max_fps`)
- Önbellek en fazla **480p**; ölçekleme `fast_bilinear`
- ffmpeg süreçleri `nice` ile düşük öncelikte, uygulama `nice +5`
- Önbellek tavanı: 20 dosya / 200 MB; açılışta eskiler silinir
- Eşik altındaki kaynaklarda fps filtresi eklenmez (12.5 fps GIF olduğu gibi kalır)

Oyunlarda ekstra tasarruf için ayar penceresinden kare hızı sınırını 8–10'a
çekebilir veya tepsi → *Tümünü duraklat* kullanabilirsin.

> Not: Wayland'da overlay açıkken KWin direct-scanout yapamaz; bu birkaç FPS'e
> mal olabilir. Bu yüzden oyunlarda **Pencereli Tam Ekran** gerekir.

## Nasıl çalışır?

```
kaynak dosya ──ffmpeg──► ~/.cache/anime-overlay/<hash>.webm  (VP9, max 480p)
                               │
               ffmpeg -re -stream_loop -1 -c:v libvpx-vp9
                               │  RGBA kareler (pipe)
                               ▼
              FrameStore (QQuickImageProvider) ──► QML Image
                               ▲
              QML Window + LayerShellQt (LayerOverlay, tık-geçirgen)
```

Dönüştürme yalnızca dosya ilk kez kullanıldığında (veya beyaz arka plan ayarı
değiştiğinde) yapılır ve önbelleğe alınır.

## Sorun giderme

- **Tam ekran oyunda görünmüyor**: Oyunda *Pencereli Tam Ekran / Windowed
  Fullscreen* kullan. Wayland'da saf exclusive fullscreen doğrudan taranır
  (direct scanout); compositor katmanı araya giremez.
- **Tıklamalar geçmiyor**: Uygulamanın Wayland'da çalıştığından emin ol
  (`echo $XDG_SESSION_TYPE` → `wayland`). XWayland altında tık-geçirgenlik
  çalışmaz.
- **Hiçbir şey görünmüyor**: `anime-overlay` çalışıyor mu? `anime-overlay ctl list`
  ve `journalctl --user -f` / terminal çıktısına bak.
- **Önbelleği temizle**: Ayar penceresi → *Önbelleği temizle* veya
  `rm -rf ~/.cache/anime-overlay` (sonraki açılışta yeniden dönüştürülür).
- **Konumlandırma modundan çıkma**: Tepsi → *Konumlandır* (işaretini kaldır).
  Ayar penceresinden başlattıysan pencere otomatik geri gelir.
