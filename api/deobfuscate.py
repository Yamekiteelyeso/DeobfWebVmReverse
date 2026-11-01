# language: Python 3.10+
# file: api/deobfuscate.py
import os, re, subprocess, json, sys, zipfile, shutil, tempfile, time
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form

app = FastAPI(title="Luraph VM Deobfuscator Web")

# Si no se sube ZIP, se usa esta carpeta del repo (engine/deob.js)
BUNDLED_ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")

TOTAL_TIMEOUT = 85  # segundos máximos entre todos los intentos


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


def build_candidates(raw_text: str):
    """Primero el payload extraído (lógica original); si falla, el texto completo."""
    candidates = []
    try:
        candidates.append(extract_vm_payload(raw_text))
    except Exception:
        pass
    if raw_text.strip() and raw_text not in candidates:
        candidates.append(raw_text)
    return candidates


def find_script(root_dir: str):
    # Primero deob.js en cualquier carpeta, luego cualquier .py válido
    for root, _, files in os.walk(root_dir):
        if "deob.js" in files:
            return os.path.join(root, "deob.js"), "js"
    for root, _, files in os.walk(root_dir):
        for file in files:
            if file.endswith(".py") and file != "build_luau.py":
                return os.path.join(root, file), "py"
    return None, None


def make_executable(root_dir: str):
    # zipfile.extractall no conserva permisos: sin esto bin/luau no se puede ejecutar
    for root, _, files in os.walk(root_dir):
        if os.path.basename(root) == "bin":
            for f in files:
                if not f.endswith(".exe") and f != "readme.txt":
                    try:
                        os.chmod(os.path.join(root, f), 0o755)
                    except Exception:
                        pass


def run_engine(script_path, script_type, work_dir, payload, tmp_in, tmp_out, timeout):
    """Devuelve (codigo, error). codigo es None si falló o salió vacío."""
    with open(tmp_in, "w", encoding="utf-8") as f:
        f.write(payload)
    if os.path.exists(tmp_out):
        os.remove(tmp_out)

    if script_type == "js":
        cmd = ["node", script_path, tmp_in, "-o", tmp_out]
    else:
        cmd = [sys.executable, script_path, tmp_in, "-o", tmp_out]

    env = dict(os.environ)
    env.setdefault("PYTHON_BIN", sys.executable)

    try:
        result = subprocess.run(
            cmd, cwd=work_dir, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"Timeout: El script tardó más de {TOTAL_TIMEOUT}s.")

    if result.returncode != 0:
        output = result.stderr or result.stdout
        return None, f"Error del deobfuscador:\n{output[-500:]}"

    if os.path.exists(tmp_out):
        with open(tmp_out, "r", encoding="utf-8", errors="replace") as f:
            code = f.read()
        if code.strip():
            return code, None
        return None, "El deobfuscador generó un resultado vacío.\n" + (result.stderr or "")[-400:]

    # Si el script imprime directo en consola en vez de guardar archivo
    if result.stdout.strip():
        return result.stdout.strip(), None

    return None, "El script terminó pero no generó el archivo de salida.\n" + (result.stderr or "")[-400:]


@app.post("/api/deobfuscate")
async def deobfuscate(raw_text: str = Form(...), engine_zip: Optional[UploadFile] = File(None)):
    work = tempfile.mkdtemp(prefix="deobf_")
    try:
        tmp_in = os.path.join(work, "payload.lua")
        tmp_out = os.path.join(work, "clean.luau")
        extract_dir = os.path.join(work, "engine")
        os.makedirs(extract_dir, exist_ok=True)

        # 1. Motor: ZIP subido o carpeta engine/ del repo
        if engine_zip is not None and getattr(engine_zip, "filename", None):
            tmp_zip = os.path.join(work, "engine.zip")
            with open(tmp_zip, "wb") as f:
                f.write(await engine_zip.read())
            try:
                with zipfile.ZipFile(tmp_zip, "r") as zip_ref:
                    zip_ref.extractall(extract_dir)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Error al descomprimir el ZIP: {str(e)}")
        elif os.path.isdir(BUNDLED_ENGINE):
            shutil.rmtree(extract_dir)
            shutil.copytree(BUNDLED_ENGINE, extract_dir)
        else:
            raise HTTPException(status_code=400, detail="Sube el .zip del motor (o incluye la carpeta engine/ en el repo).")

        make_executable(extract_dir)

        # 2. Buscar deob.js o un archivo .py válido
        script_path, script_type = find_script(extract_dir)
        if not script_path:
            raise HTTPException(status_code=400, detail="No se encontró deob.js en el ZIP.")

        if script_type == "js" and shutil.which("node") is None:
            raise HTTPException(status_code=500, detail="Node.js no está disponible en el servidor (este entorno no puede ejecutar deob.js).")

        work_dir = os.path.dirname(script_path)

        # npm install solo si el package.json declara dependencias
        pkg_path = os.path.join(work_dir, "package.json")
        if script_type == "js" and os.path.exists(pkg_path) and shutil.which("npm"):
            try:
                with open(pkg_path, "r", encoding="utf-8") as pf:
                    pkg = json.load(pf)
                if pkg.get("dependencies"):
                    subprocess.run(["npm", "install", "--silent"], cwd=work_dir, timeout=60, capture_output=True)
            except Exception:
                pass

        # 3. Extraer el dump (payload extraído, y texto completo como respaldo)
        candidates = build_candidates(raw_text)
        if not candidates:
            raise HTTPException(status_code=400, detail="No se pudo encontrar el payload de la VM (string oH).")

        # 4. Ejecutar el script (Node o Python)
        deadline = time.time() + TOTAL_TIMEOUT
        last_error = "Error desconocido"
        for payload in candidates:
            remaining = deadline - time.time()
            if remaining <= 1:
                raise HTTPException(status_code=504, detail=f"Timeout: El script tardó más de {TOTAL_TIMEOUT}s.")
            code, err = run_engine(script_path, script_type, work_dir, payload, tmp_in, tmp_out, remaining)
            if code is not None:
                return {"success": True, "code": code}
            last_error = err

        raise HTTPException(status_code=500, detail=last_error)
    finally:
        shutil.rmtree(work, ignore_errors=True)
