# 🎥 MissAV Downloader Web UI

TrueNAS / Docker 환경용 **MissAV 웹 기반 다운로더**. 브라우저에서 URL만 입력하면 백그라운드로 영상을 받아 mp4로 저장합니다.

## ✨ 주요 기능 (Features)
- **웹 UI:** URL 입력 → 백그라운드 다운로드, 실시간 진행률(%).
- **여러 미러 자동 인식:** `missav.ws / .ai / .live / .fans / .media / missav123.com / missav01.com` 등을 로테이션하며 접속 가능한 주소를 찾습니다.
- **Cloudflare 우회 (핵심):** 영상 CDN(surrit.com)의 Cloudflare는 **직접 접근은 차단**하고 **미러 페이지의 영상 플레이어가 보내는 크로스사이트 요청만 허용**합니다. 그래서 브라우저 플레이어와 동일한 헤더(`Referer` / `Origin` / `Sec-Fetch-*`)를 실어 **`curl_cffi`로 세그먼트를 직접 받아** `ffmpeg`로 mp4로 합칩니다. (VPN·FlareSolverr·쿠키 불필요)
- **↻ 재시작 버튼:** 실패/취소된 작업을 같은 URL로 재시도.
- **작업 취소 / 파일명 자동 최적화.**

## 🛠️ 설치 (Installation)

### docker-compose.yml
```yaml
services:
  missav-dlp-web:
    image: ghcr.io/nerdnam/missav-dlp-web:0.0.16
    restart: unless-stopped
    pull_policy: always
    ports:
      - "58000:5000"      # 외부 58000 → 내부 5000
    volumes:
      - /실제/다운로드/경로:/downloads
```
```bash
docker compose pull && docker compose up -d
```
접속: `http://[NAS_또는_서버_IP]:58000`

> ⚠️ **VPN도 FlareSolverr도 필요 없습니다.** 오히려 **VPN/데이터센터 IP로 나가면 surrit.com에 밴**됩니다. 컨테이너를 **기본(bridge) 네트워크 = 서버의 실제(가정용) IP**로 두세요. 가정용 IP는 surrit.com이 차단하지 않습니다.

## ⚠️ 통신사(ISP) 도메인 차단
일부 통신사는 특정 missav 미러를 **SNI 차단**(연결 리셋)합니다. 그런 환경이면 **차단되지 않는 미러 도메인의 URL**로 넣으세요. 앱이 미러를 자동 로테이션하지만, 페이지 접속 자체가 안 되는 도메인은 통신사가 막는 것입니다. (예: 다른 미러가 다 막히면 `missav01.com`을 사용)

## 🩺 문제 해결 (Troubleshooting)
- **`unable to download video data: 403` / 세그먼트 실패** → 서버가 **VPN/데이터센터 IP**로 나가는 상태. surrit.com이 그 IP를 밴한 것 → **실제 가정용 IP(bridge 네트워크)** 로 나가게 하세요.
- **`페이지 소스를 불러오는 데 실패` / `Connection reset`** → 통신사가 그 미러를 SNI 차단. **다른(안 막힌) 미러 URL** 사용.
- **작업이 에러로 끝남** → 작업 카드의 `↻ 재시작` 버튼으로 재시도.
- **이미지가 안 바뀜(코드 반영 안 됨)** → Docker 태그 캐시. compose 이미지를 **새 태그**로 지정하고 `docker compose pull` 후 `docker compose up -d`.

## ⚠️ 면책 조항 (Disclaimer)
이 도구는 개인적인 용도로만 사용해야 하며, 다운로드한 콘텐츠의 저작권 및 사용에 대한 책임은 전적으로 사용자 본인에게 있습니다.
