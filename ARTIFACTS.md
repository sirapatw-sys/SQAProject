# รายการหลักฐานและชุดส่งงาน

ชุดนี้ประกอบรายงานฉบับสมบูรณ์และไฟล์ที่ใช้/ได้จากการทดลอง final ของ Hill Climbing, AVM, GPT และ Gemini ผู้อ่านทำซ้ำการคำนวณสรุปได้จาก raw results และประเมินเทสต์เดิมหรือสร้างใหม่ตาม [Howtouse.md](Howtouse.md)

## 1. ไฟล์ส่งงาน

- [FINAL_REPORT.md](FINAL_REPORT.md): ผลเปรียบเทียบ การวิเคราะห์ บทเรียน ปัญหา ข้อจำกัด และ diagram
- [sqa-final-submission.tar.gz](submission/sqa-final-submission.tar.gz): ชุด source/เอกสารและผล final ที่มีอยู่ใน workspace
- [archive checksum](submission/sqa-final-submission.tar.gz.sha256): ตรวจไฟล์ archive จาก project root
- [FILE_MANIFEST.sha256](FILE_MANIFEST.sha256): SHA-256 ของทุก payload file และ inventory (ยกเว้นตัว manifest เอง)
- [SUBMISSION_INVENTORY.json](SUBMISSION_INVENTORY.json): จำนวนไฟล์และขนาดแยกหมวดของชุดส่งงาน

archive แตกไฟล์ลง root โดยตรง ไม่มี `.git` หรือ `.env` ภายในมี `FILE_MANIFEST.sha256` และ `SUBMISSION_INVENTORY.json` ด้วย ส่วน archive และ checksum ของ archive เป็นไฟล์แจกจ่ายภายนอก จึงไม่ได้บรรจุ archive ซ้อนตัวเอง

## 2. Source code และ test infrastructure

| ไฟล์/โฟลเดอร์ | หน้าที่ |
| --- | --- |
| [run.py](run.py) | แบ่งเคส, เรียก generator, ประกอบ prompt, checkpoint/resume, บันทึก task |
| [d4j.py](d4j.py) | Checkout/compile Defects4J และสร้าง target/API metadata |
| [construction.py](construction.py) | สร้าง receiver/setup ผ่าน public API แบบจำกัดขอบเขต |
| [algorithms/](algorithms/) | Hill Climbing, AVM และ candidate archive |
| [ai/](ai/) | Gateway client ของ GPT และ Gemini |
| [harness/CandidateRunner.java](harness/CandidateRunner.java) | รัน candidate ใน Java และส่งพฤติกรรมกลับ |
| [evaluate.py](evaluate.py) | สร้าง assertions, compile/run JUnit, candidate fitness, JaCoCo |
| [analyze.py](analyze.py) | อ่าน/deduplicate raw JSON และสรุปมาตรฐาน |
| [tools/report_analysis.py](tools/report_analysis.py) | ผลแยก experiment, เคสร่วม, errors/detection และ audit |
| [tools/package_submission.py](tools/package_submission.py) | สร้าง archive, inventory และ checksums ซ้ำจากไฟล์ใน workspace |
| [tests/test_construction.py](tests/test_construction.py) | 10 tests ของ infrastructure; เป็นคนละชุดกับ generated Java benchmark tests |

Source ที่ส่งมอบเป็น working source จริง รวม `analyze.py` ที่ถูกแก้ไว้ก่อนงานเอกสารให้เตือนแทนปฏิเสธเมื่อพบหลาย experiment_id เก็บ diff กับ Git commit ไว้ใน [analysis_workspace.patch](docs/report_data/analysis_workspace.patch) ไม่มีการแก้ generator/evaluator/prompt/configuration เพื่อจัดทำรายงาน

## 3. Configuration, prompt และ environment

| หลักฐาน | สิ่งที่ใช้ทำซ้ำ |
| --- | --- |
| [config/cases.csv](config/cases.csv) | enabled cases 854 เคส, target/concrete overrides, target policy |
| [config/settings.json](config/settings.json) | seeds/repetitions, budgets, planner/setup limits, model strings, endpoint และ token/source caps |
| [prompts/gpt_unit_test_prompt.txt](prompts/gpt_unit_test_prompt.txt) | GPT prompt template `v1` |
| [prompts/gemini_unit_test_prompt.txt](prompts/gemini_unit_test_prompt.txt) | Gemini prompt template `v1` |
| [docker/Dockerfile](docker/Dockerfile), [compose.yaml](docker/compose.yaml) | Container dependencies, Java 11, mounts, timezone, locale |
| [requirements.txt](requirements.txt) | Python dependency range ของ benchmark |
| [.env.example](.env.example) | ชื่อตัวแปรที่ต้องตั้ง โดยไม่รวม key จริง |
| [environment_observed.json](docs/report_data/environment_observed.json) | เวอร์ชันที่ตรวจพบในเครื่องทำรายงาน แยกจาก environment เดิมที่ไม่ได้เก็บครบทุก worker |

`tools/jacoco/` รวม JAR ที่ดาวน์โหลดไว้ในเครื่องนี้ด้วยถ้ามี ส่วน Defects4J และ original project repositories ติดตั้งแยกตามคู่มือ เพื่อ checkout source fixed/buggy จาก project/bug ID ไม่ต้องแจก `.work/` ของทุกเคส

## 4. Raw results และ generated artifacts

| Worker | Task JSON | Generated Java | Actual prompts | Actual responses |
| --- | ---: | ---: | ---: | ---: |
| `member1_final` | 1,140 | 756 | 570 | 570 |
| `member2` | 1,140 | 798 | 570 | 570 |
| `worker3` | 1,136 | 854 | 567 | 566 |
| **รวม** | **3,416** | **2,408** | **1,707** | **1,706** |

Raw results อยู่ใน `results/workers/<worker>/<project>/<bug>/<method>/<run_id>.json` ส่วน code/prompt/response อยู่ใน `generated_tests/<worker>/<project>/<bug>/<method>/<run_id>/` JSON เก็บ status, validity, fault detection, coverage, timing, seed/provider, provenance และ output tails ตามที่ task นั้นทำได้

JSON อ้างถึง generated Java 2,408 ไฟล์, prompts 1,707 และ responses 1,706 ไฟล์ ซึ่งมีครบทุกไฟล์หลัง normalize path ที่ใช้ Windows `\\` เป็น `/` เก็บ JSON เดิมไว้ ไม่มีการเขียนทับเพื่อแก้ separator งานที่ error/unsupported อาจไม่มี Java/response ตามขั้นตอนที่ล้มเหลว ตัวอย่าง GPT/Time-7 มี prompt แต่ไม่มี response และ GPT/Time-26 ล้มเหลวใน preparation

ก่อนจัดเตรียม GitHub มี Java อีก 3 ไฟล์ที่ผล task ปัจจุบันไม่ได้อ้างถึง จึงย้ายไปสำรองนอกโปรเจกต์ **ไม่รวมในชุดส่งงานปัจจุบันและไม่นับคะแนน**:

1. `generated_tests/member2/Compress/42/gpt/run_1/UnixStatConstantsTest.java`
2. `generated_tests/worker3/JacksonDatabind/36/avm/seed_101/Generated_avm_JacksonDatabind_36_seed_101.java`
3. `generated_tests/worker3/JacksonDatabind/36/hill_climbing/seed_101/Generated_hill_climbing_JacksonDatabind_36_seed_101.java`

metadata ที่มีอยู่ใน `results/meta/` ครอบคลุม 288 เคสและรวมในชุดส่งงาน ส่วน `results/tmp/` มีเพียงโฟลเดอร์ว่างและถูกล้างตอนจัดเตรียม GitHub ไม่ถือว่ามี metadata/temporary coverage ครบ 854 เคส ค่าที่ใช้สรุปหลักมาจาก task JSON

## 5. รายงานผลทดสอบและการวิเคราะห์

| ไฟล์ | เนื้อหา |
| --- | --- |
| [all_results.csv](results/summary/all_results.csv) | ทุก task พร้อม worker, experiment_id, status, metrics และ path ต้นทาง |
| [summary_by_method.csv](results/summary/summary_by_method.csv) | ผลรวมทุกวิธี (รวมสอง experiment_id) |
| [summary_by_project.csv](results/summary/summary_by_project.csv) | ผลแยก project/method |
| [duplicate_tasks.csv](results/summary/duplicate_tasks.csv) | ชุดนี้มี header แต่ไม่มี task ซ้ำ |
| [docs/report_data/aggregate/](docs/report_data/aggregate/) | สรุปที่คำนวณซ้ำจาก raw และตรงกับ CSV เดิม |
| [summary_by_experiment.csv](docs/report_data/summary_by_experiment.csv) | สรุปแยกสอง experiment_id |
| [summary_common_completed.csv](docs/report_data/summary_common_completed.csv) | ผลบน 349 เคสที่ทุกวิธี completed |
| [summary_common_valid.csv](docs/report_data/summary_common_valid.csv) | ผลบน 231 เคสที่ทุกวิธี completed และ valid |
| `cases_common_*.csv`, `summary_common_*_by_experiment.csv` | รายชื่อเคสร่วม และสรุปกลุ่มนี้แยก ID |
| [detected_bugs.csv](docs/report_data/detected_bugs.csv) | Matrix 51 unique bugs ที่ตรวจพบและวิธีที่ตรวจพบ |
| [failure_breakdown.csv](docs/report_data/failure_breakdown.csv) | Compile/test failures, prompt/test counts, search budgets และมัธยฐานเวลา |
| [unsupported_reasons.csv](docs/report_data/unsupported_reasons.csv) | เหตุผล unsupported ของ HC/AVM |
| [error_tasks.csv](docs/report_data/error_tasks.csv) | รายละเอียด 9 error tasks |
| [audit.json](docs/report_data/audit.json) | Inventory, provenance, ranges และ artifact completeness; หลัง cleanup ไม่มี orphan Java ในชุดส่งงาน |
| [analysis.log](docs/report_data/analysis.log) | Console log ของการคำนวณสรุปเพื่อรายงาน ซึ่งมีคำเตือนหลาย experiment_id |
| [validation.log](docs/report_data/validation.log) | ผลตรวจเครื่องมือรายงาน, CSV, links และ infrastructure tests ครั้งจัดทำเอกสาร |

ไม่มี console `.log` จากการรัน final เดิมและโฟลเดอร์ `logs/` ว่างถูกล้างแล้ว evaluator เก็บ compile/JUnit **output tails** ใน JSON พร้อมล้าง final JaCoCo CSV/.exec หลังประเมิน จึงไม่อ้างว่าชุดส่งงานมี full execution logs หรือ full raw coverage files ทั้งหมด log ที่เพิ่มใน `docs/report_data/` เป็น log ของการจัดทำ/ตรวจรายงาน

## 6. ภาพประกอบและ diagram

Diagram กระบวนการทดลองอยู่ใน [README.md](README.md) และ [FINAL_REPORT.md](FINAL_REPORT.md) เป็น Mermaid ที่ render ได้ใน Markdown viewer ที่รองรับ มี source แยกสำหรับนำไป render/export ใน [experiment_workflow.mmd](docs/diagrams/experiment_workflow.mmd) ตารางผลในรายงานและ CSV เป็นข้อมูลสำหรับสร้างกราฟต่อโดยไม่ต้องดึงค่าจากภาพ

## 7. สิ่งที่ไม่รวมและข้อจำกัดของ reproduction

ไม่รวม `.env`/credentials, `.git`, `.venv`, `__pycache__`, compiled harness classes, `.work/`, `results/tmp/`, Windows download metadata, config/code backups, pilot/AI backups และ worker bundles ต้นฉบับที่ซ้ำกับข้อมูล final ซึ่งแตกมาแล้วใน workspace รายงานคำนวณจาก `results/workers/` ชุด final เท่านั้น ไม่รวม backup/pilot results

การจัดเตรียม GitHub วันที่ 1 ตุลาคม 2026 ย้าย checkout/ผลเก่า/bundles และ Java ที่ไม่ถูกอ้างถึงไปโฟลเดอร์สำรองนอก repository โดยเก็บ archive ฉบับก่อน cleanup ไว้ด้วย ล้างเฉพาะ cache, compiled classes, download metadata และ runtime directories ที่ว่าง ผล JSON 3,416 tasks และทุกไฟล์ที่ JSON อ้างถึงยังอยู่ครบ `.gitignore` อนุญาต `submission/sqa-final-submission.tar.gz` เพื่อให้ clone จาก GitHub แล้วแตกหลักฐานทั้งหมดได้

ไม่มี working-source/settings snapshot ที่ทำให้ได้ worker3 experiment_id `1b010d74235e8785`, environment/hardware ย้อนหลังครบทุกเครื่อง หรือ remote model snapshot การคำนวณสรุปเดิมทำซ้ำได้จาก JSON แต่การ generation ใหม่ให้เหมือนเดิมทุก byte และการพิสูจน์ environment เดิมครบทุกเครื่องยังทำไม่ได้จากหลักฐานที่มี

## 8. ตรวจและสร้างชุดส่งงานซ้ำ

```bash
# คำนวณผลและ audit โดยไม่เรียก API
python3 tools/report_analysis.py
python3 analyze.py --output docs/report_data/aggregate

# สร้าง manifest และ archive จาก final artifacts ที่มีอยู่
python3 tools/package_submission.py

# ตรวจ archive จาก project root
sha256sum -c submission/sqa-final-submission.tar.gz.sha256
```

เมื่อแตก archive แล้วตรวจ `sha256sum -c FILE_MANIFEST.sha256` ก่อนรัน benchmark/แก้ไฟล์ ในการสร้าง archive ใหม่หลังแก้รายงานหรือผล ให้รัน packager อีกครั้งเพื่อให้ checksums ตรงกับไฟล์ล่าสุด เครื่องมือ package ตรวจ hash ของสมาชิกใน archive กับ manifest และไม่รวม credentials ของ `.env`
