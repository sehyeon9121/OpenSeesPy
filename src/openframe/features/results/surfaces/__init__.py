"""Qt-free surface-result calculations (shell stress, table rows).

Member fibre stress lives in ``features/results/stress.py``; this package is
the same idea for walls and slabs. Colour mapping and widgets stay in
``features/results/presentation/`` (and the 3D bridge receives payloads,
it does not import this package - ``features.results`` already imports
``features.viewport``).

``ElementResult.local_forces`` is beam end forces (6 or 12 numbers). Shell
stresses do not stretch that tuple; they get their own result shape when
the solver contract is specified.
"""
