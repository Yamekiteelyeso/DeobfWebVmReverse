# language: Python 3.10+
# file: api/index.py
import os, re, subprocess, json, sys, zipfile, shutil
from fastapi import FastAPI, HTTPException, UploadFile, File, Form

app = FastAPI(title="Luraph VM Deobfuscator Web")

TMP_IN = "/tmp/payload.lua"
TMP_OUT = "/tmp/clean.luau"
TMP_ZIP = "/tmp/engine.zip"
EXTRACT_DIR = "/tmp/deobf_engine"

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
    # 1. Limpiar y extraer el ZIP
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

    # 2. Buscar deob.js o un archivo .py válido
    script_path = None
    script_type = None
    for root, _, files in os.walk(EXTRACT_DIR):
        if "deob.js" in files:
            script_path = os.path.join(root, "deob.js")
            script_type = "js"
            break
        for file in files:
            if file.endswith(".py") and file != "build_luau.py": 
                script_path = os.path.join(root, file)
                script_type = "py"
                break
        if script_path: break

    if not script_path:
        raise HTTPException(status_code=400, detail="No se encontró deob.js en el ZIP.")

    # 3. Extraer el dump
    try:
        vm_payload = extract_vm_payload(raw_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    with open(TMP_IN, "w", encoding="utf-8") as f:
        f.write(vm_payload)

    # 4. Ejecutar el script (Node o Python)
    try:
        work_dir = os.path.dirname(script_path)

        if script_type == "js":
            # Instalar dependencias del package.json si existen (rápido)
            pkg_path = os.path.join(work_dir, "package.json")
            if os.path.exists(pkg_path):
                subprocess.run("npm install --silent", cwd=work_dir, shell=True, timeout=10, capture_output=True)

            # Ejecutar deob.js
            cmd = ["node", script_path, TMP_IN, TMP_OUT]
        else:
            cmd = [sys.executable, script_path, TMP_IN, "-o", TMP_OUT]

        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=10
        )

        # Si el script imprime directo en consola en vez de guardar archivo
        if result.returncode == 0 and result.stdout.strip() and not os.path.exists(TMP_OUT):
                return {"success": True, "code": result.stdout.strip()}

        if result.returncode != 0:
            output = result.stderr or result.stdout
            raise HTTPException(status_code=500, detail=f"Error del deobfuscador:\n{output[-500:]}")

        if not os.path.exists(TMP_OUT):
            raise HTTPException(status_code=500, detail="El script terminó pero no generó el archivo de salida.")

        with open(TMP_OUT, "r", encoding="utf-8") as f:
            clean_code = f.read()

        if os.path.exists(TMP_IN): os.remove(TMP_IN)
        if os.path.exists(TMP_OUT): os.remove(TMP_OUT)

        return {"success": True, "code": clean_code}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout: El script tardó más de 10s.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
