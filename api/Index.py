# language: Python 3.10+
# file: api/index.py
import os, re, subprocess, json, sys, zipfile, shutil
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

app = FastAPI(title="Luraph VM Deobfuscator Web")

TMP_IN = "/tmp/payload.lua"
TMP_OUT = "/tmp/clean.luau"
TMP_ZIP = "/tmp/engine.zip"
EXTRACT_DIR = "/tmp/deobf_engine"

class Payload(BaseModel):
    raw_text: str

def extract_vm_payload(raw_text: str) -> str:
    try:
        data = json.loads(raw_text)
        if isinstance(data, list) and len(data) >= 2:
            lua_vm = data[1]
        else:
            lua_vm = raw_text
    except Exception:
        lua_vm = raw_text

    match = re.search(r'oH=\[=\[(.*?)\]=\]', lua_vm, re.DOTALL)
    if match:
        return match.group(1)
    
    match = re.search(r'\[=\[(.*?)\]=\]', lua_vm, re.DOTALL)
    if match:
        return match.group(1)

    raise ValueError("No se pudo encontrar el payload de la VM (string oH).")

@app.post("/api/deobfuscate")
async def deobfuscate(raw_text: str = Form(...), engine_zip: UploadFile = File(...)):
    # 1. Guardar y extraer el ZIP
    if os.path.exists(EXTRACT_DIR):
        shutil.rmtree(EXTRACT_DIR)
    os.makedirs(EXTRACT_DIR, exist_ok=True)

    with open(TMP_ZIP, "wb") as f:
        f.write(await engine_zip.read())

    try:
        with zipfile.ZipFile(TMP_ZIP, 'r') as zip_ref:
            zip_ref.extractall(EXTRACT_DIR)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al descomprimir el ZIP: {str(e)}")

    # 2. Buscar el script principal de Python dentro del ZIP
    main_script = None
    for root, _, files in os.walk(EXTRACT_DIR):
        for file in files:
            if file.endswith(".py"):
                # Buscamos nombres comunes del deobfuscador
                if file in ["main.py", "deobfuscate.py", "run.py", "index.py"]:
                    main_script = os.path.join(root, file)
                    break
        if main_script: break

    if not main_script:
        # Fallback: coger el primer .py que encontremos
        for root, _, files in os.walk(EXTRACT_DIR):
            for file in files:
                if file.endswith(".py"):
                    main_script = os.path.join(root, file)
                    break
            if main_script: break

    if not main_script:
        raise HTTPException(status_code=400, detail="No se encontró ningún archivo .py en el ZIP.")

    # 3. Extraer el payload del dump de Luarmor
    try:
        vm_payload = extract_vm_payload(raw_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    with open(TMP_IN, "w", encoding="utf-8") as f:
        f.write(vm_payload)

    # 4. Ejecutar el script del usuario
    try:
        # Le pasamos el archivo de entrada y el de salida como argumentos
        result = subprocess.run(
            [sys.executable, main_script, TMP_IN, "-o", TMP_OUT],
            cwd=os.path.dirname(main_script),
            capture_output=True,
            text=True,
            timeout=10 # Límite de Vercel Hobby
        )
        
        # Si falla con -o, intentamos sin -o (por si el script es diferente)
        if result.returncode != 0 or not os.path.exists(TMP_OUT):
            result = subprocess.run(
                [sys.executable, main_script, TMP_IN],
                cwd=os.path.dirname(main_script),
                capture_output=True,
                text=True,
                timeout=10
            )
            # Si imprimió el resultado en consola (stdout) en vez de guardarlo en archivo
            if result.returncode == 0 and result.stdout.strip():
                clean_code = result.stdout.strip()
                return {"success": True, "code": clean_code}

        if result.returncode != 0:
            output = result.stderr or result.stdout
            raise HTTPException(status_code=500, detail=f"Error del deobfuscador:\n{output[-500:]}")

        if not os.path.exists(TMP_OUT):
            raise HTTPException(status_code=500, detail="El script terminó pero no generó el archivo de salida ni imprimió el código.")

        with open(TMP_OUT, "r", encoding="utf-8") as f:
            clean_code = f.read()

        # Limpieza
        if os.path.exists(TMP_IN): os.remove(TMP_IN)
        if os.path.exists(TMP_OUT): os.remove(TMP_OUT)

        return {"success": True, "code": clean_code}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout: El script tardó más de 10s (límite de Vercel).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
