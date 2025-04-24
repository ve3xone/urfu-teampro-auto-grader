FROM python:3.10-slim

WORKDIR /app

COPY main.py credentials.json requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]