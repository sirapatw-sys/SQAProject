# วิธีใช้งานสำหรับทดลองซ้ำตอน Demo

เอกสารนี้สรุปเฉพาะขั้นตอนที่จำเป็นสำหรับนำโค้ดไป **รันทดลองซ้ำแบบสั้น ๆ**  
แนะนำให้เตรียม environment ให้เสร็จก่อนวัน Demo แล้ววันจริงรันเพียง 1 เคส

## 1. สิ่งที่ต้องมี

- Linux หรือ WSL2
- Git
- Python 3.10+
- Docker + Docker Compose
- API key ของ KKU Gateway ถ้าจะรัน GPT/Gemini

## 2. Clone โปรเจกต์

```bash
git clone https://github.com/sirapatw-sys/SQAProject.git
cd SQAProject

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. ติดตั้ง Defects4J

วาง Defects4J ไว้ข้างโฟลเดอร์โปรเจกต์

```bash
git clone https://github.com/rjust/defects4j.git ../defects4j
git -C ../defects4j checkout 8c16da8230843cdc918eaf4ddb449637f02b83c6
```

สร้างไฟล์ `.env`

```bash
cp .env.example .env
```

แก้ค่าใน `.env` ให้ตรงกับเครื่อง

```dotenv
D4J_ROOT=/home/YOUR_USER/defects4j
LOCAL_UID=1000
LOCAL_GID=1000

GPT_API_KEY=YOUR_KKU_KEY
GEMINI_API_KEY=YOUR_KKU_KEY
```

ดู UID/GID ได้ด้วย

```bash
id -u
id -g
```

> ห้าม commit ไฟล์ `.env` หรือ API key ขึ้น GitHub

## 4. เตรียม Docker ครั้งแรก

รันครั้งแรกก่อนวัน Demo

```bash
docker compose --env-file .env -f docker/compose.yaml build worker
docker compose --env-file .env -f docker/compose.yaml up -d worker

docker compose --env-file .env -f docker/compose.yaml exec -T --user root worker \
  bash -lc 'cd /opt/defects4j && cpanm --installdeps .'

docker compose --env-file .env -f docker/compose.yaml exec -T worker \
  bash -lc 'cd /opt/defects4j && ./init.sh'

python3 d4j.py check
```

ถ้า `d4j.py check` ผ่าน แสดงว่า environment พร้อมใช้งาน

---

# Demo แบบเร็ว

แนะนำใช้ **Chart-24** เป็นตัวอย่าง 1 เคส

## รันทั้ง 4 วิธี

```bash
python3 run.py \
  --project Chart \
  --bug 24 \
  --methods hill_climbing avm gpt gemini \
  --worker demo \
  --force
```

ระบบจะทำตามลำดับนี้

```text
Checkout fixed/buggy
        ↓
สร้าง Unit Test
        ↓
รันบน fixed revision
        ↓
วัด Coverage
        ↓
รัน test เดิมบน buggy revision
        ↓
สรุปว่าตรวจพบบั๊กได้หรือไม่
```

ผลจะอยู่ที่

```text
results/workers/demo/Chart/24/
generated_tests/demo/Chart/24/
```

ดูผลของ GPT ตัวอย่าง

```bash
python3 -m json.tool results/workers/demo/Chart/24/gpt/run_1.json
```

ค่าที่ควรดูใน JSON:

- `status`
- `valid_test`
- `fault_detected`
- `coverage`
- `duration_sec`

---

## ถ้าไม่มี API key

สามารถ Demo เฉพาะ Hill Climbing และ AVM ได้

```bash
python3 run.py \
  --project Chart \
  --bug 24 \
  --methods hill_climbing avm \
  --worker demo_search \
  --force
```

## ถ้ารันค้างแล้วต้องการทำต่อ

ใช้ **คำสั่งเดิมและ worker เดิม** แต่เอา `--force` ออก

```bash
python3 run.py \
  --project Chart \
  --bug 24 \
  --methods hill_climbing avm gpt gemini \
  --worker demo
```

ระบบจะข้ามงานที่เสร็จแล้วและรันต่อจากงานที่เหลือ

---

## สำหรับ Demo จริง

ควรทำขั้นตอนติดตั้งทั้งหมดให้เสร็จก่อนนำเสนอ แล้วในห้อง Demo ใช้เพียง:

```bash
source .venv/bin/activate
docker compose --env-file .env -f docker/compose.yaml up -d worker

python3 run.py \
  --project Chart \
  --bug 24 \
  --methods hill_climbing avm gpt gemini \
  --worker demo \
  --force
```

จากนั้นเปิด JSON และ generated Java test เพื่ออธิบายผลได้ทันที

รายละเอียด methodology และผลการทดลองทั้งหมดดูได้ที่ [FINAL_REPORT.md](FINAL_REPORT.md)
