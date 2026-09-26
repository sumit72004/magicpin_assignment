"""
Application entry point compatibility bridge for Render / Gunicorn / Uvicorn.
Exports 'app' from bot.py.
"""

import os
from bot import app

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
