# SQA Defects4J Benchmark — วิธีใช้งานสั้น ๆ

## ⚠️ สำคัญมาก

ก่อนเริ่ม Final Benchmark ทุกคนต้องใช้

- Git commit เดียวกัน
- `config/settings.json` เดียวกัน
- `config/cases.csv` เดียวกัน
- Prompt เดียวกัน
- Model เดียวกัน

ห้ามแก้ Code หรือ Configuration ระหว่างรัน เพราะ `experiment_id` จะเปลี่ยนและรวมผลกันไม่ได้

เปลี่ยนได้เฉพาะ `.env` ของแต่ละเครื่อง เช่น

```env
D4J_ROOT=/home/USERNAME/defects4j
LOCAL_UID=1000
LOCAL_GID=1000
GPT_API_KEY=YOUR_KKU_API_KEY
GEMINI_API_KEY=YOUR_KKU_API_KEY
1. Clone โปรเจกต์
cd ~
git clone https://github.com/sirapatw-sys/SQAProject.git
cd SQAProject

แนะนำ Path:

/home/USERNAME/SQAProject
2. ติดตั้ง Dependencies
sudo apt update
sudo apt install -y python3-pip
python3 -m pip install -r requirements.txt
3. ตั้งค่า .env
cp .env.example .env
nano .env

ดู UID/GID:

id -u
id -g

ห้าม Push .env ขึ้น GitHub

4. Build Docker และตรวจระบบ
docker compose --env-file .env -f docker/compose.yaml build worker
docker compose --env-file .env -f docker/compose.yaml up -d worker
python3 d4j.py check

ถ้าไม่มี Error สำคัญ ถือว่าพร้อม

5. แบ่งงาน 3 คน
Member 1
python3 run.py \
  --case-range 1-285 \
  --methods hill_climbing avm gpt gemini \
  --worker member1
Member 2
python3 run.py \
  --case-range 286-570 \
  --methods hill_climbing avm gpt gemini \
  --worker member2
Member 3
python3 run.py \
  --case-range 571-854 \
  --methods hill_climbing avm gpt gemini \
  --worker member3
6. ถ้า Quota หมด / เน็ตหลุด / เครื่องดับ

ให้รัน คำสั่งเดิม อีกครั้ง

ระบบจะ Skip งานที่ completed แล้ว และทำต่อเฉพาะงานที่ยังไม่เสร็จ

ต้องใช้ --worker ชื่อเดิม

ห้ามใส่:

--force
7. ก่อนเริ่มรันทุกครั้ง
git pull
python3 d4j.py check

เช็กว่ามี Benchmark รันอยู่หรือไม่:

ps aux | grep 'python3 run.py' | grep -v grep

ถ้ามีอยู่แล้ว อย่ารันซ้อน

8. ดูผล

หลังรันเสร็จ:

python3 analyze.py

สรุปผล:

cat results/summary/summary_by_method.csv

ผลทั้งหมด:

cat results/summary/all_results.csv

Generated Tests:

generated_tests/<worker>/<project>/<bug>/
Final Config

ใช้

HC      = 1 seed
AVM     = 1 seed
GPT     = 1 run
Gemini  = 1 run
Target Methods = 5

ก่อนเริ่ม Final ให้ทุกคนเช็ก Commit:

git rev-parse HEAD

ค่า Hash ต้องตรงกันทั้ง 3 คน