# วิธีใช้งานและทำซ้ำการทดลอง

เริ่มอ่านผลที่ [FINAL_REPORT.md](FINAL_REPORT.md) นิยามอยู่ใน [EXPERIMENT_PROTOCOL.md](EXPERIMENT_PROTOCOL.md) และรายการชุดส่งงานอยู่ใน [ARTIFACTS.md](ARTIFACTS.md) คำสั่งทั้งหมดด้านล่างรันจาก root ของโปรเจกต์บน Linux หรือ WSL2

## 1. ตรวจชุดส่งงาน

ไฟล์ `submission/sqa-final-submission.tar.gz` รวม source, เอกสาร, raw results, generated tests, prompts/responses และ configuration ส่วน `.env` ให้ผู้ทำซ้ำสร้างเอง

ตรวจ checksum จาก root ของโปรเจกต์:

```bash
sha256sum -c submission/sqa-final-submission.tar.gz.sha256
mkdir -p ../sqa-submission-review
tar -xzf submission/sqa-final-submission.tar.gz -C ../sqa-submission-review
cd ../sqa-submission-review
sha256sum -c FILE_MANIFEST.sha256
```

การ clone repository อย่างเดียวอาจไม่มีผลทดลอง เพราะ `.gitignore` ละเว้น `results/` และ `generated_tests/` ใช้ archive นี้ประกอบเสมอ เก็บสำเนาที่ตรวจ checksum แล้วไว้ และใช้อีก working copy เมื่อต้องติดตั้ง/รันเทสต์ ซึ่งจะสร้างหรือเปลี่ยน runtime metadata

## 2. ทำซ้ำการวิเคราะห์ผลเดิมโดยไม่เรียก AI

ต้องมี Python 3.10 ขึ้นไปและ dependencies ตาม `requirements.txt` เครื่องมือวิเคราะห์ใช้ Python standard library แต่ import runner ซึ่งใช้ `requests` จึงต้องติดตั้ง dependency นี้ด้วย ไม่ต้องใช้ Docker, Defects4J หรือ API key สำหรับขั้นตอนนี้

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 analyze.py --output results/reproduced_summary
python3 tools/report_analysis.py --output results/reproduced_report_data
```

ผลที่ควรได้จากชุดส่งงาน:

- 3,416 raw results และ 3,416 unique tasks ครบ 854 เคส
- สอง experiment_id: `9f661b38cc1eee98` (2,280 tasks), `1b010d74235e8785` (1,136 tasks)
- completed/unsupported/error รวม 2,401 / 1,006 / 9
- บั๊กตรวจพบ HC/AVM/GPT/Gemini = 12 / 11 / 38 / 8 และ union 51 เคส
- common completed 349 เคส; common valid 231 เคส
- artifact ที่ JSON อ้างถึงครบหลัง normalize Windows path และไม่มี duplicate tasks

เปรียบเทียบ CSV ที่สร้างกับ snapshot:

```bash
diff -u results/summary/summary_by_method.csv results/reproduced_summary/summary_by_method.csv
diff -u results/summary/all_results.csv results/reproduced_summary/all_results.csv
diff -u docs/report_data/summary_common_valid.csv results/reproduced_report_data/summary_common_valid.csv
```

ไฟล์เหล่านี้ควรตรงกันบนชุดข้อมูลเดิม ส่วน `audit.json` มี provenance ของ source/เครื่องปัจจุบันซึ่งอาจเปลี่ยนเมื่อย้ายเครื่องหรือ checkout คนละ commit

`analyze.py` ฉบับที่ส่งมอบ **เตือนแล้วรวม** หลาย experiment_id ได้; `summary_by_method.csv` จึงเป็นผลรวมเชิงพรรณนา ผลแยก ID อยู่ใน `summary_by_experiment.csv` ของเครื่องมือรายงาน ฉบับ `analyze.py` ใน Git commit ที่ผลเดิมบันทึกไว้อาจปฏิเสธการรวม ใช้ไฟล์ที่ส่งมอบ หรือดู `docs/report_data/analysis_workspace.patch` สำหรับความต่าง

## 3. เตรียม environment สำหรับรัน Java

ต้องมี Git, Python 3.10+, Docker Engine และ Docker Compose v2 ส่วน Dockerfile ติดตั้ง Ubuntu 20.04, OpenJDK 11, Perl และเครื่องมือที่ Defects4J ต้องใช้ Container กำหนด timezone `America/Los_Angeles` และ locale `C.UTF-8` อยู่แล้ว

ดาวน์โหลด Defects4J ในโฟลเดอร์แยก:

```bash
git clone https://github.com/rjust/defects4j.git ../defects4j
git -C ../defects4j checkout 8c16da8230843cdc918eaf4ddb449637f02b83c6
```

commit นี้เป็น Defects4J ที่ตรวจพบในเครื่องจัดทำรายงาน (README ระบุ 3.0.1) ไม่ได้มีหลักฐานว่าทุก worker เดิมใช้ commit นี้ ดู `docs/report_data/environment_observed.json` และข้อจำกัดในรายงาน

สร้าง `.env`:

```bash
cp .env.example .env
id -u
id -g
realpath ../defects4j
```

แก้ค่าให้ตรงกับเครื่องของตน ใช้ absolute path ของ Defects4J และ UID/GID จากคำสั่งข้างบน:

```dotenv
D4J_ROOT=/absolute/path/to/defects4j
LOCAL_UID=1000
LOCAL_GID=1000
GPT_API_KEY=YOUR_KKU_GATEWAY_KEY
GEMINI_API_KEY=YOUR_KKU_GATEWAY_KEY
```

API key จำเป็นเฉพาะการสร้าง AI ใหม่ ห้ามใส่ `.env` หรือ key จริงในชุดส่งงาน

Build และเริ่ม worker จาก root ของ benchmark:

```bash
docker compose --env-file .env -f docker/compose.yaml build worker
docker compose --env-file .env -f docker/compose.yaml up -d worker
docker compose --env-file .env -f docker/compose.yaml exec -T --user root worker bash -lc 'cd /opt/defects4j && cpanm --installdeps .'
docker compose --env-file .env -f docker/compose.yaml exec -T worker bash -lc 'cd /opt/defects4j && ./init.sh'
python3 d4j.py check
```

`init.sh` ดาวน์โหลด project repositories และ dependencies จึงต้องมี network และพื้นที่ดิสก์เพียงพอ JaCoCo 0.8.13 ถูกดาวน์โหลดเมื่อ evaluator ใช้ครั้งแรก หรือใช้ JAR ที่รวมในชุดส่งงาน ถ้ามี `tools/jacoco/` แล้ว

บันทึกเวอร์ชันสำหรับการทดลองรอบใหม่:

```bash
mkdir -p logs
python3 --version > logs/python-version.txt
python3 -m pip freeze > logs/python-dependencies.txt
docker --version > logs/docker-version.txt
docker compose version > logs/compose-version.txt
git -C ../defects4j rev-parse HEAD > logs/defects4j-commit.txt
docker compose --env-file .env -f docker/compose.yaml exec -T worker java -version > logs/java-version.txt 2>&1
```

บันทึก OS, CPU, RAM และ Docker image ID ของแต่ละ worker เพิ่มเองเมื่อทดลองใหม่ ผลเดิมไม่ได้เก็บสเปกทุกเครื่อง

## 4. ประเมิน generated test เดิม

ขั้นตอนนี้ไม่เรียก AI แต่ checkout/compile Defects4J และรัน Java ใช้ working copy แยกจากสำเนาส่งงานที่ตรวจ checksum แล้ว ตัวอย่างประเมิน GPT ของ Chart-24:

```bash
python3 - <<'PY'
import json
from pathlib import Path
import d4j
import evaluate
import run

run.load_dotenv()
record_path = Path('results/workers/member1_final/Chart/24/gpt/run_1.json')
record = json.loads(record_path.read_text(encoding='utf-8'))
case = next(c for c in d4j.load_cases()
            if c['project'] == record['project']
            and int(c['bug_id']) == int(record['bug_id']))
meta = d4j.prepare_case(case)
java_path = Path(record['generated_test'].replace('\\', '/'))
result = evaluate.evaluate_test(meta, java_path)
destination = Path('results/replay/Chart_24_gpt.json')
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(result['valid_test'], result['fault_detected'])
PY
```

ผลเดิมของตัวอย่างนี้คือ `True True` (fixed ผ่าน 4 tests; buggy ล้มเหลว 1 test) metadata ของเครื่องเดิมมี workspace/classpath เฉพาะเครื่อง จึงเรียก `prepare_case` ใหม่ เปลี่ยน `record_path` เพื่อประเมินไฟล์อื่น และ normalize `\\` เป็น `/` สำหรับ worker3

## 5. สร้างเทสต์และทดลองใหม่

ใช้ source/config/prompt ที่ส่งมอบกับ **โฟลเดอร์ทดลองแยก** ที่ไม่มีผลเก่าอยู่ใน `results/workers/` เช่นแตก source จาก archive โดยเว้น results และ generated artifacts:

```bash
mkdir -p ../sqa-new-experiment
tar --exclude='results' --exclude='generated_tests' -xzf submission/sqa-final-submission.tar.gz -C ../sqa-new-experiment
```

จากนั้นเข้าโฟลเดอร์ใหม่นี้และทำขั้นตอน setup อีกครั้ง การแตกเฉพาะ source ใช้สำหรับรันใหม่ จึงไม่ได้มีไฟล์ครบตาม `FILE_MANIFEST.sha256` ของชุดส่งงานเดิม

ก่อนเริ่ม ทุกเครื่องตรวจ commit และ experiment_id:

```bash
git rev-parse HEAD
python3 -c 'import run; print(run.experiment_id())'
sha256sum config/settings.json config/cases.csv prompts/gpt_unit_test_prompt.txt prompts/gemini_unit_test_prompt.txt
```

Archive ไม่มี `.git` จึงรัน `git rev-parse HEAD` ได้เมื่อใช้ checkout จาก repository เท่านั้น มิฉะนั้นยึด source checksums และ experiment_id; JSON จะมี `git_commit = null` workspace ที่ส่งมอบต้องคำนวณได้ `9f661b38cc1eee98` การเพิ่มเอกสาร/เครื่องมือรายงานไม่ได้เปลี่ยน ID นี้

ลองหนึ่งเคสก่อนเพื่อยืนยัน Docker และ API:

```bash
python3 run.py --project Chart --bug 24 --methods hill_climbing avm gpt gemini --worker pilot_reproduction
```

แยกผล pilot ออกจาก `results/workers/` ก่อนรวมผลรอบเต็ม หรือใช้ working copy ใหม่สำหรับรอบเต็ม เพื่อไม่ให้เกิด duplicate task ผลรายงานเดิมใช้ worker `member1_final`, `member2`, `worker3` ส่วนคำสั่งรันใหม่ใช้ชื่อด้านล่าง:

```bash
# เครื่องที่ 1
python3 run.py --case-range 1-285 --methods hill_climbing avm gpt gemini --worker repro_member1 > logs/repro_member1.log 2>&1

# เครื่องที่ 2
python3 run.py --case-range 286-570 --methods hill_climbing avm gpt gemini --worker repro_member2 > logs/repro_member2.log 2>&1

# เครื่องที่ 3
python3 run.py --case-range 571-854 --methods hill_climbing avm gpt gemini --worker repro_member3 > logs/repro_member3.log 2>&1
```

อย่าแก้ source/config/prompt ระหว่างรัน และอย่า `git pull` ระหว่างรอบ frozen หากตั้งใจเปลี่ยน configuration ให้ถือเป็นการทดลองใหม่ ทุกเคสต้องรันครบทั้งสี่วิธีบนเครื่องที่รับผิดชอบช่วงนั้น

ถ้ารัน HC/AVM เท่านั้นไม่ต้องมี API key:

```bash
python3 run.py --project Chart --bug 24 --methods hill_climbing avm --worker search_reproduction
```

## 6. Resume และ quota

ใช้คำสั่งเดิมและ worker เดิมเพื่อรันต่อ โดยไม่ใส่ `--force` ระบบ skip เฉพาะ `completed`/`unsupported` ที่ experiment_id ตรงกับปัจจุบัน ส่วน `error` และ `paused_quota` จะถูกลองใหม่ เมื่อ ID เปลี่ยน checkpoint เดิมจะไม่ถูก reuse และอาจถูกเขียนทับหากใช้ worker เดิม

API retry ไม่สำเร็จหรือ quota หมดอาจหยุด provider นั้นใน process แล้วให้วิธีอื่นทำต่อ ไม่มี `paused_quota` ค้างอยู่ในผล final ที่ส่งมอบ แต่มี quota fields ใน provider metadata การสร้าง AI ใหม่อาจได้ code ต่างจาก response เดิม แม้ temperature 0 จึงใช้ response/test เดิมเมื่อจะตรวจผลเดิมแบบตรงกัน

## 7. รวมผลและตรวจคุณภาพ

คัดลอกทั้ง `results/workers/<worker>/` และ `generated_tests/<worker>/` จากทุกเครื่อง รวม metadata/environment/logs ที่เก็บได้ แล้วรัน:

```bash
python3 analyze.py
python3 tools/report_analysis.py
python3 -m unittest discover -s tests -v
```

`analyze.py` deduplicate ตาม task เลือก completed ก่อน unsupported/paused_quota/error และเลือก timestamp ล่าสุดภายในลำดับเดียวกัน ดู `duplicate_tasks.csv` ทุกครั้ง เครื่องมือรายงานตรวจ task inventory, เคสร่วม, experiment IDs และไฟล์อ้างอิง และจะออกด้วย error หากมี task ขาด/เกิน/ซ้ำ หรือ artifact อ้างอิงขาด

เครื่องมือรายงานรองรับชุดนี้ที่มีหนึ่ง run ต่อ method/bug หากจะทดลองหลาย seeds/repetitions ต้องกำหนดวิธีรวม runs ในการวิเคราะห์เคสร่วมเพิ่มก่อน สรุปผลรอบใหม่จากข้อมูลรอบใหม่นั้น และจัดชุดส่งงานตาม [ARTIFACTS.md](ARTIFACTS.md)
