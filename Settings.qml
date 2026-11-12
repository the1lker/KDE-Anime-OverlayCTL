import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// Ayar penceresi. Normal bir pencere (layer-shell değil); tepsi → Ayarlar… ile
// açılır. Kapatınca uygulama kapanmaz, pencere gizlenir.
Kirigami.ApplicationWindow {
    id: win

    title: ""
    width: 1000
    height: 720
    minimumWidth: 820
    minimumHeight: 560
    visible: false

    // Kapatma = gizle
    onClosing: (close) => {
        close.accepted = false
        settings.closeWindow()
    }

    pageStack.initialPage: Kirigami.Page {
        title: "Ayarlar"
        padding: 0

        RowLayout {
            anchors.fill: parent
            spacing: 0

            // ---------------------------------------------------------------- #
            // Sol panel: overlay listesi
            // ---------------------------------------------------------------- #
            Rectangle {
                Layout.fillHeight: true
                Layout.preferredWidth: 290
                color: Kirigami.Theme.alternateBackgroundColor

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Kirigami.Units.largeSpacing
                    spacing: Kirigami.Units.smallSpacing

                    Kirigami.Heading {
                        text: "Animasyonlar"
                        level: 2
                        Layout.fillWidth: true
                    }

                    Controls.Button {
                        Layout.fillWidth: true
                        text: "Yeni animasyon…"
                        icon.name: "list-add"
                        onClicked: settings.add()
                    }

                    Controls.ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true

                        ListView {
                            id: overlayListView
                            model: settings.overlayList
                            spacing: 2
                            delegate: Controls.ItemDelegate {
                                width: ListView.view.width
                                highlighted: index === settings.currentIndex
                                onClicked: settings.select(index)

                                contentItem: ColumnLayout {
                                    spacing: 0

                                    Controls.Label {
                                        Layout.fillWidth: true
                                        text: modelData.name
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }

                                    Controls.Label {
                                        Layout.fillWidth: true
                                        text: modelData.fileName + "  ·  "
                                              + modelData.width + "×" + modelData.height
                                        opacity: 0.65
                                        font.pixelSize: Math.round(Kirigami.Theme.defaultFont.pixelSize * 0.85)
                                        elide: Text.ElideMiddle
                                    }
                                }
                            }
                        }
                    }

                    Controls.Label {
                        Layout.fillWidth: true
                        visible: settings.overlayList.length === 0
                        text: "Henüz animasyon yok.\nYukarıdan bir GIF veya video ekle."
                        wrapMode: Text.WordWrap
                        opacity: 0.7
                    }
                }
            }

            // ---------------------------------------------------------------- #
            // Sağ panel: seçili overlay
            // ---------------------------------------------------------------- #
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Kirigami.Theme.backgroundColor

                Flickable {
                    anchors.fill: parent
                    clip: true
                    contentWidth: width
                    contentHeight: contentColumn.implicitHeight + 2 * Kirigami.Units.largeSpacing
                    boundsBehavior: Flickable.StopAtBounds

                    ColumnLayout {
                        id: contentColumn
                        x: Kirigami.Units.largeSpacing
                        y: Kirigami.Units.largeSpacing
                        width: parent.width - 2 * Kirigami.Units.largeSpacing
                        spacing: Kirigami.Units.smallSpacing

                        // --- boş durum ---
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName === ""
                            spacing: Kirigami.Units.largeSpacing

                            Kirigami.Heading {
                                text: "Başlamak için bir animasyon ekle"
                                level: 3
                                Layout.fillWidth: true
                            }

                            Controls.Button {
                                text: "Animasyon seç…"
                                icon.name: "list-add"
                                onClicked: settings.add()
                            }
                        }

                        // --- başlık ---
                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Kirigami.Heading {
                                Layout.fillWidth: true
                                text: settings.currentName
                                level: 3
                                elide: Text.ElideRight
                            }

                            Controls.Button {
                                text: "Dosya değiştir…"
                                icon.name: "document-open"
                                onClicked: settings.chooseFile()
                            }

                            Controls.Button {
                                text: "Kapat"
                                icon.name: "window-close"
                                onClicked: settings.closeWindow()
                            }
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""
                            text: settings.currentFilePath
                            opacity: 0.65
                            elide: Text.ElideMiddle
                        }

                        // --- canlı önizleme ---
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 200
                            visible: settings.currentName !== ""
                            radius: Kirigami.Units.cornerRadius
                            color: Kirigami.Theme.alternateBackgroundColor
                            border.width: 1
                            border.color: Kirigami.Theme.disabledTextColor
                            clip: true

                            Image {
                                anchors.fill: parent
                                anchors.margins: Kirigami.Units.smallSpacing
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                cache: false
                                source: settings.currentName === ""
                                        ? ""
                                        : "image://frames/" + settings.currentName + "/" + settings.previewTick
                            }
                        }

                        // --- boyut ---
                        Controls.Label {
                            visible: settings.currentName !== ""
                            text: "Boyut"
                            font.bold: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Controls.Slider {
                                id: heightSlider
                                Layout.fillWidth: true
                                from: 64
                                to: 800
                                onMoved: settings.setHeight(Math.round(value))
                            }

                            Controls.Label {
                                Layout.preferredWidth: 62
                                horizontalAlignment: Text.AlignRight
                                text: settings.currentHeight + " px"
                            }

                            Binding {
                                target: heightSlider
                                property: "value"
                                value: settings.currentHeight
                                when: !heightSlider.pressed
                                restoreMode: Binding.RestoreNone
                            }
                        }

                        // --- opaklık ---
                        Controls.Label {
                            visible: settings.currentName !== ""
                            text: "Opaklık"
                            font.bold: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Controls.Slider {
                                id: opacitySlider
                                Layout.fillWidth: true
                                from: 5
                                to: 100
                                onMoved: settings.setOpacity(Math.round(value))
                            }

                            Controls.Label {
                                Layout.preferredWidth: 62
                                horizontalAlignment: Text.AlignRight
                                text: settings.currentOpacity + " %"
                            }

                            Binding {
                                target: opacitySlider
                                property: "value"
                                value: settings.currentOpacity
                                when: !opacitySlider.pressed
                                restoreMode: Binding.RestoreNone
                            }
                        }

                        // --- hız ---
                        Controls.Label {
                            visible: settings.currentName !== ""
                            text: "Hız"
                            font.bold: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Controls.Slider {
                                id: speedSlider
                                Layout.fillWidth: true
                                from: 25
                                to: 400
                                onMoved: settings.setSpeed(Math.round(value))
                            }

                            Controls.Label {
                                Layout.preferredWidth: 62
                                horizontalAlignment: Text.AlignRight
                                text: (settings.currentSpeed / 100).toFixed(2) + "×"
                            }

                            Binding {
                                target: speedSlider
                                property: "value"
                                value: settings.currentSpeed
                                when: !speedSlider.pressed
                                restoreMode: Binding.RestoreNone
                            }
                        }

                        // --- fps sınırı ---
                        Controls.Label {
                            visible: settings.currentName !== ""
                            text: "Kare hızı sınırı (oyunlarda CPU tasarrufu)"
                            font.bold: true
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Controls.Slider {
                                id: fpsSlider
                                Layout.fillWidth: true
                                from: 5
                                to: 30
                                onMoved: settings.setFps(Math.round(value))
                            }

                            Controls.Label {
                                Layout.preferredWidth: 62
                                horizontalAlignment: Text.AlignRight
                                text: settings.currentFps + " fps"
                            }

                            Binding {
                                target: fpsSlider
                                property: "value"
                                value: settings.currentFps
                                when: !fpsSlider.pressed
                                restoreMode: Binding.RestoreNone
                            }
                        }

                        Kirigami.Separator {
                            Layout.fillWidth: true
                            Layout.topMargin: Kirigami.Units.smallSpacing
                            Layout.bottomMargin: Kirigami.Units.smallSpacing
                            visible: settings.currentName !== ""
                        }

                        // --- ekran ---
                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Controls.Label {
                                text: "Ekran"
                                Layout.preferredWidth: 140
                            }

                            Controls.ComboBox {
                                id: screenCombo
                                Layout.fillWidth: true
                                model: settings.screens
                                currentIndex: settings.currentScreenIndex
                                onActivated: settings.setScreenIndex(index)
                            }

                            Binding {
                                target: screenCombo
                                property: "currentIndex"
                                value: settings.currentScreenIndex
                                when: !screenCombo.popup.visible
                                restoreMode: Binding.RestoreNone
                            }
                        }

                        // --- beyaz arka plan ---
                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Controls.Label {
                                text: "Beyaz arka plan"
                                Layout.preferredWidth: 140
                            }

                            Controls.ComboBox {
                                id: whiteCombo
                                Layout.fillWidth: true
                                model: ["Otomatik", "Arka planı sil", "Dokunma"]
                                currentIndex: settings.currentRemoveWhite === "on" ? 1
                                            : settings.currentRemoveWhite === "off" ? 2 : 0
                                onActivated: settings.setRemoveWhite(["auto", "on", "off"][index])
                            }
                        }

                        // --- konum ---
                        RowLayout {
                            Layout.fillWidth: true
                            visible: settings.currentName !== ""

                            Controls.Label {
                                text: "Konum"
                                Layout.preferredWidth: 140
                            }

                            Controls.SpinBox {
                                id: xSpin
                                from: -5000
                                to: 10000
                                editable: true
                                value: settings.currentX
                                Layout.preferredWidth: 120
                                onValueModified: settings.setPosition(value, ySpin.value)
                            }

                            Controls.SpinBox {
                                id: ySpin
                                from: -5000
                                to: 10000
                                editable: true
                                value: settings.currentY
                                Layout.preferredWidth: 120
                                onValueModified: settings.setPosition(xSpin.value, value)
                            }

                            Binding {
                                target: xSpin
                                property: "value"
                                value: settings.currentX
                                when: !xSpin.activeFocus
                                restoreMode: Binding.RestoreNone
                            }

                            Binding {
                                target: ySpin
                                property: "value"
                                value: settings.currentY
                                when: !ySpin.activeFocus
                                restoreMode: Binding.RestoreNone
                            }

                            Item { Layout.fillWidth: true }
                        }

                        // --- eylemler ---
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.topMargin: Kirigami.Units.smallSpacing
                            visible: settings.currentName !== ""

                            Controls.Button {
                                text: settings.currentPaused ? "Devam ettir" : "Duraklat"
                                icon.name: settings.currentPaused ? "media-playback-start" : "media-playback-pause"
                                onClicked: settings.togglePause()
                            }

                            Controls.Button {
                                text: "Konumlandır (sürükle)"
                                icon.name: "transform-move"
                                onClicked: settings.locate()
                            }

                            Item { Layout.fillWidth: true }

                            Controls.Button {
                                text: "Overlay'i kaldır"
                                icon.name: "edit-delete"
                                onClicked: settings.remove()
                            }
                        }

                        Kirigami.Separator {
                            Layout.fillWidth: true
                            Layout.topMargin: Kirigami.Units.largeSpacing
                            Layout.bottomMargin: Kirigami.Units.smallSpacing
                        }

                        // --- genel ---
                        Kirigami.Heading {
                            text: "Genel"
                            level: 3
                        }

                        RowLayout {
                            Layout.fillWidth: true

                            Controls.Switch {
                                id: autostartSwitch
                                text: "Oturum açılışında otomatik başlat"
                                checked: settings.autostart
                                onToggled: settings.setAutostart(checked)
                            }

                            Binding {
                                target: autostartSwitch
                                property: "checked"
                                value: settings.autostart
                                when: !autostartSwitch.pressed
                                restoreMode: Binding.RestoreNone
                            }

                            Item { Layout.fillWidth: true }
                        }

                        RowLayout {
                            Layout.fillWidth: true

                            Controls.Button {
                                text: "Önbelleği temizle"
                                icon.name: "edit-clear-history"
                                onClicked: settings.clearCache()
                            }

                            Item { Layout.fillWidth: true }

                            Controls.Label {
                                text: settings.stats
                                opacity: 0.65
                                font.pixelSize: Math.round(Kirigami.Theme.defaultFont.pixelSize * 0.85)
                            }
                        }

                        Controls.Label {
                            Layout.fillWidth: true
                            Layout.topMargin: Kirigami.Units.smallSpacing
                            text: "Değişiklikler anında uygulanır ve ~/.config/anime-overlay/config.toml dosyasına yazılır."
                            opacity: 0.55
                            wrapMode: Text.WordWrap
                            font.pixelSize: Math.round(Kirigami.Theme.defaultFont.pixelSize * 0.85)
                        }

                        Item { Layout.fillHeight: true }
                    }
                }
            }
        }
    }
}
