"""OpenSees commands for surface members, shared by the in-process solver
and the script exporter.

Shear walls and slabs are not a new ``AnalysisModule``. Linear / nonlinear
static and time-history keep their packages; those runners call into this
module the same way they already call ``_build_one_truss_element`` for
trusses. ``_element_family`` today returns only ``"truss"`` or ``"frame"`` -
a third family lands here rather than by stuffing shells into the frame
branch.

``features.analysis.statics.solver`` and ``opensees_script_export`` are the
callers. The GUI must not import this to talk to OpenSees.

Do not emit ``ops.element`` until the element type and material/section
mapping are specified.
"""
