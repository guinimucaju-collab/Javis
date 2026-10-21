"""Javis — assistente local de segunda cérebro.

Este arquivo é apenas o ponto de entrada: o código mora no pacote `javis/`,
dividido em módulos (config, storage, llm, theme, glass, ui).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from javis.ui import main  # noqa: E402

if __name__ == "__main__":
    main()
