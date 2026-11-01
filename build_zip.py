# language: Python 3.10+
# file: build_zip.py
import os
import zipfile

files = {
    "server.py": '''import os, re, subprocess, json
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Luraph VM Deobfuscator Web")
DEOBF_DIR = "./luraph-deobfuscator-py"

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

    match = re.search(r'oH=\\[=\\[(.*?)\\]=\\]', lua_vm, re.DOTALL)
    if match:
        return match.group(1)
    
    match = re.search(r'\\[=\\[(.*?)\\]=\\]', lua_vm, re.DOTALL)
    if match:
        return match.group(1)

    raise ValueError("No se pudo encontrar el payload de la VM (string oH).")

@app.post("/api/deobfuscate")
async def deobfuscate(payload: Payload):
    try:
        vm_payload = extract_vm_payload(payload.raw_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    temp_in = "temp_payload.lua"
    temp_out = "temp_clean.luau"
    
    with open(temp_in, "w", encoding="utf-8") as f:
        f.write(vm_payload)

    if not os.path.exists(DEOBF_DIR):
        subprocess.run(["git", "clone", "https://github.com/mehCake/luraph-deobfuscator-py.git", DEOBF_DIR], check=True)

    try:
        result = subprocess.run(
            ["python", "deobfuscate.py", f"../{temp_in}", "-o", f"../{temp_out}"],
            cwd=DEOBF_DIR,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode != 0:
            output = result.stdout or result.stderr
            raise HTTPException(status_code=500, detail=f"Error del deobfuscador:\\n{output}")

        if not os.path.exists(temp_out):
            raise HTTPException(status_code=500, detail="El deobfuscador no generó el archivo de salida.")

        with open(temp_out, "r", encoding="utf-8") as f:
            clean_code = f.read()

        os.remove(temp_in)
        os.remove(temp_out)

        return {"success": True, "code": clean_code}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="El proceso de deobfuscación tardó demasiado (Timeout).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
''',

    "index.html": '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Luraph VM Deobfuscator</title>
    <style>
        :root {
            --bg: #0d1117;
            --panel: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-muted: #8b949e;
            --accent: #58a6ff;
            --success: #3fb950;
            --error: #f85149;
            --font: 'Consolas', 'Courier New', monospace;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        header {
            background-color: var(--panel);
            border-bottom: 1px solid var(--border);
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        header h1 { font-size: 1.2rem; font-weight: 600; }
        header h1 span { color: var(--accent); }
        .controls { display: flex; gap: 10px; }
        button {
            background-color: var(--accent);
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: 0.2s;
        }
        button:hover { background-color: #3182ce; }
        button:disabled { background-color: var(--border); cursor: not-allowed; }
        .main-container {
            display: flex;
            flex: 1;
            padding: 20px;
            gap: 20px;
            overflow: hidden;
        }
        .panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            background-color: var(--panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
        }
        .panel-header {
            padding: 10px 15px;
            background-color: #1f242c;
            border-bottom: 1px solid var(--border);
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--text-muted);
            display: flex;
            justify-content: space-between;
        }
        textarea {
            flex: 1;
            width: 100%;
            background-color: transparent;
            border: none;
            color: var(--text);
            font-family: var(--font);
            font-size: 0.9rem;
            padding: 15px;
            resize: none;
            outline: none;
            white-space: pre;
            overflow: auto;
        }
        #status { font-size: 0.85rem; font-weight: normal; }
        .status-success { color: var(--success); }
        .status-error { color: var(--error); }
        .status-loading { color: var(--accent); }
    </style>
</head>
<body>
    <header>
        <h1><span>Luraph</span> VM Web Deobfuscator</h1>
        <div class="controls">
            <button id="btn-deobf" onclick="deobfuscate()">Devirtualizar</button>
        </div>
    </header>
    <div class="main-container">
        <div class="panel">
            <div class="panel-header">
                <span>Dump (JSON / VM Raw)</span>
                <span id="in-size">0 bytes</span>
            </div>
            <textarea id="input" placeholder="Pega aquí el texto de tu dump..." oninput="updateSize()"></textarea>
        </div>
        <div class="panel">
            <div class="panel-header">
                <span>Código Limpio (Lua)</span>
                <span id="status">Esperando...</span>
            </div>
            <textarea id="output" readonly placeholder="El código deobfuscado aparecerá aquí..."></textarea>
        </div>
    </div>
    <script>
        const inputArea = document.getElementById('input');
        const outputArea = document.getElementById('output');
        const btnDeobf = document.getElementById('btn-deobf');
        const statusText = document.getElementById('status');
        const inSize = document.getElementById('in-size');

        function updateSize() {
            const bytes = new Blob([inputArea.value]).size;
            inSize.textContent = bytes.toLocaleString() + ' bytes';
        }

        async function deobfuscate() {
            const raw = inputArea.value.trim();
            if (!raw) {
                setStatus('Pega un dump primero.', 'error');
                return;
            }
            btnDeobf.disabled = true;
            outputArea.value = '';
            setStatus('Procesando VM...', 'loading');
            try {
                const response = await fetch('/api/deobfuscate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ raw_text: raw })
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Error desconocido');
                outputArea.value = data.code;
                setStatus('¡Completado!', 'success');
            } catch (err) {
                setStatus('Fallo', 'error');
                outputArea.value = "[-] ERROR:\\n" + err.message;
            } finally {
                btnDeobf.disabled = false;
            }
        }

        function setStatus(msg, type) {
            statusText.textContent = msg;
            statusText.className = 'status-' + type;
        }
    </script>
</body>
</html>
''',

    "requirements.txt": "fastapi\nuvicorn\npydantic\n",

    "README.md": '''# Luraph VM Web Deobfuscator

## Requisitos
- Python 3.8+
- Git

## Instalación
1. `pip install -r requirements.txt`
2. `python server.py`

## Uso
Abre `http://localhost:8000` en tu navegador.
Pega el dump en el panel izquierdo y presiona "Devirtualizar".
''',
}

def create_zip():
    zip_name = "luraph_deobfuscator_web.zip"
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as z:
        for filename, content in files.items():
            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)
            z.write(filename)
            os.remove(filename)
    print(f"[+] Archivo generado: {zip_name}")

if __name__ == "__main__":
    create_zip()
