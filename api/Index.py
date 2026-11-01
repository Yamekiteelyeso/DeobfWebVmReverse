# language: Python 3.10+
# file: api/index.py
import os, re, subprocess, json, sys
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Luraph VM Deobfuscator Web")

# Vercel solo permite escribir en /tmp
TMP_IN = "/tmp/temp_payload.lua"
TMP_OUT = "/tmp/temp_clean.luau"

# Ruta hacia la carpeta del deobfuscador en la raíz del proyecto
DEOBF_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "luraph-deobfuscator-py"))

class Payload(BaseModel):
    raw_text: str

def extract_vm_payload(raw_text: str) -> str:
    # Intentar parsear si es el JSON original de Luarmor
    try:
        data = json.loads(raw_text)
        if isinstance(data, list) and len(data) >= 2:
            lua_vm = data[1]
        else:
            lua_vm = raw_text
    except Exception:
        lua_vm = raw_text

    # Buscar el bloque que contiene el bytecode de la VM
    match = re.search(r'oH=\[=\[(.*?)\]=\]', lua_vm, re.DOTALL)
    if match:
        return match.group(1)
    
    match = re.search(r'\[=\[(.*?)\]=\]', lua_vm, re.DOTALL)
    if match:
        return match.group(1)

    raise ValueError("No se pudo encontrar el payload de la VM.")

@app.post("/api/deobfuscate")
async def deobfuscate(payload: Payload):
    try:
        vm_payload = extract_vm_payload(payload.raw_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    with open(TMP_IN, "w", encoding="utf-8") as f:
        f.write(vm_payload)

    if not os.path.exists(DEOBF_DIR):
        raise HTTPException(status_code=500, detail="Falta la carpeta luraph-deobfuscator-py en la raíz del proyecto.")

    try:
        # Usar sys.executable asegura que usamos el Python de Vercel
        result = subprocess.run(
            [sys.executable, "deobfuscate.py", TMP_IN, "-o", TMP_OUT],
            cwd=DEOBF_DIR,
            capture_output=True,
            text=True,
            timeout=10 # Límite de Vercel Hobby
        )
        
        if result.returncode != 0:
            output = result.stdout or result.stderr
            raise HTTPException(status_code=500, detail=f"Error del deobfuscador:\n{output}")

        if not os.path.exists(TMP_OUT):
            raise HTTPException(status_code=500, detail="El deobfuscador no generó el archivo de salida.")

        with open(TMP_OUT, "r", encoding="utf-8") as f:
            clean_code = f.read()

        if os.path.exists(TMP_IN): os.remove(TMP_IN)
        if os.path.exists(TMP_OUT): os.remove(TMP_OUT)

        return {"success": True, "code": clean_code}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout: El script es demasiado grande para Vercel Hobby (límite 10s).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
