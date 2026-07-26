FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* "uvicorn[standard]"==0.30.*
WORKDIR /app
COPY main.py .
VOLUME /data
EXPOSE 8787
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8787"]
