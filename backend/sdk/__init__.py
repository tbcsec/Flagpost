"""Flagpost module SDK (#390, ADR-0040) — author tooling for content packs / modules.

The build/sign/validate counterpart to the runtime install pipeline: it produces
the signed ``.fpmod`` artifacts that ``utils.marketplace_verify`` verifies and
``utils.content_packs`` installs. Repo-internal tooling — it reuses the backend's
manifest model and crypto rather than duplicating them; a standalone distribution
is a future step. Run as ``python -m sdk``.
"""
