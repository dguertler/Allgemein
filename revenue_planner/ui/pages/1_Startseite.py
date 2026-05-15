"""Start page: open / create a GmbH database."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import DATA_DIR, open_db, get_gmbh

