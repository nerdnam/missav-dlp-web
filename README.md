```markdown
# 🎥 MissAV Downloader Web UI

TrueNAS 및 Docker 환경에서 완벽하게 동작하는 **MissAV 웹 기반 다운로더**입니다. 
통신사 차단(SNI) 및 Cloudflare의 강력한 봇 방어막을 우회하기 위해 `curl_cffi`와 `yt-dlp`를 결합하여 제작되었습니다.

## ✨ 주요 기능 (Features)
- **웹 기반 UI (Web UI):** 브라우저에서 URL만 입력하면 다운로드가 백그라운드에서 진행됩니다.
- **실시간 진행률 표시:** 터미널을 볼 필요 없이 웹 화면에서 직관적인 초록색 게이지 바로 다운로드 진행률(%)을 확인할 수 있습니다.
- **완벽한 우회 로직:**
  - `curl_cffi`를 활용하여 최신 Chrome 브라우저로 위장, Cloudflare의 봇 방어막과 CAPTCHA를 스무스하게 통과합니다.
  - MissAV의 여러 미러 도메인을 자동으로 로테이션하며 뚫려있는 주소를 스스로 찾아냅니다.
- **VPN 환경 완벽 호환:** Gluetun 등 VPN 컨테이너 네트워크에 종속시켜도 정상적으로 IP 우회 및 다운로드가 가능합니다.
- **안정성 강화:** 긴 일본어/한국어 제목으로 인한 파일 시스템 저장 에러(`[Errno 36] File name too long`)를 방지하기 위해 파일명을 자동으로 최적화합니다.
- **작업 취소 기능:** 목록에서 `삭제` 버튼 클릭 시, 백그라운드 다운로드 프로세스까지 즉시 강제 종료(Cancel)됩니다.

## 🛠️ 설치 및 실행 (Installation & Usage)

VPN(예: Gluetun)을 적용하여 안전하게 구동하는 것을 강력히 권장합니다.

### 1. `docker-compose.yml` 작성
다운로더 컨테이너를 VPN 네트워크에 종속시킵니다. (GitHub Container Registry를 사용합니다.)

```yaml
version: '3'
services:
  missav-dlp-web:
    image: ghcr.io/nerdnam/missav-dlp-web:0.0.1
    network_mode: "container:gluetun-vpn" # (선택) VPN 컨테이너 네트워크 사용 시
    # ports:
    #   - "5000:5000" # VPN을 사용하지 않을 때만 활성화하세요.
    volumes:
      - /실제/다운로드/경로:/downloads
    restart: unless-stopped
```

### 2. Gluetun `docker-compose.yml`에 포트 추가
네트워크가 VPN 컨테이너에 종속되므로, 외부 접속을 위한 포트는 반드시 **Gluetun 컨테이너 설정**에 추가해야 합니다.

```yaml
services:
  gluetun-vpn:
    # ... (기존 Gluetun 설정) ...
    ports:
      - "58000:5000/tcp"  # 사용할 포트 58000, missav-dlp-web docker 내부 포트 5000
```

### 3. 접속
컨테이너를 실행한 뒤, 브라우저에서 `http://[NAS_또는_서버_IP]:58000` 으로 접속하여 사용합니다.

## ⚠️ 면책 조항 (Disclaimer)
이 도구는 개인적인 용도로만 사용해야 하며, 다운로드한 콘텐츠의 저작권 및 사용에 대한 책임은 전적으로 사용자 본인에게 있습니다.
```
