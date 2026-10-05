# วิธีรันทดลองซ้ำตอน Demo

ใช้สำหรับนำโค้ดไปรันซ้ำแบบสั้น ๆ แนะนำให้ **ติดตั้งทุกอย่างให้เสร็จก่อนวัน Demo** แล้ววันจริงรันเพียง 1 เคส

## สิ่งที่ต้องมี

- Linux / WSL2
- Python 3.10+
- Docker + Docker Compose
- API key ของ KKU Gateway ถ้าจะรัน GPT และ Gemini

## 1. เตรียมโปรเจกต์ครั้งแรก

```bash
git clone https://github.com/sirapatw-sys/SQAProject.git
cd SQAProject

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

git clone https://github.com/rjust/defects4j.git ../defects4j
git -C ../defects4j checkout 8c16da8230843cdc918eaf4ddb449637f02b83c6

cp .env.example .env
```

แก้ `.env` ให้ตรงกับเครื่อง

```dotenv
D4J_ROOT=/home/YOUR_USER/defects4j
LOCAL_UID=1000
LOCAL_GID=1000

GPT_API_KEY=YOUR_KKU_KEY
GEMINI_API_KEY=YOUR_KKU_KEY
```

จากนั้นเตรียม Docker

```bash
docker compose --env-file .env -f docker/compose.yaml build worker
docker compose --env-file .env -f docker/compose.yaml up -d worker

docker compose --env-file .env -f docker/compose.yaml exec -T --user root worker \
  bash -lc 'cd /opt/defects4j && cpanm --installdeps .'

docker compose --env-file .env -f docker/compose.yaml exec -T worker \
  bash -lc 'cd /opt/defects4j && ./init.sh'

python3 d4j.py check
```

ถ้า `d4j.py check` ผ่าน แสดงว่าพร้อมใช้งาน

---

## 2. รัน Demo

แนะนำใช้ **Chart-24** เป็นตัวอย่าง

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

ระบบจะ:

```text
สร้าง test จาก fixed revision
        ↓
ตรวจว่า test ผ่านบน fixed
        ↓
วัด coverage
        ↓
นำ test เดิมไปรันบน buggy revision
        ↓
สรุปว่าตรวจพบบั๊กได้หรือไม่
```

## 3. สรุปผลแบบอ่านง่าย

หลังรันเสร็จ ให้รวมผลของ worker `demo`

```bash
python3 analyze.py \
  --input results/workers/demo \
  --output results/demo_summary
```

จากนั้นแสดงตารางสั้น ๆ ใน Terminal

```bash
python3 tools/demo_summary.py results/demo_summary/summary_by_method.csv
```

ตัวอย่างหน้าตา:

```text
=== Demo Summary ===
Method          Valid  Bug  Branch Cov.  Line Cov.  Time
---------------------------------------------------------
hill_climbing   YES    YES  18.5%        31.2%      42.1s
avm             YES    NO   20.1%        32.4%      38.7s
gpt             YES    YES  28.4%        35.6%      21.3s
gemini          YES    NO   25.7%        34.1%       6.8s
```

ค่าที่ดูตอน Demo:

- **Valid** — ชุดทดสอบใช้ได้หรือไม่
- **Bug** — ตรวจพบบั๊กหรือไม่
- **Branch / Line Cov.** — ครอบคลุมโค้ดเท่าไร
- **Time** — ใช้เวลาเท่าไร

ไฟล์ผลฉบับเต็มยังอยู่ที่

```text
results/workers/demo/Chart/24/
generated_tests/demo/Chart/24/
results/demo_summary/
```

## ถ้าไม่มี API key

รันเฉพาะ Hill Climbing และ AVM ได้

```bash
python3 run.py \
  --project Chart \
  --bug 24 \
  --methods hill_climbing avm \
  --worker demo_search \
  --force
```

> ถ้ารันค้าง ให้ใช้คำสั่งเดิมและ worker เดิม แต่เอา `--force` ออก ระบบจะทำต่อจากงานที่ยังไม่เสร็จ

รายละเอียดการทดลองทั้งหมดดูได้ที่ [FINAL_REPORT.md](FINAL_REPORT.md)
