import os
from app import create_app

try:

    app = create_app()

except Exception as e:
    import traceback
    print("🔥 APP FAILED TO START 🔥", flush=True)
    traceback.print_exc()
    raise e
