import QtQuick
import QtQuick.Window as Win
import org.kde.layershell as LS

// Tek bir overlay penceresi. Python tarafı her overlay için bundan bir tane
// oluşturur ve özellikleri (winX/winY/...) initial property olarak verir.
Win.Window {
    id: root

    property string mediaName: ""
    property string mediaKey: ""
    property int frameTick: 0
    property int winX: 32
    property int winY: 32
    property int winWidth: 200
    property int winHeight: 300
    property real overlayOpacity: 1.0
    property bool editMode: false

    visible: false
    color: "transparent"
    flags: Qt.FramelessWindowHint
           | Qt.WindowDoesNotAcceptFocus
           | (root.editMode ? 0 : Qt.WindowTransparentForInput)

    width: winWidth
    height: winHeight

    LS.Window.layer: LS.Window.LayerOverlay
    LS.Window.anchors: LS.Window.AnchorTop | LS.Window.AnchorLeft
    LS.Window.margins: geo.margins(root.winX, root.winY)
    LS.Window.keyboardInteractivity: LS.Window.KeyboardInteractivityNone
    LS.Window.activateOnShow: false

    Image {
        anchors.fill: parent
        source: "image://frames/" + root.mediaKey + "/" + root.frameTick
        cache: false
        asynchronous: false
        fillMode: Image.PreserveAspectFit
        smooth: true
        opacity: root.overlayOpacity
    }

    // --- konumlandırma modu görselleri ---
    Rectangle {
        anchors.fill: parent
        visible: root.editMode
        color: "transparent"
        border.color: "#59f7c8"
        border.width: 2
        radius: 4
    }

    Rectangle {
        visible: root.editMode
        anchors.top: parent.top
        anchors.topMargin: 4
        anchors.horizontalCenter: parent.horizontalCenter
        width: hintText.implicitWidth + 14
        height: 20
        radius: 4
        color: "#dd101418"
        z: 10

        Text {
            id: hintText
            anchors.centerIn: parent
            text: "sürükle"
            color: "#59f7c8"
            font.pixelSize: 11
        }
    }

    MouseArea {
        id: dragArea
        anchors.fill: parent
        enabled: root.editMode
        cursorShape: Qt.SizeAllCursor

        property real pressWinX: 0
        property real pressWinY: 0
        property real pressX: 0
        property real pressY: 0

        onPressed: (mouse) => {
            pressWinX = root.winX
            pressWinY = root.winY
            pressX = mouse.x
            pressY = mouse.y
        }

        onPositionChanged: (mouse) => {
            if (!pressed)
                return
            root.winX = Math.round(pressWinX + (mouse.x - pressX))
            root.winY = Math.round(pressWinY + (mouse.y - pressY))
        }

        onReleased: {
            backend.savePosition(root.mediaName, Math.round(root.winX), Math.round(root.winY))
        }
    }
}
