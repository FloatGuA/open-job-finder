# Task 023 — 修复 app.js 中所有乱码中文字符串

## 背景

由于之前某次 codex 迭代以 GBK 编码读取了 UTF-8 文件，`dashboard/static/app.js` 中多处中文字符串被损坏为乱码（如 `鎼滅储` 代替 `搜索`）。语法错误已在上一轮修复，但以下显示字符串仍是乱码，用户在界面上会看到乱码文字。

本 task 只做**最小替换**：仅替换乱码字符串本身，不修改任何逻辑、变量名、函数结构，不重写文件。

---

## 修复范围

### 1. WORKFLOW_STEPS（约第 160 行）

当前：
```js
['search', '鎼滅储'],
['score', '璇勫垎'],
['critique', '瀹℃牳'],
['done', '瀹屾垚'],      // apply workflow 的 done
['open_chat', '鎵撳紑鑱婂ぉ'],
['classify', '娑堟伅鍒嗙被'],
['done', '瀹屾垚'],      // check workflow 的 done
```

修复后（使用 `\uXXXX` escape，不写裸中文）：
```js
['search', '\u641C\u7D22'],
['score', '\u8BC4\u5206'],
['critique', '\u5BA1\u6838'],
['done', '\u5B8C\u6210'],   // apply workflow done
['open_chat', '\u6253\u5F00\u804A\u5929'],
['classify', '\u6D88\u606F\u5206\u7C7B'],
['done', '\u5B8C\u6210'],   // check workflow done
```

### 2. PAGE_TITLES（约第 181 行）

当前：
```js
jobs:         '鑱屼綅杩涘害',
chat:         'HR 浼氳瘽',
profile:      '姹傝亴鍋忓ソ',
setup:        '鐜閰嶇疆',
'dev-logs':   '杩愯鏃ュ織',
```

修复后：
```js
jobs:         '\u804C\u4F4D\u8FDB\u5EA6',
chat:         'HR \u4F1A\u8BDD',
profile:      '\u6C42\u804C\u504F\u597D',
setup:        '\u73AF\u5883\u914D\u7F6E',
'dev-logs':   '\u8FD0\u884C\u65E5\u5FD7',
```

### 3. BOSS_CITY_CODES（约第 42 行）

当前所有城市名 key 均为乱码，修复为：
```js
const BOSS_CITY_CODES = {
  '\u5168\u56FD': '100010000',
  '\u5317\u4EAC': '101010100',
  '\u4E0A\u6D77': '101020100',
  '\u5E7F\u5DDE': '101280100',
  '\u6DF1\u5733': '101280600',
  '\u676D\u5DDE': '101210100',
  '\u6210\u90FD': '101270100',
  '\u5357\u4EAC': '101190100',
  '\u6B66\u6C49': '101200100',
  '\u897F\u5B89': '101110100',
  '\u91CD\u5E86': '101040100',
  '\u5929\u6D25': '101030100',
  '\u82CF\u5DDE': '101190400',
  '\u5408\u80A5': '101220100',
  '\u90D1\u5DDE': '101180100',
  '\u957F\u6C99': '101250100',
  '\u6D4E\u5357': '101120100',
  '\u9752\u5C9B': '101120200',
  '\u53A6\u95E8': '101230200',
  '\u5B81\u6CE2': '101210400',
  '\u65E0\u9521': '101190200',
};
```

### 4. BOSS_EXPERIENCE_CODES（约第 51 行）

当前所有 key 乱码（含尾部 `?`），修复为：
```js
const BOSS_EXPERIENCE_CODES = {
  '\u7ECF\u9A8C\u4E0D\u9650': '101',
  '\u5728\u6821\u751F': '108',
  '\u5E94\u5C4A\u751F': '102',
  '1\u5E74\u4EE5\u5185': '103',
  '1-3\u5E74': '104',
  '3-5\u5E74': '105',
  '5-10\u5E74': '106',
  '10\u5E74\u4EE5\u4E0A': '107',
};
```

### 5. BOSS_DEGREE_CODES（约第 55 行）

当前乱码，修复为：
```js
const BOSS_DEGREE_CODES = {
  '\u521D\u4E2D\u53CA\u4EE5\u4E0B': '209',
  '\u4E2D\u4E13/\u4E2D\u6280': '208',
  '\u9AD8\u4E2D': '206',
  '\u5927\u4E13': '202',
  '\u672C\u79D1': '203',
  '\u786C\u58EB': '204',
  '\u535A\u58EB': '205',
};
```

注意：`'涓笓/涓妧': '208'` 这一条原始值为 `中专/中技`，key 里有斜杠，需保留。

### 6. BOSS_SALARY_CODES（约第 59 行）

当前含乱码 key：
```js
'3K浠ヤ笅': '402',   // 3K以下
'50K浠ヤ笂': '407',  // 50K以上
```

修复为：
```js
const BOSS_SALARY_CODES = {
  '3K\u4EE5\u4E0B': '402',
  '3-5K': '403',
  '5-10K': '404',
  '10-20K': '405',
  '20-50K': '406',
  '50K\u4EE5\u4E0A': '407',
};
```

### 7. BOSS_JOB_TYPE_CODES（约第 63 行）

当前乱码，修复为：
```js
const BOSS_JOB_TYPE_CODES = {
  '\u5168\u804C': '1901',
  '\u5B9E\u4E60': '1902',
  '\u517C\u804C': '1903',
};
```

> Unicode 对照：全职 \u5168\u804C，实习 \u5B9E\u4E60，兼职 \u517C\u804C

### 8. BOSS_FINANCING_CODES（约第 66 行）

当前所有含 `?` 的 key 为乱码，修复为：
```js
const BOSS_FINANCING_CODES = {
  '\u672A\u878D\u8D44': '801',
  '\u5929\u4F7F\u8F6E': '802',
  'A\u8F6E': '803',
  'B\u8F6E': '804',
  'C\u8F6E': '805',
  'D\u8F6E\u53CA\u4EE5\u4E0A': '806',
  '\u5DF2\u4E0A\u5E02': '807',
  '\u4E0D\u9700\u8981\u878D\u8D44': '808',
};
```

### 9. buildBossSearchUrl 中的默认城市（约第 73 行）

当前：
```js
const cityName  = (profile.cities || [])[0] || '鍏ㄥ浗';
```

修复为：
```js
const cityName  = (profile.cities || [])[0] || '\u5168\u56FD';
```

---

## 额外扫描要求

完成上述替换后，请扫描整个文件中**所有包含非 ASCII 字符（字节 > 0x7F）的字符串字面量**（包括注释），逐一判断：

- 如果是合法 UTF-8 中文（如 `\u5F00\u59CB`），保持不变
- 如果显示为乱码（如 `鎵撳紑`），说明是 GBK 误读，按语境推断正确中文后替换为 `\uXXXX` escape

重点排查：
- 所有 `toast(...)` 调用中的消息文本
- 所有 `innerHTML = ...` 或 `textContent = ...` 中的中文
- 所有注释（`//` 和 `/* */`）中的乱码（注释乱码不影响功能，但优先级低，可跳过）

---

## 验证要求

1. `node --check dashboard/static/app.js` 必须通过（无语法错误）
2. 所有替换必须是**纯字符串内容替换**，不改变任何逻辑
3. 不新增任何功能或注释

---

## 工作范围

**仅修改文件**：`dashboard/static/app.js`

不修改任何其他文件。
