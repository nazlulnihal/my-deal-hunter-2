"""
Compatibility shim (`streamlit_app.py`) that delegates directly to `deal-sniper.py`
so both `streamlit run deal-sniper.py` and default `streamlit_app.py` Cloud settings work seamlessly.
"""

import runpy
from pathlib import Path

ENTRY = Path(__file__).resolve().parent / "deal-sniper.py"
runpy.run_path(str(ENTRY), run_name="__main__")
