FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Railway: Volume'ni /data ga ulang (baza shu yerda saqlanadi, redeploydan keyin ham o'chmaydi)
CMD ["python", "main.py"]
