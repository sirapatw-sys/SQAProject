# SQA Defects4J Benchmark

โปรเจกต์เปรียบเทียบการสร้าง Unit Test 4 วิธี

- Hill Climbing
- AVM
- GPT
- Gemini

ผลที่เก็บ:
- จำนวน Test Case
- Valid Test Rate
- Line / Branch / Instruction Coverage
- Fault Detection
- Generation / Evaluation Time
- Coverage per Test

---

## 1. Clone โปรเจกต์

```bash
git clone https://github.com/sirapatw-sys/SQAProject.git
cd SQAProject
2. ติดตั้ง Python dependency
sudo apt update
sudo apt install -y python3-pip
python3 -m pip install -r requirements.txt
3. ตั้งค่า .env
cp .env.example .env
nano .env

ตัวอย่าง:

D4J_ROOT=/home/USERNAME/defects4j
LOCAL_UID=1000
LOCAL_GID=1000

GPT_API_KEY=
GEMINI_API_KEY=

ดู UID/GID ด้วย:

id -u
id -g

ห้าม push .env ขึ้น GitHub

4. Build Docker ครั้งแรก
docker compose --env-file .env -f docker/compose.yaml build worker
docker compose --env-file .env -f docker/compose.yaml up -d worker

เช็ก environment:

python3 d4j.py check

ถ้าไม่มี error ถือว่าพร้อม

วิธีรัน Bug ที่ต้องการ

รูปแบบ:

python3 run.py \
  --project PROJECT \
  --bug BUG_ID \
  --methods hill_climbing avm gpt gemini \
  --worker ชื่อคนรัน

ตัวอย่าง Chart-1:

python3 run.py \
  --project Chart \
  --bug 1 \
  --methods hill_climbing avm gpt gemini \
  --worker member1

ตัวอย่าง Lang-5:

python3 run.py \
  --project Lang \
  --bug 5 \
  --methods hill_climbing avm gpt gemini \
  --worker member2
รันเฉพาะ Algorithm
python3 run.py \
  --project Chart \
  --bug 1 \
  --methods hill_climbing avm \
  --worker member1
รันเฉพาะ AI
python3 run.py \
  --project Chart \
  --bug 1 \
  --methods gpt gemini \
  --worker member1
ถ้าโปรแกรมหยุด / เน็ตหลุด / quota หมด

รันคำสั่งเดิมอีกครั้งได้เลย

ระบบจะ skip งานที่เสร็จแล้วและทำต่อเฉพาะงานที่ยังไม่เสร็จ

ดูผล
python3 analyze.py

ดูสรุป:

cat results/summary/summary_by_method.csv

ผลละเอียด:

cat results/summary/all_results.csv

Generated Tests อยู่ที่:

generated_tests/<worker>/<project>/<bug>/
เช็กว่ามี benchmark รันอยู่ไหม
ps aux | grep 'python3 run.py' | grep -v grep

ถ้ามี process อยู่แล้ว อย่ารันอีกตัวซ้อน

ก่อนเริ่มงานทุกครั้ง
git pull
python3 d4j.py check
