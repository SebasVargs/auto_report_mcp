FROM python:3.11-slim

# Evitar archivos .pyc y buffering de stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente
COPY . .

# Crear directorios necesarios
RUN mkdir -p data/raw_reports data/processed_chunks data/daily_inputs \
    vector_db output_reports templates

EXPOSE 8000

CMD ["python", "-m", "app.main"]
