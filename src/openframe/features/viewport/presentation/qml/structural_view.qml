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
    property bool pickingEnabled: false
    // Free-form 3D authoring: clicking the active work plane places a point
    // there (in view coordinates — Python converts back to structural and
    // then to the plane's own u/v); clicking an existing node instead
    // continues the current chain to it. Both only fire while this is true,
    // so the read-only model viewer's plain node-inspection clicks are unaffected.
    property bool planePickingEnabled: false
    property string planeKind: "xy"
    property real planeOffset: 0
    signal cameraModeChanged(string mode)
    signal nodePicked(int tag, real screenX, real screenY)
    signal planePicked(real viewX, real viewY, real viewZ)

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

    // Structural (x, y, z) -> view (x, z, -y); see Quick3DSceneBridge._view_coordinates.
    // A work plane is rendered as a thin slab spanning the two axes it holds
    // constant-free and pinned along the third at its offset, so its silhouette
    // in the view always matches what the 2D canvas would show for that plane.
    function planePosition() {
        if (root.planeKind === "xy") {
            return Qt.vector3d(sceneBridge.center_x, root.planeOffset, sceneBridge.center_z)
        } else if (root.planeKind === "xz") {
            return Qt.vector3d(sceneBridge.center_x, sceneBridge.center_y, -root.planeOffset)
        }
        return Qt.vector3d(root.planeOffset, sceneBridge.center_y, sceneBridge.center_z)
    }
    function planeScale() {
        let size = Math.max(sceneBridge.extent * 3, 10) / 100
        let thin = Math.max(sceneBridge.extent * 0.003, 0.004) / 100
        if (root.planeKind === "xy") {
            return Qt.vector3d(size, thin, size)
        } else if (root.planeKind === "xz") {
            return Qt.vector3d(size, size, thin)
        }
        return Qt.vector3d(thin, size, size)
    }

    function zoomBy(factor) {
        cameraDistance = Math.max(
            sceneBridge.extent * 0.18,
            Math.min(sceneBridge.extent * 25, cameraDistance * factor)
        )
    }

    View3D {
        id: view3d
        anchors.fill: parent
        camera: camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#f4f6f8"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
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

        // Three lights spaced 120 degrees apart in yaw (rather than one strong key
        // light) so that orbiting the camera never turns a whole face of the model
        // fully dark - each face is always lit by at least one of them.
        DirectionalLight {
            eulerRotation: Qt.vector3d(-35, -30, 0)
            brightness: 0.75
            castsShadow: false
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-35, 90, 0)
            brightness: 0.6
            castsShadow: false
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-35, 210, 0)
            brightness: 0.6
            castsShadow: false
        }

        PrincipledMaterial {
            id: groundMaterial
            baseColor: "#d8dee4"
            metalness: 0.0
            roughness: 0.95
        }

        // Coordinate-system axes through the structural origin (0,0,0), so a
        // student can always tell which way X/Y/Z point without hunting for a
        // node label. Structural (x, y, z) maps to view (x, z, -y) — see
        // Quick3DSceneBridge._view_coordinates — so only the vertical (Z) axis
        // lines up with the view's own Y without rotation.
        property real axisLength: Math.max(sceneBridge.extent * 1.2, 2.0)
        property real axisThickness: Math.max(sceneBridge.extent * 0.006, 0.008)
        PrincipledMaterial {
            id: xAxisMaterial
            baseColor: "#dc2626"
            metalness: 0.0
            roughness: 0.6
        }
        PrincipledMaterial {
            id: yAxisMaterial
            baseColor: "#16a34a"
            metalness: 0.0
            roughness: 0.6
        }
        PrincipledMaterial {
            id: zAxisMaterial
            baseColor: "#2563eb"
            metalness: 0.0
            roughness: 0.6
        }
        Model {
            // Structural X -> view +X
            source: "#Cylinder"
            eulerRotation: Qt.vector3d(0, 0, -90)
            scale: Qt.vector3d(axisThickness / 100, axisLength / 100, axisThickness / 100)
            materials: [xAxisMaterial]
            castsShadows: false
            receivesShadows: false
        }
        Model {
            // Structural Y -> view -Z
            source: "#Cylinder"
            eulerRotation: Qt.vector3d(-90, 0, 0)
            scale: Qt.vector3d(axisThickness / 100, axisLength / 100, axisThickness / 100)
            materials: [yAxisMaterial]
            castsShadows: false
            receivesShadows: false
        }
        Model {
            // Structural Z -> view +Y, already the cylinder's default axis.
            source: "#Cylinder"
            scale: Qt.vector3d(axisThickness / 100, axisLength / 100, axisThickness / 100)
            materials: [zAxisMaterial]
            castsShadows: false
            receivesShadows: false
        }

        PrincipledMaterial {
            id: activePlaneMaterial
            baseColor: "#3b82f6"
            opacity: 0.1
            metalness: 0.0
            roughness: 1.0
            cullMode: Material.NoCulling
        }
        Model {
            // The surface free-form 3D drawing clicks land on — visible and
            // pickable only while the draw tool is active (planePickingEnabled),
            // so it never gets in the way of orbiting or picking existing nodes.
            id: activePlaneModel
            source: "#Cube"
            visible: root.planePickingEnabled
            pickable: root.planePickingEnabled
            position: root.planePosition()
            scale: root.planeScale()
            materials: [activePlaneMaterial]
            castsShadows: false
            receivesShadows: false
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
            // MIDAS-style support glyphs: block=fixed, cone=pin, cone+rollers=roller.
            model: sceneBridge.supportSymbols
            delegate: Model {
                source: modelData.shape
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                rotation: Qt.quaternion(
                    modelData.qscalar,
                    modelData.qx,
                    modelData.qy,
                    modelData.qz
                )
                scale: Qt.vector3d(
                    modelData.scale_x / 100,
                    modelData.scale_y / 100,
                    modelData.scale_z / 100
                )
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        metalness: 0.0
                        roughness: 0.48
                    }
                ]
                castsShadows: false
                receivesShadows: false
                property int supportNodeTag: modelData.tag
                property string supportKind: modelData.kind
            }
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
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        opacity: modelData.opacity
                        metalness: 0.0
                        roughness: 0.55
                    }
                ]
                castsShadows: false
                receivesShadows: false
            }
        }

        Repeater3D {
            model: sceneBridge.nodes
            delegate: Model {
                source: "#Sphere"
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                scale: Qt.vector3d(
                    modelData.radius * 2 / 100,
                    modelData.radius * 2 / 100,
                    modelData.radius * 2 / 100
                )
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        opacity: modelData.opacity
                        metalness: 0.0
                        roughness: 0.55
                    }
                ]
                castsShadows: false
                receivesShadows: false
                pickable: true
                property int nodeTag: modelData.tag
            }
        }

        Repeater3D {
            model: sceneBridge.ghostMembers
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
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        opacity: modelData.opacity
                        metalness: 0.0
                        roughness: 0.55
                    }
                ]
                castsShadows: false
                receivesShadows: false
            }
        }

        Repeater3D {
            model: sceneBridge.ghostNodes
            delegate: Model {
                source: "#Sphere"
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                scale: Qt.vector3d(
                    modelData.radius * 2 / 100,
                    modelData.radius * 2 / 100,
                    modelData.radius * 2 / 100
                )
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        opacity: modelData.opacity
                        metalness: 0.0
                        roughness: 0.55
                    }
                ]
                castsShadows: false
                receivesShadows: false
            }
        }

        Repeater3D {
            // Each load contributes two flat entries (shaft + head), positioned and
            // rotated independently by the bridge - the same scheme members already
            // use - so there is no parent/child offset math that could leave a gap.
            model: sceneBridge.loadArrows
            delegate: Model {
                source: modelData.shape
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
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        metalness: 0.0
                        roughness: 0.4
                    }
                ]
                castsShadows: false
                receivesShadows: false
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.MiddleButton | Qt.LeftButton
        onClicked: function(mouse) {
            if (mouse.button !== Qt.LeftButton)
                return
            if (root.planePickingEnabled) {
                let result = view3d.pick(mouse.x, mouse.y)
                if (result.objectHit && result.objectHit.nodeTag !== undefined) {
                    // Clicked an existing node — continue the chain to it
                    // rather than dropping a new point on top of it.
                    root.nodePicked(result.objectHit.nodeTag, mouse.x, mouse.y)
                } else if (result.objectHit === activePlaneModel) {
                    root.planePicked(result.scenePosition.x, result.scenePosition.y, result.scenePosition.z)
                }
                return
            }
            if (!root.pickingEnabled)
                return
            let result = view3d.pick(mouse.x, mouse.y)
            if (result.objectHit && result.objectHit.nodeTag !== undefined)
                root.nodePicked(result.objectHit.nodeTag, mouse.x, mouse.y)
        }
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
