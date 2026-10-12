FROM python:3.12-slim

WORKDIR /servicio
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# No expone ningún puerto: solo escucha la cola
CMD ["python", "-u", "-m", "app.main"]
