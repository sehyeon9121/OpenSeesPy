import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

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
    property int hoveredNodeTag: -1
    property real snapScreenX: 0
    property real snapScreenY: 0
    property real selectionStartX: 0
    property real selectionStartY: 0
    property real selectionCurrentX: 0
    property real selectionCurrentY: 0
    property bool selectionCandidate: false
    property bool selectionDragging: false
    property bool selectionCompletedDrag: false
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
    signal memberPicked(int tag, real screenX, real screenY)
    signal planePicked(real viewX, real viewY, real viewZ)
    // Hover equivalents of the two signals above, fired continuously (no
    // button held) while planePickingEnabled - drive the free-form 3D draw
    // mode's live rubber-band preview and node-snap. hoverCleared covers the
    // pointer landing on neither a node nor the active plane, or leaving the
    // viewport outright.
    signal nodeHovered(int tag)
    signal planeHovered(real viewX, real viewY, real viewZ)
    signal hoverCleared()
    signal selectionBoxFinished(string nodeTags, string memberTags, bool additive)
    //: A plain click (not a drag-box) in select mode that hit neither a node
    //: nor a member - the 3D-view equivalent of clicking empty space on the
    //: 2D canvas, which clears the current selection there.
    signal emptySpaceClicked()

    onPlanePickingEnabledChanged: {
        if (!planePickingEnabled)
            clearSnapFeedback()
    }

    function clearSnapFeedback() {
        hoveredNodeTag = -1
    }

    function showSnapFeedback(tag) {
        hoveredNodeTag = tag
        for (let index = 0; index < sceneBridge.nodes.length; ++index) {
            const node = sceneBridge.nodes[index]
            if (node.tag !== tag)
                continue
            const screen = view3d.mapFrom3DScene(Qt.vector3d(node.x, node.y, node.z))
            snapScreenX = screen.x
            snapScreenY = screen.y
            return
        }
    }

    // view3d.pick() only ever hits the exact rendered pixel, so a node whose
    // on-screen radius shrinks to a couple of pixels at any real zoom level
    // was effectively unpickable without landing dead-center - no magnet
    // effect at all, unlike the 2D canvas's generous pixel-radius snap
    // (StaticsDrawingCanvas._SNAP_PIXELS). Probing a small ring of nearby
    // points and taking the first node hit reproduces that same forgiving
    // snap here.
    function pickNearestNode(mx, my) {
        let exact = view3d.pick(mx, my)
        if (exact.objectHit && exact.objectHit.nodeTag !== undefined)
            return exact
        const radii = [4, 8, 14]
        const steps = 8
        for (let r = 0; r < radii.length; ++r) {
            for (let i = 0; i < steps; ++i) {
                const angle = (Math.PI * 2 * i) / steps
                const hit = view3d.pick(
                    mx + radii[r] * Math.cos(angle),
                    my + radii[r] * Math.sin(angle)
                )
                if (hit.objectHit && hit.objectHit.nodeTag !== undefined)
                    return hit
            }
        }
        return exact
    }

    function pointInSelection(point, left, top, right, bottom) {
        return point.x >= left && point.x <= right
            && point.y >= top && point.y <= bottom
    }

    function orientation2d(ax, ay, bx, by, cx, cy) {
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    }

    function segmentsCross(ax, ay, bx, by, cx, cy, dx, dy) {
        const o1 = orientation2d(ax, ay, bx, by, cx, cy)
        const o2 = orientation2d(ax, ay, bx, by, dx, dy)
        const o3 = orientation2d(cx, cy, dx, dy, ax, ay)
        const o4 = orientation2d(cx, cy, dx, dy, bx, by)
        return ((o1 >= 0 && o2 <= 0) || (o1 <= 0 && o2 >= 0))
            && ((o3 >= 0 && o4 <= 0) || (o3 <= 0 && o4 >= 0))
    }

    function memberTouchesSelection(a, b, left, top, right, bottom) {
        if (pointInSelection(a, left, top, right, bottom)
                || pointInSelection(b, left, top, right, bottom))
            return true
        return segmentsCross(a.x, a.y, b.x, b.y, left, top, right, top)
            || segmentsCross(a.x, a.y, b.x, b.y, right, top, right, bottom)
            || segmentsCross(a.x, a.y, b.x, b.y, right, bottom, left, bottom)
            || segmentsCross(a.x, a.y, b.x, b.y, left, bottom, left, top)
    }

    function finishSelectionBox(additive) {
        const left = Math.min(selectionStartX, selectionCurrentX)
        const right = Math.max(selectionStartX, selectionCurrentX)
        const top = Math.min(selectionStartY, selectionCurrentY)
        const bottom = Math.max(selectionStartY, selectionCurrentY)
        // Same vertical gesture used by the 2D canvas: a member with both
        // endpoints inside the box is always selected ("window"); dragging
        // upward ("crossing") additionally grabs members the box merely
        // touches, same as canvas_rendering.py's _select_in_rect.
        const crossing = selectionCurrentY < selectionStartY - 4
        let nodeTags = []
        let memberTags = []
        for (let index = 0; index < sceneBridge.nodes.length; ++index) {
            const node = sceneBridge.nodes[index]
            const point = view3d.mapFrom3DScene(Qt.vector3d(node.x, node.y, node.z))
            if (pointInSelection(point, left, top, right, bottom))
                nodeTags.push(node.tag)
        }
        for (let index = 0; index < sceneBridge.members.length; ++index) {
            const member = sceneBridge.members[index]
            const start = view3d.mapFrom3DScene(
                Qt.vector3d(member.start_x, member.start_y, member.start_z)
            )
            const end = view3d.mapFrom3DScene(
                Qt.vector3d(member.end_x, member.end_y, member.end_z)
            )
            const fullyInside = pointInSelection(start, left, top, right, bottom)
                && pointInSelection(end, left, top, right, bottom)
            if (fullyInside
                    || (crossing && memberTouchesSelection(start, end, left, top, right, bottom)))
                memberTags.push(member.tag)
        }
        selectionBoxFinished(nodeTags.join(","), memberTags.join(","), additive)
    }

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
            id: activePlaneMaterial
            baseColor: "#3b82f6"
            // Fully transparent - the plane still needs to stay "visible" (see
            // the Model below) for Quick3D's own pick() ray test to hit it,
            // but opacity 0 means nothing actually renders, so drawing no
            // longer paints a blue slab over the viewport. Picking is a
            // geometry/bounding-volume test, not a rendered-pixel test, so it
            // is unaffected by the material being invisible.
            opacity: 0.0
            metalness: 0.0
            roughness: 1.0
            cullMode: Material.NoCulling
        }
        Model {
            // The surface free-form 3D drawing clicks land on — pickable
            // only while the draw tool is active (planePickingEnabled), so
            // it never gets in the way of orbiting or picking existing
            // nodes. Kept "visible" (not just pickable) even though the
            // material above is fully transparent, since visible is what
            // Quick3D's pick() actually requires to consider it a candidate.
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

        // The ground plate used to render here as a flat Cube sized from
        // sceneBridge.ground_width/ground_depth, growing with the model's
        // extent every time a node was added far enough out - visually
        // distracting rather than helpful, so it is gone. The Python-side
        // ground_y/ground_width/ground_depth properties stay (see
        // quick3d_scene_bridge.py) since support glyphs still position
        // themselves relative to ground_y.

        // Origin coordinate plane - unlike the removed ground plate above,
        // this is a faint wireframe grid (Qt's own editor-grid helper), not
        // a filled/opaque surface, plus two thin colored lines through the
        // structural (0, 0, 0) origin so the user always has a fixed visual
        // anchor for "where is the origin" (requested: "0,0,0 부분의 좌표계
        // 평면으로 만들어주면 원점이 어딘지 편할 것 같아", MIDAS's own origin
        // grid given as a reference). AxisHelper's own built-in axis lines
        // are disabled (enableAxisLines: false) in favor of the two Models
        // below, so the colors match the 2D canvas's existing X=red/Y=green
        // convention (canvas_glyphs.py) exactly - AxisHelper's default
        // green line runs along view Y (structural +Z, vertical), not
        // structural Y, which would have been a confusing color clash here.
        AxisHelper {
            enableAxisLines: false
            enableXZGrid: true
            gridColor: "#c7d2e0"
            gridOpacity: 0.35
            scale: {
                const s = Math.max(sceneBridge.extent * 0.02, 0.05)
                return Qt.vector3d(s, s, s)
            }
        }
        Model {
            // Structural +X - red, matching the 2D canvas's X axis line.
            source: "#Cube"
            scale: Qt.vector3d(Math.max(sceneBridge.extent * 0.6, 2.0), 0.01, 0.01)
            materials: DefaultMaterial {
                lighting: DefaultMaterial.NoLighting
                diffuseColor: "#dc2626"
            }
        }
        Model {
            // Structural +Y - green, matching the 2D canvas's Y axis line.
            // View space maps structural Y to Z (see _view_coordinates), so
            // this line is scaled along view Z, not view X.
            source: "#Cube"
            scale: Qt.vector3d(0.01, 0.01, Math.max(sceneBridge.extent * 0.6, 2.0))
            materials: DefaultMaterial {
                lighting: DefaultMaterial.NoLighting
                diffuseColor: "#16a34a"
            }
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
            // Each list entry is already a fully self-contained box/cylinder
            // part (position, rotation, its own width_b x width_h) computed
            // in Python - Quick3DSceneBridge._member_parts. A plain member
            // is one part; an H/I section is three (web + two flanges),
            // each its own independent entry rather than a Node group
            // nesting several conditionally-visible children under one
            // parent transform - the same flat-list-of-parts shape
            // loadArrows/supportSymbols below already use, and Repeater3D
            // keeps that in sync with model changes far more reliably than
            // it does a nested multi-child delegate (a copied member
            // intermittently rendered as a bare hairline instead of its
            // real cross-section under the nested form).
            model: sceneBridge.members
            delegate: Model {
                property int memberTag: modelData.tag
                source: modelData.source
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                rotation: Qt.quaternion(
                    modelData.qscalar,
                    modelData.qx,
                    modelData.qy,
                    modelData.qz
                )
                scale: Qt.vector3d(
                    modelData.width_b / 100,
                    modelData.length / 100,
                    modelData.width_h / 100
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
                // Members participate in click picking only in selection
                // mode.  Keeping them non-pickable while drawing lets the
                // invisible work plane and nearby node snaps remain reachable.
                pickable: root.pickingEnabled
            }
        }

        Repeater3D {
            // Free-form 3D draw mode's rubber-band preview - see
            // Quick3DSceneBridge.set_preview_segment. Never pickable, so it
            // can never itself become a snap target while it follows the
            // cursor.
            model: sceneBridge.previewMembers
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
                property int nodeTag: modelData.tag
                property bool snapTarget: root.planePickingEnabled
                    && root.hoveredNodeTag === nodeTag
                source: "#Sphere"
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                scale: Qt.vector3d(
                    modelData.radius * 2 * (snapTarget ? 1.65 : 1) / 100,
                    modelData.radius * 2 * (snapTarget ? 1.65 : 1) / 100,
                    modelData.radius * 2 * (snapTarget ? 1.65 : 1) / 100
                )
                materials: [
                    PrincipledMaterial {
                        baseColor: snapTarget ? "#f59e0b" : modelData.color
                        opacity: modelData.opacity
                        metalness: 0.0
                        roughness: 0.55
                    }
                ]
                castsShadows: false
                receivesShadows: false
                pickable: true
            }
        }

        Repeater3D {
            // A translucent outer sphere makes a selected node unmistakable
            // even when its solid red core is partly hidden by several
            // members. It is deliberately non-pickable.
            model: sceneBridge.nodes
            delegate: Model {
                visible: modelData.selected === true
                source: "#Sphere"
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                scale: Qt.vector3d(
                    modelData.radius * 2.75 / 100,
                    modelData.radius * 2.75 / 100,
                    modelData.radius * 2.75 / 100
                )
                materials: [
                    PrincipledMaterial {
                        baseColor: "#ef4444"
                        opacity: 0.24
                        metalness: 0.0
                        roughness: 0.35
                        cullMode: Material.NoCulling
                    }
                ]
                castsShadows: false
                receivesShadows: false
                pickable: false
            }
        }

        Repeater3D {
            // Translucent undeformed reference overlay - a plain B x H box
            // is enough here (no flange/web split), since it is only a faint
            // low-opacity backdrop behind the actual deformed member.
            model: sceneBridge.ghostMembers
            delegate: Model {
                source: modelData.source
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                rotation: Qt.quaternion(
                    modelData.qscalar,
                    modelData.qx,
                    modelData.qy,
                    modelData.qz
                )
                scale: Qt.vector3d(
                    modelData.width_b / 100,
                    modelData.length / 100,
                    modelData.width_h / 100
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

        Repeater3D {
            // Loads tab's own case-based store (Load Case/Load Entry/Load
            // Combination) - entirely separate from loadArrows above, which
            // only ever reflects nodal_loads/element_loads. Same flat-parts
            // scheme (shaft/head/moment "bowtie" cone pair/distribution
            // line, each self-positioned) - see
            // Quick3DSceneBridge.loadEntryGlyphs.
            model: sceneBridge.loadEntryGlyphs
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

        Repeater3D {
            // Local-axis gizmo: two flat entries per 3D member (local y, local
            // z), off by default - see Quick3DSceneBridge.localAxisGizmos.
            model: sceneBridge.localAxisGizmos
            delegate: Model {
                source: "#Cylinder"
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

    Rectangle {
        id: nodeSnapIndicator
        objectName: "nodeSnapIndicator"
        z: 24
        visible: root.planePickingEnabled && root.hoveredNodeTag >= 0
        x: root.snapScreenX - width / 2
        y: root.snapScreenY - height / 2
        width: 30
        height: 30
        radius: 15
        color: "#33f59e0b"
        border.color: "#f59e0b"
        border.width: 2

        Rectangle {
            anchors.centerIn: parent
            width: 7
            height: 7
            radius: 3.5
            color: "#f59e0b"
        }
        Text {
            x: parent.width + 7
            anchors.verticalCenter: parent.verticalCenter
            text: "N" + root.hoveredNodeTag + "  SNAP"
            color: "#92400e"
            font.family: "Segoe UI"
            font.pixelSize: 12
            font.bold: true
            style: Text.Outline
            styleColor: "#fffaf0"
        }
    }

    Rectangle {
        id: selectionRubberBand
        objectName: "selectionRubberBand"
        z: 22
        visible: root.selectionDragging
        x: Math.min(root.selectionStartX, root.selectionCurrentX)
        y: Math.min(root.selectionStartY, root.selectionCurrentY)
        width: Math.abs(root.selectionCurrentX - root.selectionStartX)
        height: Math.abs(root.selectionCurrentY - root.selectionStartY)
        property bool crossing: root.selectionCurrentY < root.selectionStartY - 4
        color: crossing ? "#2516a34a" : "#252563eb"
        border.color: crossing ? "#16a34a" : "#2563eb"
        border.width: 2

        Text {
            x: 6
            y: parent.crossing ? -25 : 5
            text: parent.crossing ? "노드 + 부재 선택" : "노드 선택"
            color: parent.crossing ? "#166534" : "#1d4ed8"
            font.family: "Segoe UI"
            font.pixelSize: 12
            font.bold: true
            style: Text.Outline
            styleColor: "#ffffff"
        }
    }

    Canvas {
        // CAD-style orientation triad.  It lives in screen space, so zooming,
        // fitting or working far away from the structural origin never makes
        // it dominate the model.  Structural axes are mapped to the Quick3D
        // view as X=(1,0,0), Y=(0,0,-1), Z=(0,1,0), then projected through the
        // inverse of the orbit camera's yaw/pitch rotations.
        id: orientationGizmo
        objectName: "orientationGizmo"
        z: 10
        width: 104
        height: 104
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 12
        anchors.rightMargin: 12
        property real yaw: root.cameraYaw
        property real pitch: root.cameraPitch

        function projectedAxis(x, y, z) {
            let yawRadians = yaw * Math.PI / 180
            let pitchRadians = pitch * Math.PI / 180
            let cosYaw = Math.cos(yawRadians)
            let sinYaw = Math.sin(yawRadians)
            let cosPitch = Math.cos(pitchRadians)
            let sinPitch = Math.sin(pitchRadians)
            let cameraX = cosYaw * x - sinYaw * z
            let yawedZ = sinYaw * x + cosYaw * z
            let cameraY = cosPitch * y + sinPitch * yawedZ
            return { x: cameraX, y: -cameraY, depth: yawedZ }
        }

        function drawArrow(context, originX, originY, axis, color, label) {
            let length = 31
            let magnitude = Math.max(Math.sqrt(axis.x * axis.x + axis.y * axis.y), 0.28)
            let dx = axis.x / magnitude * length
            let dy = axis.y / magnitude * length
            let endX = originX + dx
            let endY = originY + dy
            let angle = Math.atan2(dy, dx)

            context.strokeStyle = color
            context.fillStyle = color
            context.lineWidth = 2.4
            context.lineCap = "round"
            context.beginPath()
            context.moveTo(originX, originY)
            context.lineTo(endX, endY)
            context.stroke()

            context.beginPath()
            context.moveTo(endX, endY)
            context.lineTo(endX - 7 * Math.cos(angle - 0.48), endY - 7 * Math.sin(angle - 0.48))
            context.lineTo(endX - 7 * Math.cos(angle + 0.48), endY - 7 * Math.sin(angle + 0.48))
            context.closePath()
            context.fill()

            context.font = "700 11px Segoe UI"
            context.textAlign = "center"
            context.textBaseline = "middle"
            context.fillText(label, endX + 9 * Math.cos(angle), endY + 9 * Math.sin(angle))
        }

        onPaint: {
            let context = getContext("2d")
            context.clearRect(0, 0, width, height)
            context.fillStyle = "rgba(255, 255, 255, 0.88)"
            context.strokeStyle = "rgba(196, 197, 213, 0.95)"
            context.lineWidth = 1
            context.beginPath()
            context.arc(52, 52, 46, 0, Math.PI * 2)
            context.fill()
            context.stroke()

            let axes = [
                { vector: projectedAxis(1, 0, 0), color: "#dc2626", label: "X" },
                { vector: projectedAxis(0, 0, -1), color: "#16a34a", label: "Y" },
                { vector: projectedAxis(0, 1, 0), color: "#2563eb", label: "Z" }
            ]
            axes.sort(function(a, b) { return b.vector.depth - a.vector.depth })
            for (let index = 0; index < axes.length; ++index)
                drawArrow(context, 52, 58, axes[index].vector, axes[index].color, axes[index].label)

            context.fillStyle = "#455568"
            context.beginPath()
            context.arc(52, 58, 3.2, 0, Math.PI * 2)
            context.fill()
        }
        onYawChanged: requestPaint()
        onPitchChanged: requestPaint()
        Component.onCompleted: requestPaint()
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.MiddleButton | Qt.LeftButton
        hoverEnabled: true
        onExited: {
            if (root.planePickingEnabled) {
                root.clearSnapFeedback()
                root.hoverCleared()
            }
        }
        onClicked: function(mouse) {
            if (mouse.button !== Qt.LeftButton)
                return
            if (root.selectionCompletedDrag) {
                root.selectionCompletedDrag = false
                return
            }
            if (root.planePickingEnabled) {
                let result = root.pickNearestNode(mouse.x, mouse.y)
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
            let result = root.pickNearestNode(mouse.x, mouse.y)
            if (result.objectHit && result.objectHit.nodeTag !== undefined) {
                root.nodePicked(result.objectHit.nodeTag, mouse.x, mouse.y)
            } else if (result.objectHit && result.objectHit.memberTag !== undefined) {
                root.memberPicked(result.objectHit.memberTag, mouse.x, mouse.y)
            } else {
                root.emptySpaceClicked()
            }
        }
        onPressed: function(mouse) {
            root.lastMouseX = mouse.x
            root.lastMouseY = mouse.y
            root.panning = Boolean(mouse.modifiers & Qt.ShiftModifier)
            if (mouse.button === Qt.LeftButton && root.pickingEnabled) {
                root.selectionStartX = mouse.x
                root.selectionStartY = mouse.y
                root.selectionCurrentX = mouse.x
                root.selectionCurrentY = mouse.y
                root.selectionCandidate = true
                root.selectionDragging = false
                root.selectionCompletedDrag = false
            }
        }
        onPositionChanged: function(mouse) {
            if (root.planePickingEnabled && !(mouse.buttons & Qt.MiddleButton)) {
                // Pure hover (no button held) while the draw tool is active -
                // resolve what the cursor is over so the caller can snap the
                // rubber-band preview onto an existing node, or follow the
                // active plane otherwise. Mirrors onClicked's own pick logic
                // exactly, so hover and click always agree on what counts as
                // a hit.
                let hover = root.pickNearestNode(mouse.x, mouse.y)
                if (hover.objectHit && hover.objectHit.nodeTag !== undefined) {
                    root.showSnapFeedback(hover.objectHit.nodeTag)
                    root.nodeHovered(hover.objectHit.nodeTag)
                } else if (hover.objectHit === activePlaneModel) {
                    root.clearSnapFeedback()
                    root.planeHovered(hover.scenePosition.x, hover.scenePosition.y, hover.scenePosition.z)
                } else {
                    root.clearSnapFeedback()
                    root.hoverCleared()
                }
            }
            if (root.selectionCandidate && (mouse.buttons & Qt.LeftButton)) {
                root.selectionCurrentX = mouse.x
                root.selectionCurrentY = mouse.y
                const dx = mouse.x - root.selectionStartX
                const dy = mouse.y - root.selectionStartY
                if (dx * dx + dy * dy >= 25)
                    root.selectionDragging = true
                if (root.selectionDragging)
                    return
            }
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
        onReleased: function(mouse) {
            if (mouse.button !== Qt.LeftButton || !root.selectionCandidate)
                return
            root.selectionCurrentX = mouse.x
            root.selectionCurrentY = mouse.y
            if (root.selectionDragging) {
                root.finishSelectionBox(Boolean(mouse.modifiers & Qt.ControlModifier))
                root.selectionCompletedDrag = true
            }
            root.selectionCandidate = false
            root.selectionDragging = false
        }
        onCanceled: {
            root.selectionCandidate = false
            root.selectionDragging = false
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
