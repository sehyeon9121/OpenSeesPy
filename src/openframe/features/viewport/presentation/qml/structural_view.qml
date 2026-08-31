import QtQuick
import QtQuick3D

Item {
    id: root
    // sceneBridge is cleared during QQuickWidget teardown while bindings still
    // evaluate once more - guard every read so offscreen tests do not spam
    // "Cannot read property 'extent' of null".
    readonly property bool bridgeReady: sceneBridge !== null && sceneBridge !== undefined
    readonly property real bridgeExtent: {
        if (bridgeReady)
            sceneBridge.sceneMetricsRevision
        return bridgeReady ? sceneBridge.extent : 1.0
    }
    readonly property real bridgeCenterX: {
        if (bridgeReady)
            sceneBridge.sceneMetricsRevision
        return bridgeReady ? sceneBridge.center_x : 0.0
    }
    readonly property real bridgeCenterY: {
        if (bridgeReady)
            sceneBridge.sceneMetricsRevision
        return bridgeReady ? sceneBridge.center_y : 0.0
    }
    readonly property real bridgeCenterZ: {
        if (bridgeReady)
            sceneBridge.sceneMetricsRevision
        return bridgeReady ? sceneBridge.center_z : 0.0
    }
    property real cameraYaw: 45
    property real cameraPitch: -25
    property real cameraDistance: Math.max(bridgeExtent * 2.8, 4.0)
    // Preserve the section proportions carried by width_b/width_h while
    // making the rendered member clearly subordinate to the node sphere.
    // Python keeps the unscaled dimensions for geometry, picking and node
    // sizing; this is deliberately a presentation-only reduction.
    readonly property real memberCrossSectionScale: 0.72
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
        if (!bridgeReady)
            return
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
    function tagIsSelected(tagList, tag) {
        for (let i = 0; i < tagList.length; ++i)
            if (tagList[i] === tag)
                return true
        return false
    }

    function nodeVisible(tag) {
        if (!bridgeReady || !sceneBridge.isolateActive)
            return true
        if (bridgeReady)
            sceneBridge.visibilityRevision
        return root.tagIsSelected(sceneBridge.isolateNodeTags, tag)
    }

    function memberVisible(tag) {
        if (!bridgeReady || !sceneBridge.isolateActive)
            return true
        if (bridgeReady)
            sceneBridge.visibilityRevision
        return root.tagIsSelected(sceneBridge.isolateMemberTags, tag)
    }

    function loadArrowVisible(part) {
        if (!bridgeReady || !sceneBridge.loadsVisible)
            return false
        if (bridgeReady)
            sceneBridge.visibilityRevision
        if (sceneBridge.loadFilter !== "all" && part.kind !== sceneBridge.loadFilter)
            return false
        if (sceneBridge.loadCaseFilter !== "all" && part.case_type !== sceneBridge.loadCaseFilter)
            return false
        return true
    }

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
        // The ray-cast probes above are still occluded by whatever geometry
        // sits in front of the node along that particular ray - a member's
        // cross-section can render several times wider on screen than the
        // node's own marker, so a big section can block every one of those
        // rays too, at any real zoom level. Nodes are the anchors members
        // attach to (not the reverse), so fall back to a depth-blind
        // nearest-node-by-screen-position search: if a node's projected
        // position really is this close to the cursor, it wins regardless
        // of what is rendered on top of it.
        if (root.bridgeReady) {
            let bestTag = -1
            let bestDistance = 16
            for (let index = 0; index < sceneBridge.nodes.length; ++index) {
                const node = sceneBridge.nodes[index]
                const point = view3d.mapFrom3DScene(Qt.vector3d(node.x, node.y, node.z))
                const dx = point.x - mx
                const dy = point.y - my
                const distance = Math.sqrt(dx * dx + dy * dy)
                if (distance < bestDistance) {
                    bestDistance = distance
                    bestTag = node.tag
                }
            }
            if (bestTag !== -1)
                return { objectHit: { nodeTag: bestTag } }
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
        if (!bridgeReady)
            return
        const left = Math.min(selectionStartX, selectionCurrentX)
        const right = Math.max(selectionStartX, selectionCurrentX)
        const top = Math.min(selectionStartY, selectionCurrentY)
        const bottom = Math.max(selectionStartY, selectionCurrentY)
        // Same vertical gesture as canvas_rendering.py's _select_in_rect under
        // the default "all" filter: downward ("window") grabs only nodes -
        // never members, even ones fully enclosed - so boxing a whole
        // building to pick many nodes at once does not silently sweep the
        // members in too. Upward ("crossing") still takes members the box
        // encloses or merely touches. The rubber-band label ("노드 선택" /
        // "노드 + 부재 선택") follows this same rule.
        const crossing = selectionCurrentY < selectionStartY - 4
        let nodeTags = []
        let memberTags = []
        for (let index = 0; index < sceneBridge.nodes.length; ++index) {
            const node = sceneBridge.nodes[index]
            const point = view3d.mapFrom3DScene(Qt.vector3d(node.x, node.y, node.z))
            if (pointInSelection(point, left, top, right, bottom))
                nodeTags.push(node.tag)
        }
        if (crossing) {
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
                        || memberTouchesSelection(start, end, left, top, right, bottom))
                    memberTags.push(member.tag)
            }
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
        cameraDistance = Math.max(bridgeExtent * 2.8, 4.0)
        cameraModeChanged(preset)
    }

    // Structural (x, y, z) -> view (x, z, -y); see Quick3DSceneBridge._view_coordinates.
    // A work plane is rendered as a thin slab spanning the two axes it holds
    // constant-free and pinned along the third at its offset, so its silhouette
    // in the view always matches what the 2D canvas would show for that plane.
    function planePosition() {
        if (root.planeKind === "xy") {
            return Qt.vector3d(bridgeCenterX, root.planeOffset, bridgeCenterZ)
        } else if (root.planeKind === "xz") {
            return Qt.vector3d(bridgeCenterX, bridgeCenterY, -root.planeOffset)
        }
        return Qt.vector3d(root.planeOffset, bridgeCenterY, bridgeCenterZ)
    }
    function planeScale() {
        let size = Math.max(bridgeExtent * 3, 10) / 100
        let thin = Math.max(bridgeExtent * 0.003, 0.004) / 100
        if (root.planeKind === "xy") {
            return Qt.vector3d(size, thin, size)
        } else if (root.planeKind === "xz") {
            return Qt.vector3d(size, size, thin)
        }
        return Qt.vector3d(thin, size, size)
    }

    function zoomBy(factor) {
        cameraDistance = Math.max(
            bridgeExtent * 0.18,
            Math.min(bridgeExtent * 25, cameraDistance * factor)
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
            clipNear: Math.max(bridgeExtent * 0.001, 0.001)
            clipFar: Math.max(bridgeExtent * 30, 100)
            fieldOfView: 38
        }

        Node {
            id: cameraTarget
            position: Qt.vector3d(
                bridgeCenterX + root.panX,
                bridgeCenterY + root.panY,
                bridgeCenterZ
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

        Repeater3D {
            // Mechanically descriptive support assemblies: anchored socket=fixed,
            // cone+joint=pin, aligned cylinders=roller, DOF bars/coils=custom/spring.
            model: bridgeReady ? sceneBridge.supportSymbols : []
            delegate: Model {
                property int supportNodeTag: modelData.tag
                visible: bridgeReady && sceneBridge.supportsVisible && root.nodeVisible(supportNodeTag)
                source: modelData.shape
                position: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                rotation: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.quaternion(
                        modelData.qscalar,
                        modelData.qx,
                        modelData.qy,
                        modelData.qz
                    )
                }
                scale: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(
                        modelData.scale_x / 100,
                        modelData.scale_y / 100,
                        modelData.scale_z / 100
                    )
                }
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        metalness: 0.0
                        roughness: 0.48
                    }
                ]
                castsShadows: false
                receivesShadows: false
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
            model: bridgeReady ? sceneBridge.members : []
            delegate: Model {
                property int memberTag: modelData.tag
                visible: (!bridgeReady
                    || !sceneBridge.timeHistoryDeformationActive
                    || sceneBridge.timeHistoryShowDeformed)
                    && root.memberVisible(memberTag)
                source: modelData.source
                position: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                rotation: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.quaternion(
                        modelData.qscalar,
                        modelData.qx,
                        modelData.qy,
                        modelData.qz
                    )
                }
                scale: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.vector3d(
                        modelData.width_b * root.memberCrossSectionScale / 100,
                        modelData.length / 100,
                        modelData.width_h * root.memberCrossSectionScale / 100
                    )
                }
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
            // Red overlay for the few selected members only.  Coloring every
            // member delegate via selectionRevision made a single click walk
            // thousands of QML bindings on large models.
            model: bridgeReady ? sceneBridge.selectedMemberHighlight : []
            delegate: Model {
                visible: !bridgeReady
                    || !sceneBridge.timeHistoryDeformationActive
                    || sceneBridge.timeHistoryShowDeformed
                source: modelData.source
                position: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                rotation: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.quaternion(
                        modelData.qscalar,
                        modelData.qx,
                        modelData.qy,
                        modelData.qz
                    )
                }
                scale: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.vector3d(
                        modelData.width_b * root.memberCrossSectionScale * 1.35 / 100,
                        modelData.length / 100,
                        modelData.width_h * root.memberCrossSectionScale * 1.35 / 100
                    )
                }
                materials: [
                    PrincipledMaterial {
                        baseColor: "#ef4444"
                        opacity: modelData.opacity
                        metalness: 0.0
                        roughness: 0.55
                    }
                ]
                castsShadows: false
                receivesShadows: false
                pickable: false
            }
        }

        Repeater3D {
            // Free-form 3D draw mode's rubber-band preview - see
            // Quick3DSceneBridge.set_preview_segment. Never pickable, so it
            // can never itself become a snap target while it follows the
            // cursor.
            model: bridgeReady ? sceneBridge.previewMembers : []
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
            // 3D N/V/M diagrams: each list entry is already a self-positioned
            // #Cylinder (outline / end connector) or #Cube (filled ribbon
            // slice) - same flat-parts scheme as loadArrows. Never pickable,
            // so a click through the ribbon still hits the member underneath.
            model: bridgeReady ? sceneBridge.forceDiagrams : []
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
                    modelData.width / 100,
                    modelData.length / 100,
                    modelData.thickness / 100
                )
                materials: [
                    PrincipledMaterial {
                        baseColor: modelData.color
                        opacity: modelData.opacity
                        lighting: PrincipledMaterial.NoLighting
                        cullMode: Material.NoCulling
                    }
                ]
                castsShadows: false
                receivesShadows: false
                pickable: false
            }
        }

        Repeater3D {
            // Floor-boundary click-picking's live yellow outline - one edge
            // per picked pair of boundary nodes plus a trailing edge that
            // follows the cursor, see Quick3DSceneBridge.
            // set_floor_boundary_outline. This replaced a single Model bound
            // to a custom filled-face geometry: that was a real mesh
            // (vertex buffer rebuilt and re-uploaded to the GPU on every
            // mouse-move) for what is really just a handful of line
            // segments, which made the whole viewport lag. A Repeater3D over
            // plain #Cylinder parts - the same pattern every other glyph
            // list here already uses - is far cheaper to rebuild every move.
            // Never pickable, so it can never shadow the nodes it connects.
            model: bridgeReady ? sceneBridge.floorBoundaryOutline : []
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
                        lighting: PrincipledMaterial.NoLighting
                    }
                ]
                castsShadows: false
                receivesShadows: false
                pickable: false
            }
        }

        Repeater3D {
            model: bridgeReady ? sceneBridge.nodes : []
            delegate: Model {
                property int nodeTag: modelData.tag
                property bool snapTarget: root.planePickingEnabled
                    && root.hoveredNodeTag === nodeTag
                property bool nodeSelected: {
                    if (bridgeReady)
                        sceneBridge.selectionRevision
                    return root.tagIsSelected(sceneBridge.selectedNodeTags, nodeTag)
                }
                visible: (!bridgeReady
                    || !sceneBridge.timeHistoryDeformationActive
                    || sceneBridge.timeHistoryShowDeformed)
                    && root.nodeVisible(nodeTag)
                source: "#Sphere"
                position: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                scale: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    const radiusScale = modelData.radius * 2 * (snapTarget ? 1.65 : 1) / 100
                    return Qt.vector3d(radiusScale, radiusScale, radiusScale)
                }
                materials: [
                    PrincipledMaterial {
                        baseColor: snapTarget ? "#f59e0b" : (nodeSelected ? "#ef4444" : modelData.color)
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
            model: bridgeReady ? sceneBridge.selectedNodeHalo : []
            delegate: Model {
                visible: !bridgeReady
                    || !sceneBridge.timeHistoryDeformationActive
                    || sceneBridge.timeHistoryShowDeformed
                source: "#Sphere"
                position: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                scale: {
                    if (bridgeReady) {
                        sceneBridge.geometryRevision
                        sceneBridge.deformationRevision
                    }
                    return Qt.vector3d(
                        modelData.radius * 2.75 / 100,
                        modelData.radius * 2.75 / 100,
                        modelData.radius * 2.75 / 100
                    )
                }
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
            model: bridgeReady ? sceneBridge.ghostMembers : []
            delegate: Model {
                visible: !bridgeReady
                    || !sceneBridge.timeHistoryDeformationActive
                    || sceneBridge.timeHistoryShowOriginal
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
            model: bridgeReady ? sceneBridge.ghostNodes : []
            delegate: Model {
                visible: !bridgeReady
                    || !sceneBridge.timeHistoryDeformationActive
                    || sceneBridge.timeHistoryShowOriginal
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
            // Time-history torsion markers: short local y/z arms that twist about
            // the member axis - see Quick3DSceneBridge.begin_torsion_marker_mode.
            model: bridgeReady ? sceneBridge.torsionMarkers : []
            delegate: Node {
                visible: bridgeReady
                    && sceneBridge.torsionMarkersVisible
                    && modelData.visible === true
                position: {
                    if (bridgeReady)
                        sceneBridge.torsionRevision
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                property real _armLength: modelData.length / 100
                property real _armThickness: modelData.thickness / 100

                Model {
                    source: "#Cylinder"
                    rotation: {
                        if (bridgeReady)
                            sceneBridge.torsionRevision
                        return Qt.quaternion(
                            modelData.y_qscalar,
                            modelData.y_qx,
                            modelData.y_qy,
                            modelData.y_qz
                        )
                    }
                    scale: Qt.vector3d(_armThickness, _armLength, _armThickness)
                    materials: [
                        PrincipledMaterial {
                            baseColor: "#2ecc71"
                            opacity: 0.95
                            metalness: 0.0
                            roughness: 0.45
                        }
                    ]
                    castsShadows: false
                    receivesShadows: false
                    pickable: false
                }

                Model {
                    source: "#Cylinder"
                    rotation: {
                        if (bridgeReady)
                            sceneBridge.torsionRevision
                        return Qt.quaternion(
                            modelData.z_qscalar,
                            modelData.z_qx,
                            modelData.z_qy,
                            modelData.z_qz
                        )
                    }
                    scale: Qt.vector3d(_armThickness, _armLength, _armThickness)
                    materials: [
                        PrincipledMaterial {
                            baseColor: "#3498db"
                            opacity: 0.95
                            metalness: 0.0
                            roughness: 0.45
                        }
                    ]
                    castsShadows: false
                    receivesShadows: false
                    pickable: false
                }
            }
        }

        Repeater3D {
            // Each load contributes two flat entries (shaft + head), positioned and
            // rotated independently by the bridge - the same scheme members already
            // use - so there is no parent/child offset math that could leave a gap.
            model: bridgeReady ? sceneBridge.loadArrows : []
            delegate: Model {
                visible: root.loadArrowVisible(modelData)
                source: modelData.shape
                position: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                rotation: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.quaternion(
                        modelData.qscalar,
                        modelData.qx,
                        modelData.qy,
                        modelData.qz
                    )
                }
                scale: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(
                        modelData.thickness / 100,
                        modelData.length / 100,
                        modelData.thickness / 100
                    )
                }
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
            model: bridgeReady ? sceneBridge.loadEntryGlyphs : []
            delegate: Model {
                visible: bridgeReady && sceneBridge.loadsVisible
                source: modelData.shape
                position: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                rotation: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.quaternion(
                        modelData.qscalar,
                        modelData.qx,
                        modelData.qy,
                        modelData.qz
                    )
                }
                scale: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(
                        modelData.thickness / 100,
                        modelData.length / 100,
                        modelData.thickness / 100
                    )
                }
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
            model: bridgeReady ? sceneBridge.localAxisGizmos : []
            delegate: Model {
                visible: bridgeReady && sceneBridge.localAxesVisible
                source: "#Cylinder"
                position: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(modelData.x, modelData.y, modelData.z)
                }
                rotation: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.quaternion(
                        modelData.qscalar,
                        modelData.qx,
                        modelData.qy,
                        modelData.qz
                    )
                }
                scale: {
                    if (bridgeReady)
                        sceneBridge.geometryRevision
                    return Qt.vector3d(
                        modelData.thickness / 100,
                        modelData.length / 100,
                        modelData.thickness / 100
                    )
                }
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

    Item {
        // MIDAS-style result numbers: 2D billboards, not 3D meshes, so a
        // value stays readable while the camera orbits. enabled:false so a
        // click through a label still orbits / picks the View3D underneath
        // rather than being swallowed by the Text.
        id: resultValueOverlay
        objectName: "resultValueOverlay"
        anchors.fill: parent
        z: 12
        enabled: false

        Repeater {
            model: bridgeReady ? sceneBridge.resultLabels : []
            delegate: Text {
                objectName: "resultValueLabel"
                property var screenPoint: {
                    root.cameraYaw
                    root.cameraPitch
                    root.cameraDistance
                    root.panX
                    root.panY
                    if (!root.bridgeReady)
                        return Qt.vector3d(-10000, -10000, 0)
                    return view3d.mapFrom3DScene(
                        Qt.vector3d(modelData.x, modelData.y, modelData.z)
                    )
                }
                visible: isFinite(screenPoint.x) && isFinite(screenPoint.y)
                x: screenPoint.x - implicitWidth / 2
                y: screenPoint.y - implicitHeight - 2
                text: modelData.text
                color: modelData.color
                font.family: "Segoe UI"
                font.pixelSize: 11
                font.weight: Font.DemiBold
                style: Text.Outline
                styleColor: "#fffffff0"
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
        // Global structural axes attached to the model's real (0, 0, 0)
        // origin. Unlike the corner orientation gizmo below, these axes are
        // projected from model space and therefore move, orbit and zoom with
        // the structure. Structural coordinates map to the Quick3D scene as
        // (x, y, z) -> (x, z, -y).
        id: worldOriginAxes
        objectName: "worldOriginAxes"
        z: 8
        anchors.fill: parent
        property real axisLength: Math.max(bridgeExtent * 0.18, 0.35)
        property real trackedYaw: root.cameraYaw
        property real trackedPitch: root.cameraPitch
        property real trackedDistance: root.cameraDistance
        property real trackedPanX: root.panX
        property real trackedPanY: root.panY
        property real trackedCenterX: bridgeCenterX
        property real trackedCenterY: bridgeCenterY
        property real trackedCenterZ: bridgeCenterZ

        function structuralPoint(x, y, z) {
            return view3d.mapFrom3DScene(Qt.vector3d(x, z, -y))
        }

        function usablePoint(point) {
            return isFinite(point.x) && isFinite(point.y)
        }

        function drawWorldArrow(context, origin, endpoint, color, label) {
            let dx = endpoint.x - origin.x
            let dy = endpoint.y - origin.y
            let screenLength = Math.sqrt(dx * dx + dy * dy)
            if (screenLength < 2)
                return

            let angle = Math.atan2(dy, dx)
            context.lineCap = "round"
            context.strokeStyle = "rgba(255, 255, 255, 0.92)"
            context.lineWidth = 5.2
            context.beginPath()
            context.moveTo(origin.x, origin.y)
            context.lineTo(endpoint.x, endpoint.y)
            context.stroke()

            context.strokeStyle = color
            context.fillStyle = color
            context.lineWidth = 2.6
            context.beginPath()
            context.moveTo(origin.x, origin.y)
            context.lineTo(endpoint.x, endpoint.y)
            context.stroke()
            context.beginPath()
            context.moveTo(endpoint.x, endpoint.y)
            context.lineTo(
                endpoint.x - 9 * Math.cos(angle - 0.48),
                endpoint.y - 9 * Math.sin(angle - 0.48)
            )
            context.lineTo(
                endpoint.x - 9 * Math.cos(angle + 0.48),
                endpoint.y - 9 * Math.sin(angle + 0.48)
            )
            context.closePath()
            context.fill()

            context.font = "700 12px Segoe UI"
            context.textAlign = "center"
            context.textBaseline = "middle"
            context.lineWidth = 3.5
            let labelX = endpoint.x + 12 * Math.cos(angle)
            let labelY = endpoint.y + 12 * Math.sin(angle)
            context.strokeStyle = "rgba(255, 255, 255, 0.96)"
            context.strokeText(label, labelX, labelY)
            context.fillText(label, labelX, labelY)
        }

        onPaint: {
            let context = getContext("2d")
            context.clearRect(0, 0, width, height)
            let origin = structuralPoint(0, 0, 0)
            let xEnd = structuralPoint(axisLength, 0, 0)
            let yEnd = structuralPoint(0, axisLength, 0)
            let zEnd = structuralPoint(0, 0, axisLength)
            if (!usablePoint(origin) || !usablePoint(xEnd)
                    || !usablePoint(yEnd) || !usablePoint(zEnd))
                return

            // Draw the axes farthest from the camera first so overlaps remain
            // legible around the origin.
            drawWorldArrow(context, origin, yEnd, "#16a34a", "Y")
            drawWorldArrow(context, origin, zEnd, "#2563eb", "Z")
            drawWorldArrow(context, origin, xEnd, "#dc2626", "X")

            context.fillStyle = "#334155"
            context.strokeStyle = "rgba(255, 255, 255, 0.96)"
            context.lineWidth = 3
            context.beginPath()
            context.arc(origin.x, origin.y, 4.2, 0, Math.PI * 2)
            context.stroke()
            context.fill()
            context.font = "600 10px Segoe UI"
            context.textAlign = "left"
            context.textBaseline = "top"
            context.lineWidth = 3
            context.strokeText("0,0,0", origin.x + 7, origin.y + 7)
            context.fillText("0,0,0", origin.x + 7, origin.y + 7)
        }

        onAxisLengthChanged: requestPaint()
        onTrackedYawChanged: requestPaint()
        onTrackedPitchChanged: requestPaint()
        onTrackedDistanceChanged: requestPaint()
        onTrackedPanXChanged: requestPaint()
        onTrackedPanYChanged: requestPaint()
        onTrackedCenterXChanged: requestPaint()
        onTrackedCenterYChanged: requestPaint()
        onTrackedCenterZChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Component.onCompleted: requestPaint()
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
        width: 112
        height: 118
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: 12
        anchors.rightMargin: 12
        property real yaw: root.cameraYaw
        property real pitch: root.cameraPitch
        property string hoverTarget: ""

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
            let labelX = endX + 9 * Math.cos(angle)
            let labelY = endY + 9 * Math.sin(angle)
            if (hoverTarget === label) {
                context.globalAlpha = 0.16
                context.beginPath()
                context.arc(labelX, labelY, 11, 0, Math.PI * 2)
                context.fill()
                context.globalAlpha = 1.0
            }
            context.fillText(label, labelX, labelY)
        }

        function axisEndpoint(axis) {
            let length = 31
            let magnitude = Math.max(Math.sqrt(axis.x * axis.x + axis.y * axis.y), 0.28)
            return {
                x: 56 + axis.x / magnitude * length,
                y: 56 + axis.y / magnitude * length
            }
        }

        function targetAt(px, py) {
            let candidates = [
                { name: "X", point: axisEndpoint(projectedAxis(1, 0, 0)) },
                { name: "Y", point: axisEndpoint(projectedAxis(0, 0, -1)) },
                { name: "Z", point: axisEndpoint(projectedAxis(0, 1, 0)) }
            ]
            let best = ""
            let bestDistance = 18
            for (let index = 0; index < candidates.length; ++index) {
                let dx = px - candidates[index].point.x
                let dy = py - candidates[index].point.y
                let distance = Math.sqrt(dx * dx + dy * dy)
                if (distance < bestDistance) {
                    bestDistance = distance
                    best = candidates[index].name
                }
            }
            let originDistance = Math.sqrt((px - 56) * (px - 56) + (py - 56) * (py - 56))
            return originDistance < 13 ? "ISO" : best
        }

        function activateTarget(target) {
            if (target === "X")
                root.setPreset("yz")
            else if (target === "Y")
                root.setPreset("xz")
            else if (target === "Z")
                root.setPreset("xy")
            else if (target === "ISO")
                root.setPreset("iso")
        }

        onPaint: {
            let context = getContext("2d")
            context.clearRect(0, 0, width, height)
            context.fillStyle = "rgba(255, 255, 255, 0.88)"
            context.strokeStyle = "rgba(196, 197, 213, 0.95)"
            context.lineWidth = 1
            context.beginPath()
            context.arc(56, 56, 46, 0, Math.PI * 2)
            context.fill()
            context.stroke()

            let axes = [
                { vector: projectedAxis(1, 0, 0), color: "#dc2626", label: "X" },
                { vector: projectedAxis(0, 0, -1), color: "#16a34a", label: "Y" },
                { vector: projectedAxis(0, 1, 0), color: "#2563eb", label: "Z" }
            ]
            axes.sort(function(a, b) { return b.vector.depth - a.vector.depth })
            for (let index = 0; index < axes.length; ++index)
                drawArrow(context, 56, 56, axes[index].vector, axes[index].color, axes[index].label)

            context.fillStyle = "#455568"
            context.beginPath()
            context.arc(56, 56, hoverTarget === "ISO" ? 5.2 : 3.2, 0, Math.PI * 2)
            context.fill()

            context.fillStyle = "#64748b"
            context.font = "700 9px Segoe UI"
            context.textAlign = "center"
            context.textBaseline = "middle"
            context.fillText("GLOBAL", 56, 111)
        }
        onYawChanged: requestPaint()
        onPitchChanged: requestPaint()
        Component.onCompleted: requestPaint()

        MouseArea {
            id: orientationMouseArea
            objectName: "orientationGizmoMouseArea"
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            hoverEnabled: true
            preventStealing: true
            cursorShape: parent.hoverTarget === ""
                ? Qt.ArrowCursor : Qt.PointingHandCursor

            onPositionChanged: function(mouse) {
                parent.hoverTarget = parent.targetAt(mouse.x, mouse.y)
                parent.requestPaint()
            }
            onExited: {
                parent.hoverTarget = ""
                parent.requestPaint()
            }
            onClicked: function(mouse) {
                let target = parent.targetAt(mouse.x, mouse.y)
                if (target !== "")
                    parent.activateTarget(target)
            }
        }
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
                bridgeExtent * 0.18,
                Math.min(bridgeExtent * 25, root.cameraDistance * factor)
            )
            wheel.accepted = true
        }
    }
}
