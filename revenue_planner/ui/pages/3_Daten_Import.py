"""IST revenue data import page."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from database.importer import import_ist_umsatz, ensure_filialen_from_ist
import pandas as pd

