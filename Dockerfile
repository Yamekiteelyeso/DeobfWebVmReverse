FROM python:3.12-slim

# Node.js (para deob.js) y libstdc++ (para bin/luau)
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
