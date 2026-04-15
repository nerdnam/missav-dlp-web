FROM python:3.10-slim

# 1. uv 바이너리 복사
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. 필수 패키지 설치
RUN apt-get update && \
    apt-get install -y ffmpeg curl bash && \
    rm -rf /var/lib/apt/lists/*

# 3. SpoofDPI 설치
RUN curl -fsSL https://raw.githubusercontent.com/xvzc/SpoofDPI/main/install.sh | bash -s linux-amd64

WORKDIR /app

# 4. 파이썬 패키지 고속 설치
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# 5. 애플리케이션 복사
COPY . .

# 6. 폴더 생성 및 포트 노출
RUN mkdir -p /downloads
EXPOSE 5000

# 7. 파이썬 바로 실행 (SpoofDPI는 app.py가 알아서 켭니다)
CMD ["python", "app.py"]