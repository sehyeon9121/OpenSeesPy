import QtQuick
import QtQuick3D

Item {
    id: root
    property real cameraYaw: 45
    property real cameraPitch: -25
    property real cameraDistance: Math.max(sceneBridge.extent * 2.8, 4.0)
    property real panX: 0
    property real panY: 0
    property real lastMouseX: 0
    property real lastMouseY: 0
    property bool panning: false
    signal cameraModeChanged(string mode)

    function setPreset(preset) {
        if (preset === "xy") {
            cameraYaw = 0
            cameraPitch = -89
        } else if (preset === "xz") {
            cameraYaw = 0
            cameraPitch = 0
        } else if (preset === "yz") {
            cameraYaw = 90
            cameraPitch = 0
        } else {
            cameraYaw = 45
            cameraPitch = -25
        }
        panX = 0
        panY = 0
        cameraDistance = Math.max(sceneBridge.extent * 2.8, 4.0)
        cameraModeChanged(preset)
    }

    function zoomBy(factor) {
        cameraDistance = Math.max(
            sceneBridge.extent * 0.18,
            Math.min(sceneBridge.extent * 25, cameraDistance * factor)
        )
    }

    View3D {
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#f4f6f8"
            antialiasingMode: SceneEnvironment.NoAA
        }

        PerspectiveCamera {
            id: camera
            parent: cameraPitchNode
            position: Qt.vector3d(0, 0, root.cameraDistance)
            clipNear: Math.max(sceneBridge.extent * 0.001, 0.001)
            clipFar: Math.max(sceneBridge.extent * 30, 100)
            fieldOfView: 38
        }

        Node {
            id: cameraTarget
            position: Qt.vector3d(
                sceneBridge.center_x + root.panX,
                sceneBridge.center_y + root.panY,
                sceneBridge.center_z
            )
            Node {
                id: cameraYawNode
                eulerRotation.y: root.cameraYaw
                Node {
                    id: cameraPitchNode
                    eulerRotation.x: root.cameraPitch
                }
            }
        }

        DirectionalLight {
            eulerRotation: Qt.vector3d(-42, -35, 0)
            brightness: 1.0
            castsShadow: false
        }

        PrincipledMaterial {
            id: memberMaterial
            baseColor: "#647789"
            metalness: 0.0
            roughness: 0.9
        }
        PrincipledMaterial {
            id: nodeMaterial
            baseColor: "#2877b7"
            metalness: 0.0
            roughness: 0.9
        }
        PrincipledMaterial {
            id: groundMaterial
            baseColor: "#d8dee4"
            metalness: 0.0
            roughness: 1.0
        }

        Model {
            source: "#Cube"
            position: Qt.vector3d(
                sceneBridge.center_x,
                sceneBridge.ground_y,
                sceneBridge.center_z
            )
            scale: Qt.vector3d(
                sceneBridge.ground_width / 100,
                Math.max(sceneBridge.extent * 0.012, 0.01) / 100,
                sceneBridge.ground_depth / 100
            )
            materials: [groundMaterial]
            castsShadows: false
            receivesShadows: false
        }

        Repeater3D {
            model: sceneBridge.members
            delegate: Model {
                source: "#Cube"
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                rotation: Qt.quaternion(
                    modelData.qscalar,
                    modelData.qx,
                    modelData.qy,
                    modelData.qz
                )
                scale: Qt.vector3d(
                    modelData.thickness / 100,
                    modelData.length / 100,
                    modelData.thickness / 100
                )
                materials: [memberMaterial]
                castsShadows: false
                receivesShadows: false
            }
        }

        Repeater3D {
            model: sceneBridge.nodes
            delegate: Model {
                source: "#Cube"
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                scale: Qt.vector3d(
                    modelData.radius * 2 / 100,
                    modelData.radius * 2 / 100,
                    modelData.radius * 2 / 100
                )
                materials: [nodeMaterial]
                castsShadows: false
                receivesShadows: false
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.MiddleButton
        onPressed: function(mouse) {
            root.lastMouseX = mouse.x
            root.lastMouseY = mouse.y
            root.panning = Boolean(mouse.modifiers & Qt.ShiftModifier)
        }
        onPositionChanged: function(mouse) {
            if (!(mouse.buttons & Qt.MiddleButton))
                return
            let dx = mouse.x - root.lastMouseX
            let dy = mouse.y - root.lastMouseY
            root.lastMouseX = mouse.x
            root.lastMouseY = mouse.y
            if (root.panning) {
                let scale = root.cameraDistance / Math.max(root.width, root.height, 1)
                root.panX -= dx * scale
                root.panY += dy * scale
            } else {
                root.cameraYaw += dx * 0.42
                root.cameraPitch = Math.max(-85, Math.min(85, root.cameraPitch - dy * 0.38))
            }
            root.cameraModeChanged("free")
        }
        onWheel: function(wheel) {
            let factor = wheel.angleDelta.y > 0 ? 0.88 : 1.14
            root.cameraDistance = Math.max(
                sceneBridge.extent * 0.18,
                Math.min(sceneBridge.extent * 25, root.cameraDistance * factor)
            )
            wheel.accepted = true
        }
    }
}
