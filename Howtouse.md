# วิธีรันทดลองซ้ำตอน Demo

เอกสารนี้เป็นขั้นตอนที่ใช้จริงสำหรับ **WSL/Linux + Docker** เพื่อรันทดลองซ้ำแบบสั้น ๆ ตอน Demo  
แนะนำให้ติดตั้งทุกอย่างให้เสร็จก่อนวัน Demo แล้ววันจริงรันเพียง 1 เคส

## สิ่งที่ต้องมี

- Linux / WSL2
- Git
- Python 3.10+
- Docker + Docker Compose
- API key ของ KKU Gateway ถ้าจะรัน GPT และ Gemini

---

## 1. Clone โปรเจกต์และเตรียม Python

```bash
git clone https://github.com/sirapatw-sys/SQAProject.git
cd SQAProject

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2. ติดตั้ง Defects4J

Clone Defects4J ไว้ข้างโฟลเดอร์ `SQAProject` และบังคับใช้ line ending แบบ Linux

```bash
git -c core.autocrlf=false clone https://github.com/rjust/defects4j.git ../defects4j
git -C ../defects4j checkout 8c16da8230843cdc918eaf4ddb449637f02b83c6
```

คืนสิทธิ์ execute ให้ shell script ตามที่ Git กำหนด

```bash
cd ../defects4j
git ls-files -s | awk '$1 == "100755" {print $4}' | xargs chmod +x
cd ../SQAProject
```

ตรวจว่า `init.sh` พร้อมรัน

```bash
file ../defects4j/init.sh
ls -l ../defects4j/init.sh
```

ควรเห็นว่าเป็น shell script และมีสิทธิ์ `x` เช่น `-rwxr-xr-x`

---

## 3. ตั้งค่า .env

สร้างไฟล์จากตัวอย่าง

```bash
cp .env.example .env
```

หาค่า path, UID และ GID ของเครื่อง

```bash
realpath ../defects4j
id -u
id -g
```

แล้วแก้ `.env` เช่น

```dotenv
D4J_ROOT=/home/YOUR_USER/demo/defects4j
LOCAL_UID=1000
LOCAL_GID=1000

GPT_API_KEY=YOUR_KKU_KEY
GEMINI_API_KEY=YOUR_KKU_KEY
```

> ใช้ path แบบ Linux เช่น `/home/user/...` และใช้ `/` ไม่ใช่ `\\`

---

## 4. เตรียม Docker และ Defects4J

Build และเปิด worker

```bash
docker compose --env-file .env -f docker/compose.yaml build worker
docker compose --env-file .env -f docker/compose.yaml up -d worker
```

ติดตั้ง dependency ของ Defects4J

```bash
docker compose --env-file .env -f docker/compose.yaml exec -T --user root worker \
  bash -lc 'cd /opt/defects4j && cpanm --installdeps .'
```

Initialize Defects4J

```bash
docker compose --env-file .env -f docker/compose.yaml exec -T worker \
  bash -lc 'cd /opt/defects4j && ./init.sh'
```

ถ้าสำเร็จจะเห็น

```text
Defects4J successfully initialized.
```

จากนั้นตรวจ environment

```bash
python3 d4j.py check
```

ถ้า `d4j.py check` ผ่าน แสดงว่าพร้อมทดลอง

> ถ้าเคยสร้าง worker มาก่อนแล้วมีการเปลี่ยน `D4J_ROOT` หรือ clone Defects4J ใหม่ ให้สร้าง container ใหม่เพื่อให้ mount path ถูกต้อง:
>
> ```bash
> docker compose --env-file .env -f docker/compose.yaml down
> docker compose --env-file .env -f docker/compose.yaml up -d worker
> ```

---

## 5. รัน Demo

แนะนำใช้ **Chart-24** เป็นตัวอย่าง 1 เคส

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
ถ้าจะรัน เคสลำดับ 1–5 ตาม config/cases.csv ใช้ --case-range 1-5 ได้เลย
```bash
python3 run.py \
  --case-range 1-5 \
  --methods hill_climbing avm gpt gemini \
  --worker demo \
  --force
```

ระบบจะทำตามลำดับ

```text
เตรียม fixed และ buggy revision
        ↓
สร้าง JUnit test ด้วย 4 วิธี
        ↓
ตรวจว่า test ผ่านบน fixed
        ↓
วัด coverage
        ↓
นำ test เดิมไปรันบน buggy
        ↓
สรุปว่าตรวจพบบั๊กได้หรือไม่
```

ตัวอย่างผลที่เห็นใน Terminal

```text
hill_climbing  completed  valid=True   fault=True
avm            completed  valid=True   fault=True
gpt            completed  valid=True   fault=True
gemini         completed  valid=False  fault=False
```

- `completed` = กระบวนการของวิธีนั้นรันจบ
- `valid=True` = test คอมไพล์และผ่านบน fixed revision
- `fault=True` = test เดิมผ่านบน fixed แต่ล้มเหลวบน buggy จึงตรวจพบบั๊ก

> `completed` ไม่ได้แปลว่า test valid เสมอ ต้องดู `valid_test` เพิ่มด้วย

---

## 6. สรุปผลแบบอ่านง่าย

รวมเฉพาะผลของ worker `demo`

```bash
python3 analyze.py \
  --input results/workers/demo \
  --output results/demo_summary
```

จากนั้นแสดงเป็นตารางสั้น ๆ ใน Terminal

```bash
python3 tools/demo_summary.py results/demo_summary/summary_by_method.csv
```

ตัวอย่างผลจาก Chart-24

```text
Method         Valid  Bug  Branch Cov.  Line Cov.  Time
-------------  -----  ---  -----------  ---------  -----
avm            YES    YES  10.0%        56.0%      7.8s
gemini         NO     NO   -            -          3.9s
gpt            YES    YES  10.0%        48.0%      10.5s
hill_climbing  YES    YES  10.0%        56.0%      17.5s
```

ค่าที่ดูตอน Demo:

- **Valid** — ชุดทดสอบใช้งานได้หรือไม่
- **Bug** — ตรวจพบบั๊ก Chart-24 หรือไม่
- **Branch / Line Cov.** — coverage ของ target class
- **Time** — เวลาที่ใช้ในงานนี้

> ผล Chart-24 เป็นเพียง **Demo 1 เคส** ใช้แสดงว่ากระบวนการทำงานได้จริง ไม่ควรใช้ตัดสินว่าวิธีใดดีที่สุด ผลเปรียบเทียบหลักต้องดูจากผลรวมของ benchmark

ไฟล์ผลอยู่ที่

```text
results/workers/demo/Chart/24/
generated_tests/demo/Chart/24/
results/demo_summary/
```

---

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

## ถ้ารันค้าง

ใช้คำสั่งเดิมและ worker เดิม แต่เอา `--force` ออก ระบบจะข้ามงานที่เสร็จแล้วและทำต่อจากงานที่เหลือ

รายละเอียดผลการทดลองทั้งหมดดูได้ที่ [FINAL_REPORT.md](FINAL_REPORT.md)
