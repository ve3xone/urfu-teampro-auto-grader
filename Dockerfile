FROM python:3.10-slim

WORKDIR /app

COPY main.py credentials.json ./

RUN pip install --no-cache-dir requests beautifulsoup4

CMD ["python", "main.py"]