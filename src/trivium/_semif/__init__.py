"""Vendored from semif (https://github.com/theoleecj/semif) at commit
1f2dea3e25379f9dfc98cb83c324f00ab5deda37, MIT License, Copyright (c) 2026 TheoLeeCJ (see LICENSE here).

Copied unchanged so Trivium can be installed from PyPI, which does not allow git dependencies, and so
the MLX path no longer pulls in PyTorch. Modules: core, direct, shared (PyTorch scoring), mlx_backend
(Apple Silicon), llamacpp_backend (CPU, GGUF). To update, copy the same files from a newer commit and
re-run `ask eval` against the previous results.
"""
