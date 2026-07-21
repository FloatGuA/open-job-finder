# Task 006 — Resume Parser, Manager & GenerateResumeTool

## 目标
Implement resume upload parsing (Boss直聘 PDF/Word → YAML), resume patching and PDF rendering (Jinja2 + WeasyPrint), and the GenerateResumeTool.

## 上下文
- 依赖：Task 001 (schemas.py, services/logger.py, services/exceptions.py), Task 003 (services/llm_client.py, services/llm_parser.py)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### 1. `services/resume_parser.py` — Boss直聘 Resume Parser

Parse Boss直聘 exported PDF or Word (.docx) files into a structured YAML dict.

```python
def parse_resume_file(file_path: str) -> dict:
    """
    Detect file type by extension (.pdf or .docx).
    Extract text, then parse into structured dict.
    Return the resume_base dict (see schema below).
    Raise ValueError if file type unsupported or parsing fails badly.
    """

def _extract_text_from_pdf(file_path: str) -> str:
    """Use pdfminer.six: from pdfminer.high_level import extract_text"""

def _extract_text_from_docx(file_path: str) -> str:
    """Use python-docx: doc.paragraphs[i].text joined with newlines."""

def _parse_resume_text(raw_text: str) -> dict:
    """
    Parse extracted text into structured dict using heuristic section detection.
    Look for section headers like: 个人信息, 工作经历, 教育背景, 技能, 项目经历
    Return structured dict matching resume_base schema.
    """
```

**`resume_base.yaml` schema** (the dict structure to produce):
```yaml
# Personal info
name: ""
phone: ""
email: ""
city: ""
linkedin: ""
github: ""

# Professional summary
summary: ""

# Work experience (list)
experience:
  - company: ""
    title: ""
    start_date: ""   # "2022-03"
    end_date: ""     # "2024-01" or "Present"
    bullets:
      - ""

# Education
education:
  - school: ""
    degree: ""
    major: ""
    graduation_year: ""

# Skills
skills:
  - category: "编程语言"
    items: ["Python", "Go"]
  - category: "框架"
    items: ["FastAPI", "Django"]

# Projects
projects:
  - name: ""
    description: ""
    tech_stack: []
    bullets: []
```

#### Implementation Notes

- Parsing heuristics: split text by lines, detect section headers with a keyword list.
- Work experience: look for date patterns `\d{4}[./-]\d{2}` to split entries.
- If a section cannot be parsed, leave it as empty string / empty list — never raise on missing sections.
- Save the result to `data/resume_base.yaml` using `yaml.dump(..., allow_unicode=True, default_flow_style=False)`.

### 2. `services/resume_manager.py` — Resume Manager

```python
class ResumeManager:
    def __init__(self, base_yaml_path: str = "data/resume_base.yaml",
                 template_path: str = "templates/resume.html",
                 output_dir: str = "output/resumes"):
        ...

    def load_base(self) -> dict:
        """Load and return resume_base.yaml as dict. Raise FileNotFoundError if missing."""

    def is_available(self) -> bool:
        """Return True if resume_base.yaml exists and is non-empty."""

    def apply_patch(self, base: dict, patch: dict) -> dict:
        """
        Apply resume_patch (from ScoreResult) to a copy of base resume.
        patch format: {"summary": "new summary text", "highlights": ["bullet1", "bullet2"]}

        Rules:
        - If patch["summary"] is non-empty, replace base["summary"].
        - If patch["highlights"] is non-empty, prepend these bullets to the
          first work experience entry's bullets list (limited to 3 additional bullets).
        - Return the patched copy (do not mutate base).
        """

    def render_pdf(self, resume_data: dict, job_id: str) -> str:
        """
        1. Render resume_data using Jinja2 template at template_path.
        2. Convert HTML to PDF using WeasyPrint.
        3. Save to {output_dir}/{job_id}.pdf (create dir if needed).
        4. Return the absolute path to the generated PDF.
        """

    def generate_for_job(self, job_id: str, patch: dict) -> str:
        """
        Convenience method:
        1. base = load_base()
        2. patched = apply_patch(base, patch)
        3. return render_pdf(patched, job_id)
        """
```

### 3. `templates/resume.html` — Boss直聘 Style Resume Template

Create a clean, professional HTML resume template using Jinja2 syntax. The template should:

- Be designed for A4 paper (210mm × 297mm), single page preferred.
- Use inline CSS (no external dependencies) for WeasyPrint compatibility.
- Sections: header (name, contact), summary, experience, education, skills, projects.
- Use `{{ resume.name }}`, `{{ resume.summary }}`, `{% for job in resume.experience %}` etc.
- Font: use system fonts (Arial, Helvetica, sans-serif) — no Google Fonts (no internet in rendering).
- Color scheme: black text on white, with a thin colored bar at the top (use #2E5BFF or similar).
- Each section should gracefully handle empty data (use `{% if resume.summary %}`).

Template variables available:
```
resume.name, resume.phone, resume.email, resume.city, resume.linkedin, resume.github
resume.summary
resume.experience[]  (company, title, start_date, end_date, bullets[])
resume.education[]   (school, degree, major, graduation_year)
resume.skills[]      (category, items[])
resume.projects[]    (name, description, tech_stack[], bullets[])
```

### 4. `tools/generate_resume.py` — GenerateResumeTool

```python
class GenerateResumeTool:
    name = "generate_resume"
    description = "Generate a tailored PDF resume for a specific job."

    def __init__(self, resume_manager: ResumeManager):
        ...

    def execute(self, job: Job, score_result: ScoreResult) -> dict:
        """
        1. Check resume_manager.is_available(). If not, return {"pdf_path": None, "error": "resume_base.yaml not found"}.
        2. Call resume_manager.generate_for_job(job.job_id, score_result.resume_patch).
        3. Return {"pdf_path": str(absolute_path)}.
        On exception: return {"pdf_path": None, "error": str(e)}.
        """
```

## 文件清单

- `code/services/resume_parser.py`：parse_resume_file + helper functions
- `code/services/resume_manager.py`：ResumeManager class
- `code/templates/resume.html`：Jinja2 resume template
- `code/tools/generate_resume.py`：GenerateResumeTool

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# Test 1: Import check
python -c "
from services.resume_parser import parse_resume_file
from services.resume_manager import ResumeManager
from tools.generate_resume import GenerateResumeTool
print('imports OK')
"

# Test 2: ResumeManager with synthetic data
python -c "
import os
from services.resume_manager import ResumeManager
import yaml

# Create a test resume_base.yaml
test_data = {
    'name': 'Zhang San',
    'phone': '138-0000-0000',
    'email': 'zhangsan@example.com',
    'city': 'Beijing',
    'linkedin': '',
    'github': 'github.com/zhangsan',
    'summary': 'Experienced Python engineer with 3 years in backend development.',
    'experience': [
        {
            'company': 'Test Corp',
            'title': 'Backend Engineer',
            'start_date': '2021-07',
            'end_date': 'Present',
            'bullets': ['Built REST APIs with FastAPI', 'Optimized database queries']
        }
    ],
    'education': [
        {'school': 'Beijing University', 'degree': 'Bachelor', 'major': 'Computer Science', 'graduation_year': '2021'}
    ],
    'skills': [
        {'category': 'Languages', 'items': ['Python', 'Go', 'SQL']},
        {'category': 'Frameworks', 'items': ['FastAPI', 'Django']}
    ],
    'projects': []
}
os.makedirs('data', exist_ok=True)
with open('data/test_resume.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(test_data, f, allow_unicode=True)

rm = ResumeManager(base_yaml_path='data/test_resume.yaml')
assert rm.is_available(), 'is_available should be True'

# Test apply_patch
base = rm.load_base()
patch = {'summary': 'Senior Python engineer specializing in AI systems.', 'highlights': ['Led AI pipeline development']}
patched = rm.apply_patch(base, patch)
assert patched['summary'] == patch['summary'], 'summary patch failed'
print('apply_patch OK')

# Test PDF rendering
try:
    pdf_path = rm.render_pdf(patched, 'test_smoke')
    assert os.path.exists(pdf_path), f'PDF not created at {pdf_path}'
    print('PDF rendered OK at:', pdf_path)
except Exception as e:
    print('PDF rendering failed (WeasyPrint may need system deps):', e)

os.remove('data/test_resume.yaml')
"

# Test 3: Resume parser with plain text simulation
python -c "
from services.resume_parser import _parse_resume_text
sample = '''
个人信息
张三 | 138-0000-0000 | zhangsan@example.com | 北京

工作经历
测试公司 - 后端工程师 (2021.07 - 至今)
- 使用FastAPI开发REST接口
- 优化数据库查询性能

教育背景
北京大学 计算机科学 本科 2021年
'''
result = _parse_resume_text(sample)
print('parsed sections:', list(k for k,v in result.items() if v))
print('resume_parser OK')
"
```

<!-- FACTORY:DONE -->
