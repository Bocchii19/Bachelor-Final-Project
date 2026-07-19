# Surveillance System

Frontend demo dashboard quan ly nhieu camera voi mock stream, mock data va fake realtime AI event.

## Chay 1 lenh

```bash
docker compose up --build
```

## URL truy cap

- `http://localhost:8080`
- `http://<IP_ubuntu>:8080`

## Tinh nang chinh

- Camera tabs + them/sua/xoa camera
- Fake live stream chi cho phep 1 camera viewing tai mot thoi diem
- 6 AI core cau hinh rieng theo tung camera
- Event realtime gia lap cho camera dang `AI Running`
- Filter event, toast, localStorage persistence

## Ghi chu

Hien tai toan bo service dang dung mock data, fake stream va event simulator. Cau truc service/store da san sang de thay bang backend that sau nay.
