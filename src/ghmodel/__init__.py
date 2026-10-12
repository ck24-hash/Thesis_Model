"""Techno-economic dispatch model for greenhouse heat, CO2 and electricity (PyPSA)."""
import logging
import warnings

from .config import Params, INPUT_COLUMNS, OPTIONAL_COLUMNS

logging.getLogger("pypsa").setLevel(logging.WARNING)
logging.getLogger("linopy").setLevel(logging.WARNING)
warnings.filterwarnings("ignore", category=FutureWarning, module="pypsa")   # pandas 3 string-dtype notice
