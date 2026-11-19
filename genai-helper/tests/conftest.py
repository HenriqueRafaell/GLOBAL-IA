import sys
from pathlib import Path

# garante que `app` e `tests` sejam importáveis rodando `pytest` de dentro de genai-helper/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
