# file: main.py  (entrada para Railway / servidor propio)
import os
from fastapi.responses import FileResponse
from api.deobfuscate import app

ROOT = os.path.dirname(os.path.abspath(__file__))


@app.get("/")
async def home():
    return FileResponse(os.path.join(ROOT, "index.html"))
