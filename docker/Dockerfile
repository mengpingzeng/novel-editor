FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

ENV NOVEL_EDITOR_HOST=0.0.0.0
ENV NOVEL_EDITOR_PORT=19080
ENV NOVEL_EDITOR_MAX_CONCURRENT_BOOKS=2
ENV PHASE1_TIMEOUT=3600
ENV CHAPTER_TIMEOUT=1800
ENV COVER_TIMEOUT=300

RUN echo 'APT::Get::Update::SourceListWarnings::NonFreeFirmware "false";' > /etc/apt/apt.conf.d/99no-warnings && \
    echo 'Acquire::AllowInsecureRepositories "true";' >> /etc/apt/apt.conf.d/99no-warnings && \
    apt-get update -qq --allow-insecure-repositories && \
    apt-get install -y -qq --allow-unauthenticated \
    curl ca-certificates git psmisc python3 python3-pip && \
    rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99no-warnings

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y -qq nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN npm config set registry https://registry.npmmirror.com && \
    npm install -g opencode-ai

WORKDIR /mnt/data/novel-editor

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY .opencode/ .opencode/
RUN cd .opencode && npm install

COPY . .

EXPOSE 19080

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:19080/api/v1/health || exit 1

CMD ["python3", "-m", "api.server"]
