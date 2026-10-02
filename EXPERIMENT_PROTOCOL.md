# Experiment Protocol

เอกสารนี้ระบุวิธีประเมินตามโค้ดและ configuration ที่ส่งมอบ รวมถึงความแตกต่างที่พบในผลจริง รายงานผลอยู่ใน [FINAL_REPORT.md](FINAL_REPORT.md) และคำสั่งทำซ้ำอยู่ใน [Howtouse.md](Howtouse.md)

## 1. วัตถุประสงค์และหน่วยการทดลอง

เปรียบเทียบ Hill Climbing, AVM, GPT และ Gemini ในด้านความสามารถสร้างเทสต์ที่ใช้ได้ การตรวจบั๊ก coverage และเวลา มี 854 enabled cases จาก 17 โปรเจกต์ หนึ่ง task หมายถึง `(project, bug_id, method, run_id)` ซึ่งอาจมีหลาย JUnit `@Test` อยู่ในหนึ่งชุดเทสต์

HC/AVM ใช้ `seeds = [101]` ส่วน GPT/Gemini ใช้ `ai_repetitions = 1` จึงคาดหวัง 3,416 tasks การทดลองนี้ไม่มีการทำซ้ำหลาย seed หรือหลาย AI response สำหรับประเมินความแปรปรวน

## 2. การแบ่งงานและ provenance

เรียง enabled cases ตาม `(project, int(bug_id))` แล้วแบ่งช่วงแบบ 1-based inclusive:

| **ช่วง** | **worker ในผลจริง** | **เคส** | **tasks** | **experiment_id** |
| -------- | ------------------- | ------- | --------- | ------------------ |
| 1–285 | `member1_final` | 285 | 1,140 | `9f661b38cc1eee98` |
| 286–570 | `member2` | 285 | 1,140 | `9f661b38cc1eee98` |
| 571–854 | `worker3` | 284 | 1,136 | `1b010d74235e8785` |

ทั้งสี่วิธีของแต่ละเคสรันบน worker ที่รับผิดชอบเคสนั้น และทุกผลบันทึก commit `d7f55a4e608de5ae552bdccdb52acf50b2d62b14`

ผลลัพธ์ปรากฏ `experiment_id` สองค่า เนื่องจากไฟล์ source/config/prompt บนแต่ละ workspace ใช้รูปแบบ **End of Line (EOL) ต่างกัน** เช่น `LF` และ `CRLF` แม้เนื้อหาของไฟล์จะเหมือนกันในเชิงตรรกะก็ตาม เนื่องจาก `experiment_id()` ใน `run.py` คำนวณ hash จากข้อมูลของไฟล์ที่เกี่ยวข้อง ความแตกต่างของ EOL จึงทำให้ byte representation ของไฟล์ต่างกันและส่งผลให้ค่า hash หรือ `experiment_id` ต่างกัน

ดังนั้น ความแตกต่างระหว่าง `9f661b38cc1eee98` และ `1b010d74235e8785` ไม่ได้หมายความว่ามีการใช้ configuration หรือวิธีการทดลองที่แตกต่างกัน แต่เกิดจากรูปแบบ EOL ของไฟล์ในแต่ละ workspace แตกต่างกัน ทั้งสองกลุ่มยังคงใช้ source, configuration และ prompt ที่มีเนื้อหาเดียวกันสำหรับการทดลอง

## 3. ข้อมูลที่ใช้สร้างเทสต์

- ใช้ fixed revision สำหรับการค้นหา อ่าน source/API และสร้าง oracle
- ไม่ส่ง buggy source, patch, diff, issue, triggering test หรือ known failing developer test ให้ generator
- เมื่อ `target_class` ว่าง ใช้ `classes.modified` ของ Defects4J เป็น fallback จึงทราบตำแหน่งระดับคลาส แต่ไม่ได้รับตำแหน่งบรรทัดจาก patch
- ทั้งสี่วิธีเลือกจาก eligible public target methods ตาม metadata จำกัดไม่เกิน 5 methods แต่ AI ยังรันได้เมื่อ eligible list ว่าง โดย prompt มี `TARGET METHODS: none`
- Prompt จริงมีชื่อ project, bug ID, target/concrete class, public API และ fixed source ที่เลือกไว้ การระบุ bug ID และการใช้โมเดลที่ไม่ทราบ training data ทำให้ไม่สามารถตัดความเสี่ยงการจดจำ benchmark ได้ทั้งหมด
- GPT/Gemini ใช้ template คนละไฟล์และคำแนะนำการคิดต่างกัน ผลจึงเป็นการเปรียบเทียบ model พร้อม prompt ของแต่ละเครื่องมือ

## 4. ขอบเขต HC/AVM

target arguments รองรับ primitive และ `String` โดยตัวเลขและสตริงมีขอบเขตตาม `algorithms/hill_climbing.py` และ `algorithms/avm.py` เช่น int/long ในช่วง -1000 ถึง 1000 และชุดสตริงขนาดเล็ก ไม่ใช่การค้นหา input ของ Java ทุกประเภท

construction planner รองรับ public constructors, exact-type public factories, public default/singleton fields, primitive/boxed/String, enums, empty arrays, common collections, stream/reader/writer แบบง่าย และการค้นหา concrete subtype ภายในขอบเขต ค่า constructor/factory เป็นค่าโครงสร้างคงที่ ไม่เป็นตัวแปรค้นหา HC/AVM

planner มี cycle detection, memoization, depth/type/candidate caps และ timeout ส่วน setup sequence จำกัด public instance `void` actions, จำนวน parameters และจำนวนขั้น ไม่มี reflection access bypass หรือ `Unsafe.allocateInstance` คลาสที่เข้าถึงไม่ได้หรือ dependency graph ที่เกินขอบเขตอาจเป็น `unsupported`

Hill Climbing สำรวจ setup ตาม seed ใช้ random restart และเปลี่ยน input/setup รอบค่าปัจจุบัน AVM สำรวจ setup แบบ categorical ตามลำดับ แล้วค้นหาทีละตัวแปร รวม exploratory และ numeric pattern moves ลำดับตัวแปร AVM มีการสุ่มตาม seed

fitness ของ candidate คือ `branch_ratio + 0.001 * instruction_ratio` ของ target class บน fixed revision ไม่ใช่จำนวนบั๊กที่ตรวจพบ เก็บ candidate archive ที่ให้พฤติกรรมต่างกันก่อน แล้วเติม input/setup ที่ต่างกันได้ไม่เกิน 3 candidates ต่อ method จึงสร้างได้สูงสุด 15 `@Test` ต่อ task

## 5. Configuration ที่ส่งมอบ

ค่าครบทุก field อยู่ใน [config/settings.json](config/settings.json) ตารางนี้เป็นค่าปัจจุบันที่ hash ได้ `9f661b38cc1eee98` และไม่ได้ยืนยันว่า worker3 ใช้ configuration ทุก field ตรงกัน

| กลุ่ม | ค่า |
| --- | --- |
| Repetition | seed 101 หนึ่งครั้ง; AI หนึ่งครั้งต่อวิธี |
| Target/search | 5 methods; 20 evaluations ต่อ method; 3 archived candidates ต่อ method; HC restarts 2 |
| Runtime | candidate timeout 30 s; test timeout 45 s; algorithm budget 180 s; search budget 110 s; final reserve 60 s |
| Construction | depth 3; inspected types 24; constructors/type 8; factories/type 6; planning timeout 15 s |
| Subtype scan | 120 classes; timeout 10 s; max subtypes/type 6 |
| Stateful setup | actions 4; parameters 2; steps 2; sequences 8 |
| AI | prompt `v1`; output cap 4,096 tokens; source cap 14,000 characters |
| API | timeout 120 s; max retries 2 (รวมได้สูงสุด 3 attempts); request temperature 0 |
| GPT model string | `gpt-5.6-terra` |
| Gemini model string | `gemini-3.5-flash-lite` |
| Gateway | `https://gen.ai.kku.ac.th/api/v1/chat/completions` ทั้งสองวิธี |

ชื่อโมเดลเป็นชื่อที่ configuration และ `provider.model` บันทึกจาก gateway ไม่ได้ยืนยัน model build ภายในหรือรุ่นของผู้ให้บริการโดยตรง temperature 0 ไม่มี request seed และไม่มีการ pin remote model snapshot

AI prompt ขอไม่เกินหนึ่ง `@Test` ต่อ target method จึงต่างจาก HC/AVM ที่เก็บได้สาม candidates ต่อ method และ evaluator ไม่บังคับเพดาน AI นี้ ผลจริง Gemini มี 39 tasks ที่มากกว่า 5 tests; GPT/Gemini มี 141/277 tasks ที่จำนวน tests มากกว่า `target_method_count` ตาม metadata ซึ่งรวมกรณีไม่มี target method ด้วย ดู [failure_breakdown.csv](docs/report_data/failure_breakdown.csv)

## 6. การประเมินร่วม

1. Checkout และ compile fixed (`<bug_id>f`) และ buggy (`<bug_id>b`)
2. สร้างชุดเทสต์จาก fixed context
3. Compile และรัน JUnit บน fixed revision
4. ถ้า fixed compile หรือ test ไม่ผ่าน ให้ `valid_test = false` และไม่รัน buggy
5. ถ้า fixed ผ่าน วัด coverage และ compile/รัน source เดิมบน buggy revision
6. `fault_detected = fixed passes AND buggy compiles AND buggy test fails`
7. บันทึกผล compile/run, output tail, coverage, test path และ timing ใน JSON

ตาม evaluator การรัน buggy ไม่ผ่านพิจารณาจาก process return code ไม่ได้แยก assertion failure ออกจาก runtime/infrastructure failure ทุกประเภท งาน valid ที่เก็บ JaCoCo ไม่สำเร็จจะเป็น `error` และไม่เข้า main summary แม้มี `fault_detected = true` ใน JSON เช่น GPT/Cli-21

`completed` หมายถึงประเมินจบและอาจเป็นเทสต์ invalid ได้ `unsupported` คือ generator ไม่รองรับ/ไม่พบ candidate ในขอบเขต ส่วน `error` คือข้อผิดพลาดระหว่างเตรียม สร้าง ประเมิน หรือเก็บ coverage และ `paused_quota` คือหยุดเพราะ quota/rate-limit ที่ต้องลองใหม่

## 7. นิยามตัวชี้วัดและตัวหาร

| ตัวชี้วัด | นิยาม |
| --- | --- |
| Validity rate | `valid completed tasks / completed tasks` |
| Valid yield | `valid completed tasks / configured tasks` รวม unsupported/error ในตัวหาร |
| Fault-detecting runs | จำนวน completed runs ที่ `fault_detected = true` |
| Unique bugs detected | จำนวน `(project, bug_id)` ที่มี completed detecting run อย่างน้อยหนึ่งครั้ง |
| Bug detection rate | `unique bugs detected / unique configured bugs represented` ชุดนี้ 854 ต่อวิธี |
| Coverage | covered / (covered + missed) ของ target class บน fixed revision |
| Average coverage | ค่าเฉลี่ย ratios ของ valid completed tasks ที่มี metric ไม่ใช่ coverage รวมทั้งโปรเจกต์ |
| Generated test cases | ผลรวมจำนวน JUnit `@Test` ของทุก task รวม invalid และ error ที่นับได้ |
| Valid test cases | จำนวน `@Test` ในชุดที่ valid ทั้งชุด ไม่ได้หมายถึงประเมินแต่ละ test แยกอิสระ |
| Average test cases | ค่าเฉลี่ยจำนวน `@Test` เฉพาะ completed tasks |
| Generation/evaluation/total time | ค่าเฉลี่ย fields ที่บันทึกได้เฉพาะ completed tasks |
| Coverage/time per test | คำนวณ ratio หรือเวลาหารจำนวน `@Test` ราย task แล้วเฉลี่ย ไม่ใช่ผลรวม coverage หารผลรวม tests |

เมื่อคลาสไม่มี branch โค้ดบันทึก branch ratio 0 เมื่อ covered + missed เป็น 0 จึงไม่ตีความทุกค่า 0 ว่าเทสต์พลาด branch จริง ค่าที่หายไปไม่แทนด้วย 0 ยกเว้นการนับ test cases ที่ไม่มีค่าจะนับ 0 ตาม `analyze.py`

algorithm budget เริ่มหลัง checkout/compile/metadata preparation เวลา `duration_sec` ไม่รวมการเตรียมดังกล่าว แต่เวลา HC/AVM generation รวมการรัน candidate และ JaCoCo ระหว่างค้นหา ส่วน AI generation รวม prompt, API/retry และแปลง response จึงไม่ใช่เวลา wall clock ของการทดลองทั้งระบบ และไม่ใช่ budget แบบเดียวกันระหว่าง search กับ API

## 8. การวิเคราะห์ผลและข้อจำกัดการเปรียบเทียบ

ส่งทั้งผลรวม 854 เคส ผลแยก experiment_id ผลบน 349 เคสที่ทุกวิธี completed และผลบน 231 เคสที่ทุกวิธี completed และ valid กลุ่มเคสร่วมช่วยลดความต่างของเคสในการเปรียบเทียบ แต่เลือกเฉพาะเคสที่ทุกวิธีทำได้ และไม่แก้ปัญหาสอง experiment_id จำนวน tests ต่างกัน หรือเครื่อง/โปรเจกต์ต่างกัน

`analyze.py` ใน workspace เตือนแล้วอนุญาตให้รวมหลาย ID; ฉบับใน Git commit เดิมปฏิเสธการรวมหลาย ID ความต่างนี้เก็บใน [analysis_workspace.patch](docs/report_data/analysis_workspace.patch) ไม่มีการแก้ generator/evaluator เพื่อจัดทำรายงาน

ไม่มีการทดสอบนัยสำคัญทางสถิติจากหลาย repetitions ไม่มีข้อมูลราคา API หรือสเปก hardware ของทุก worker จึงไม่สรุปความเหนือกว่าทั่วไป ความคุ้มค่าทางราคา หรือความเร็วบนเครื่องเดียวกันจากตารางรวม

## 9. เงื่อนไขทำซ้ำและส่งมอบ

เก็บ raw JSON และไฟล์ generated ต้นฉบับไว้โดยไม่แก้ path/ผลลัพธ์ Path จาก worker3 ใช้ `\\` ให้เปลี่ยนเป็น `/` เฉพาะเวลาเปิดไฟล์บน Linux เครื่องมือรายงานตรวจว่าทุก artifact ที่ JSON อ้างถึงมีจริงหลัง normalize

ผลสรุปเดิมสามารถทำซ้ำจาก raw JSON ด้วย source ที่ส่งมอบ การประเมิน Java เดิมต้องสร้าง environment/metadata ใหม่ ส่วนการสร้าง AI ใหม่อาจได้ผลต่างแม้ใช้ prompt เดิม เพราะไม่มี remote model snapshot ของการทดลองเดิม วิธีทำซ้ำและรายการสิ่งที่ขาดระบุใน [Howtouse.md](Howtouse.md) และ [ARTIFACTS.md](ARTIFACTS.md)
