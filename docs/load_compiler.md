# Common Load Compiler

`openframe.features.analysis.loads` is the engine-independent seam between domain
loads and the future solver/export adapters. This change does **not** wire either
adapter or change the UI. It adds only compiler/IR, numerical tests and this contract.

## Inputs and output

```python
from openframe.core.domain.load_entry import SelfWeightEntry
from openframe.features.analysis.loads import compile_loads

# model contains the final mesh, including generated ShellQuad nodes/tags.
# selected_entries are already filtered and factored by the caller.
plan = compile_loads(
    model,
    entries=selected_entries,
    self_weight=SelfWeightEntry(),  # global -Z; 3D example
    gravity_acceleration=9.80665,  # example ONLY for length=m and time=s
)

# Future builders first create subdivisions, then resolve every abstract target.
for source_element_tag, count in plan.required_subdivisions:
    print(source_element_tag, count)
for load in plan.nodal_loads:
    print(load.node_tag, load.force, load.moment, load.source)
for load in plan.element_loads:
    print(load.target, load.kind, load.components, load.source)
for warning in plan.warnings:
    print(warning.code, warning.message, warning.source)
```

In 2D use `SelfWeightEntry(factor_y=-1, factor_z=0)`. No dimension, gravity or
unit is guessed. `self_weight=None` means no additional self-weight generation.
Each existing `NodalLoad`, `UniformElementLoad`, `PointElementLoad` is compiled;
passed `LoadEntry` objects and optional self weight are **additional** loads.
Do not pass entries already expanded into the model by `canvas.build_model()`;
that would apply the same physical load twice. Use an authoring model plus raw
selected entries OR the expanded analysis loads, never both representations of
the same input. `hidden=True` affects display only and does not remove a load.

`CompiledLoadPlan` and its records are frozen dataclasses containing tuples.
`CompiledNodalLoad.force/moment` are global xyz vectors, not an engine ndf array.
`CompiledElementLoad.components` is local `(wx, wy, wz)` (or `(Px, Py, Pz)` for
point forces), **not** an OpenSees positional argument tuple. LoadSource retains
entry ID, case ID, pattern tag, case type and original element tag where available.
The plan retains separate contributions; adapters must sum within the correct
case/pattern and validate nonzero DOFs rather than truncate them.

## Capability policy

`element_load_handling(element, kind)` returns `native_element`,
`equivalent_nodal` or `unsupported`. It is the family-level policy; compilation
also validates dimension, transform, range and beam subtype.

| Family | Distributed load | Point force | Self weight |
|---|---|---|---|
| Beam/frame | Native uniform; legacy 2D full trapezoid subdivision | Native | Native uniform |
| Truss family | Two-node consistent force integral | Two-node interpolation | Same distributed integral |
| ShellQuad | Unsupported member line load | Unsupported member point load | Rectangular A/4 nodal distribution |

The truss discriminator deliberately agrees with existing `_element_family`:
`"truss" in element.element_type.lower()`. Cable, tension-only and compression-only
are behaviors on those elements, not separate OpenSees type names. Known frame
aliases and beam-column types are allowlisted; unknown types are not blindly
accepted via the old catch-all frame classification.

3D Corotational beam loads, partial dispBeamColumn loads, 3D beam trapezoids,
partial beam trapezoids, member moments and raw floor loads raise a compile error.
Floor tributary distribution and member-moment mesh insertion remain upstream.
The compiler does not rely on a possibly newer engine's trapezoid syntax: it
preserves this repository's established 40-segment 2D approximation.

## Shape functions and partial spans

Let `a,b` be the loaded interval measured from node i in physical lengths;
`L` is the full undeformed chord length. End intensities belong to **a and b**, not
to x=0 and x=L when the load is partial:

```text
w(x) = w_a + (w_b - w_a) (x-a)/(b-a)
N_i(x) = 1 - x/L; N_j(x) = x/L
F_i = integral[a,b] N_i(x) w_global(x) dx
F_j = integral[a,b] N_j(x) w_global(x) dx
```

Two-point Gauss integration is exact because the integrand is quadratic. The
same kernel handles full/partial uniform/trapezoidal loading, axial/transverse
components and signed loads whose resultant is zero but first moment is not.
This preserves both total force and first moment without adding rotational loads
to a truss. It does not reproduce cable sag, internal bending or follower-load
behavior. Cable/tension-only conversions return `cable_sag_not_represented`.
Absolute positions are divided by L once; reversed, zero-width, nonfinite or
out-of-range intervals fail explicitly instead of being clipped or ignored.

Axes compose existing `auto_reference_vector`, `rotate_about_axis`, and
`local_y_z_axes`; authored models match `_reference_vector`/`_local_axes`. Imported
explicit vecxz is reused without applying local_axis_angle twice. The future
builder MUST use those same axes/transform. Offset-dependent projection and
offset subdivision are rejected until the flexible-axis convention is shared;
already-local native uniform/point loads can still be forwarded unchanged.

## Density is not currently a uniform domain convention

- Line members: `Element.properties['density']` is **unit weight F/L³**.
  Evidence: `canvas_model_build._self_weight_local`,
  `canvas_units._UNIT_WEIGHT_PROPERTY_KEYS`, and `section_material_panel` store
  and convert it as unit weight. Use `density*A*L`, without another g.
- Shells: `WallPanel.density` is passed unchanged by `statics.surfaces` to
  `ElasticMembranePlateSection.rho`, whose meaning is **mass/volume**.
  Use `density*thickness*quad_area*g`. Require explicit positive finite
  `gravity_acceleration` in the model's L/T² units for nonzero shell weight.
  Density must already be in coherent model mass/volume units, not arbitrarily
  kg/m³ in a kN-based model. Do not infer its meaning from its numerical value.

Current nonzero wall-density authoring/conversion is not unified with the line
material UI. Changing that schema or the shell mass builder is follow-up work.
The compiler preserves the current shell section contract, rather than silently
reinterpreting a mass input as force density. Explicit zero density creates no
weight; absent line A/density, negative density and invalid geometry are errors.

`rectangular_quad_nodal_areas` reuses the existing rectangular mesher validator.
It returns four A/4 contributions. Shared mesh nodes receive contributions from
all incident quads. Warped/skewed/degenerate quads are rejected, not approximated
as rectangles. Future consistent area integration can replace this one function.

## Builder/exporter integration requirements

1. Finalize the mesh and active/factored physical loads **before** compilation.
2. Compile once; both consumers use the same plan. Do not repeat load physics.
3. Build `plan.required_subdivisions` and map `ElementLoadTarget` to actual tags.
   A target with `segment_index != None` never means the original element exists.
   All companion uniform, partial, point and self-weight loads are routed onto
   the same subdivision, even if only one load required it. Preserve source end
   releases/material/geometry while building segments and result mappings.
4. Native start/end ratios and point position are relative to that **target**.
   `target.source_span` describes its fraction of the original member.
5. Group by case/pattern, resolve nodal force/moment DOFs and native argument
   order in the adapter. Repeated node contributions add; they must not overwrite.
6. Surface compile errors and warnings; never emit a partially compiled plan.
7. Use identical axes/transform in both builders. A transform override after
   compilation requires recompilation/capability validation; 3D Corotational
   native eleLoads are not supported.
8. On integrating, remove the legacy canvas self-weight/entry expansion for
   inputs supplied raw, preventing double counting. Keep floor lowering upstream.

The 2D trapezoid approximation preserves the existing midpoint intensities and
exact resultant, with a small first-moment error reported as
`beam_trapezoid_midpoint_approximation`. No engine tag arithmetic lives in the IR.

## Validation

`tests/unit/test_load_compiler.py` checks resultants and moments, partial-load
centroids, signed loads, existing axis parity, explicit vecxz, unit conversions,
truss and meshed-shell self weight, mixed models, solver/exporter native argument
parity, subdivision companion loads, provenance, immutability, invalid inputs,
unsupported combinations and import independence from OpenSees/PySide6.

Authoritative backend contracts consulted:
- [OpenSees eleLoad](https://opensees.github.io/OpenSeesDocumentation/user/manual/model/pattern/PlainPatternloadcommands/eleLoad.html)
- [ElasticMembranePlateSection density](https://opensees.berkeley.edu/wiki/index.php/Elastic_Membrane_Plate_Section)
