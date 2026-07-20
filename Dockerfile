FROM python:3.11-slim

ENV NOVEL_EDITOR_HOST=0.0.0.0
ENV NOVEL_EDITOR_PORT=19080
ENV NOVEL_EDITOR_MAX_CONCURRENT_BOOKS=2
ENV PHASE1_TIMEOUT=3600
ENV CHAPTER_TIMEOUT=1800

WORKDIR /mnt/data/novel-editor

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 19080

CMD ["python3", "-m", "api.server"]
