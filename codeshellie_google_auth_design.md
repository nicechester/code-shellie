# 코드셸리(CodeShellie) 구글 로그인 연동 설계 문서

## 1. 개요 및 목표
* **목표:** 코드셸리(CodeShellie) 백엔드에 **구글 OAuth 2.0 (OpenID Connect)** 인증을 도입하여, 리모트 컨트롤 앱(모바일/웹) 및 대시보드 접근 시 구글 계정을 통해 안전하게 로그인하고 세션을 관리하도록 함.
* **특징:**
  * 사용자 관리가 필요 없고, 지정된 구글 계정(Owner)만 허용하거나 특정 도메인만 접근하도록 화이트리스트(Whitelist) 보안 적용 가능.
  * 리모트 앱과 코드셸리 서버 간 JWT 기반 인증 세션 공유.

---

## 2. 전체 인증 플로우 (Google Sign-In + CodeShellie Session)

```
[Remote Control App]                 [CodeShellie Server]               [Google OAuth Server]
       |                                      |                               |
       |--- 1. 구글 로그인 요청 (SDK/Redirect)|                               |
       |--------------------------------------------------------------------->|
       |<-- 2. Google ID Token (JWT) ---------| (사용자 인증 완료)
       |                                      |                               |
       |--- 3. POST /api/auth/google -------->|                               |
       |      (ID Token 전달)                 |--- 4. Google API로 토큰 검증 --->|
       |                                      |<-- 5. 검증 완료 (Email, Name) -|
       |                                      |                               |
       |                                      | (6. 화이트리스트 검사 및 세션 발급)    |
       |<-- 7. CodeShellie JWT (Access Token)-|                               |
       |                                      |                               |
       |--- 8. API 요청 (Bearer Token) ------>|                               |
```

1. **리모트 앱(클라이언트):** 구글 SDK(또는 웹 리다이렉트)를 통해 사용자로부터 구글 로그인 권한을 획득하고 **Google ID Token (JWT)**을 발급받습니다.
2. **토큰 전송:** 리모트 앱이 코드셸리 서버의 인증 엔드포인트(`POST /api/auth/google`)로 Google ID Token을 전달합니다.
3. **서버 검증:** 코드셸리 서버는 구글 공개 키(JWKS)를 이용해 해당 ID Token의 유효성을 검증하고, 포함된 사용자 정보(`email`, `sub`, `name`)를 추출합니다.
4. **권한 확인 (Whitelist):** 서버에 등록된 허용된 사용자(`ALLOWED_EMAILS` 등)인지 확인합니다.
5. **세션 발행:** 검증이 완료되면 코드셸리 자체의 **Access Token (JWT)**을 리모트 앱에 발급하여 이후 API 요청에 사용하도록 합니다.

---

## 3. 백엔드 구현 설계 (Python / FastAPI 또는 Flask 기준 예시)

### 환경 변수 설정 (`.env`)
```env
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
CODE_SHELLIE_JWT_SECRET=your-jwt-secret-key-for-session
ALLOWED_EMAILS=your_email@gmail.com
```

### 핵심 인증 API 엔드포인트 (`POST /api/auth/google`)
* **Request Body:**
  ```json
  {
    "id_token": "eyJhbGciOiJSUzI1NiIs..."
  }
  ```
* **Server Logic:**
  1. `google-auth` 라이브러리를 사용해 `id_token` 검증.
     ```python
     from google.oauth2 import id_token
     from google.auth.transport import requests

     try:
         idinfo = id_token.verify_oauth2_token(
             token, requests.Request(), os.getenv("GOOGLE_CLIENT_ID")
         )
         email = idinfo['email']
     except ValueError:
         raise HTTPException(status_code=401, detail="Invalid Google Token")
     ```
  2. 이메일 화이트리스트 검증 (`email`이 허용된 관리자/사용자인지 확인).
  3. 코드셸리 자체 Access Token (JWT) 생성 후 반환.
     ```json
     {
       "access_token": "codeshellie_jwt_token_here",
       "token_type": "bearer",
       "user": {
         "email": "your_email@gmail.com",
         "name": "Your Name"
       }
     }
     ```

---

## 4. 리모트 컨트롤 앱 연동 흐름 (클라이언트 측)

1. **로그인 버튼 클릭:** 리모트 앱(Flutter/React 등)에서 `Google Sign-In` 플러그인을 호출합니다.
2. **ID Token 획득:** 구글 로그인이 완료되면 앱 내에 `id_token`이 확보됩니다.
3. **코드셸리 서버 로그인:** 확보한 `id_token`을 코드셸리 백엔드(`POST /api/auth/google`)로 전송합니다.
4. **API 호출:** 응답으로 받은 코드셸리 전용 `access_token`을 저장하고, 이후 코드셸리 에이전트 제어, 터미널 실행 등의 API 호출 시 헤더에 포함합니다.
   ```http
   Authorization: Bearer codeshellie_jwt_token_here
   ```

---

## 5. 보안 및 확장 고려사항

* **단일 사용자 모드 (개인용):** 코드셸리는 주로 개인 기기나 사내 서버에서 구동되므로, `ALLOWED_EMAILS` 환경변수에 본인의 구글 이메일만 등록해두면 외부인의 접근을 완벽히 차단할 수 있습니다.
* **HTTPS 필수:** 구글 로그인 및 토큰 전송 과정은 반드시 HTTPS 환경(또는 로컬 개발 시 `localhost`)에서 이루어져야 합니다.
