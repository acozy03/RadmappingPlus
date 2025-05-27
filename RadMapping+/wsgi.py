import os
from app import create_app
import sys


try:

    app = create_app()

except Exception as e:
    import traceback
    print("PYTHONPATH:", sys.path, flush=True)
    print("🔥 APP FAILED TO START 🔥", flush=True)
    traceback.print_exc()
    raise e


