import os
import re
from typing import Iterable

import yaml


SECTION_KEYWORDS = {
    "personal": ["个人信息", "基本信息", "联系方式"],
    "summary": ["个人简介", "自我评价", "职业概述", "个人亮点", "个人总结"],
    "experience": ["工作经历", "工作经验", "实习经历", "职业经历"],
    "education": ["教育背景", "教育经历", "学历", "教育"],
    "skills": ["技能", "专业技能", "技术技能", "技能栈"],
    "projects": ["项目经历", "项目经验", "项目"],
}

DATE_RANGE_PATTERN = re.compile(
    r"(?P<start>\d{4}[./-]\d{1,2})\s*(?:至|到|-|–|—|~|～)\s*(?P<end>\d{4}[./-]\d{1,2}|至今|现在|Present)",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\d{4}[./-]\d{1,2}")
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")
PHONE_PATTERN = re.compile(r"(?:\+?86[-\s]?)?1[3-9]\d(?:[-\s]?\d{4}){2}")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_PATTERN = re.compile(r"(https?://\S+|(?:github|linkedin)\.com/\S+)", re.IGNORECASE)
BULLET_PREFIX_PATTERN = re.compile(r"^\s*[-•·▪●]\s*")
CITY_CANDIDATES = {
    "北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都", "武汉", "西安",
    "天津", "重庆", "长沙", "郑州", "青岛", "厦门", "合肥", "宁波", "福州", "珠海",
}
DEGREE_KEYWORDS = {
    "博士", "硕士", "本科", "大专", "中专", "PhD", "Master", "Bachelor", "Associate",
}


def parse_resume_file(file_path: str) -> dict:
    """
    Detect file type by extension (.pdf or .docx).
    Extract text, then parse into a structured dict and persist it to data/resume_base.yaml.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        raw_text = _extract_text_from_pdf(file_path)
    elif ext == ".docx":
        raw_text = _extract_text_from_docx(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Only .pdf and .docx are supported.")

    if not raw_text or not raw_text.strip():
        raise ValueError("Resume parsing failed: extracted text is empty.")

    resume_base = _parse_resume_text(raw_text)
    if not _has_meaningful_resume_content(resume_base):
        raise ValueError("Resume parsing failed: no meaningful resume content detected.")

    output_path = os.path.join("data", "resume_base.yaml")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        yaml.dump(resume_base, file, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return resume_base


def _extract_text_from_pdf(file_path: str) -> str:
    from pdfminer.high_level import extract_text

    return extract_text(file_path)


def _extract_text_from_docx(file_path: str) -> str:
    import docx

    document = docx.Document(file_path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def _parse_resume_text(raw_text: str) -> dict:
    """
    Parse extracted text into the resume_base structure with section-based heuristics.
    Missing sections are left empty instead of raising.
    """
    result = _empty_resume()
    lines = _normalize_lines(raw_text)

    sections = {key: [] for key in SECTION_KEYWORDS}
    current_section = "personal"

    for line in lines:
        detected = _detect_section(line)
        if detected:
            current_section = detected
            continue
        sections[current_section].append(line)

    _parse_personal_info(sections["personal"], result)
    result["summary"] = _parse_summary(sections["summary"])
    result["experience"] = _parse_experience(sections["experience"])
    result["education"] = _parse_education(sections["education"])
    result["skills"] = _parse_skills(sections["skills"])
    result["projects"] = _parse_projects(sections["projects"])

    return result


def _empty_resume() -> dict:
    return {
        "name": "",
        "phone": "",
        "email": "",
        "city": "",
        "linkedin": "",
        "github": "",
        "summary": "",
        "experience": [],
        "education": [],
        "skills": [],
        "projects": [],
    }


def _normalize_lines(raw_text: str) -> list[str]:
    lines = []
    for raw_line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return lines


def _detect_section(line: str) -> str:
    stripped = line.strip().rstrip(":：")
    for section, keywords in SECTION_KEYWORDS.items():
        if stripped in keywords:
            return section
    for section, keywords in SECTION_KEYWORDS.items():
        if any(keyword in stripped for keyword in keywords):
            return section
    return ""


def _parse_personal_info(lines: Iterable[str], result: dict) -> None:
    for line in lines:
        if not result["phone"]:
            phone_match = PHONE_PATTERN.search(line)
            if phone_match:
                result["phone"] = phone_match.group(0)

        if not result["email"]:
            email_match = EMAIL_PATTERN.search(line)
            if email_match:
                result["email"] = email_match.group(0)

        lower_line = line.lower()
        url_match = URL_PATTERN.search(line)
        if "github" in lower_line and not result["github"]:
            result["github"] = url_match.group(0) if url_match else line
        if "linkedin" in lower_line and not result["linkedin"]:
            result["linkedin"] = url_match.group(0) if url_match else line

        if not result["city"]:
            for city in CITY_CANDIDATES:
                if city in line:
                    result["city"] = city
                    break

    for line in lines:
        if result["name"]:
            break
        candidates = [part.strip() for part in re.split(r"[|/｜·•,，]", line) if part.strip()]
        for candidate in candidates:
            if PHONE_PATTERN.search(candidate) or EMAIL_PATTERN.search(candidate):
                continue
            if re.search(r"(github|linkedin|简历|resume|cv)", candidate, re.IGNORECASE):
                continue
            if 1 < len(candidate) <= 20:
                result["name"] = candidate
                break


def _parse_summary(lines: Iterable[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip())


def _parse_experience(lines: Iterable[str]) -> list[dict]:
    entries = []
    current = None

    for line in lines:
        date_match = DATE_RANGE_PATTERN.search(line)
        if date_match:
            if current:
                entries.append(_finalize_experience_entry(current))
            current = {
                "company": "",
                "title": "",
                "start_date": _normalize_date(date_match.group("start")),
                "end_date": _normalize_end_date(date_match.group("end")),
                "bullets": [],
            }
            header = line[:date_match.start()].strip(" -()（）|")
            company, title = _split_company_and_title(header)
            current["company"] = company
            current["title"] = title
            continue

        if current is None:
            continue

        cleaned = BULLET_PREFIX_PATTERN.sub("", line).strip()
        if line.startswith(("-", "•", "·", "▪", "●")):
            if cleaned:
                current["bullets"].append(cleaned)
        elif not current["title"]:
            current["title"] = cleaned
        elif cleaned:
            current["bullets"].append(cleaned)

    if current:
        entries.append(_finalize_experience_entry(current))
    return entries


def _finalize_experience_entry(entry: dict) -> dict:
    entry["bullets"] = [bullet for bullet in entry.get("bullets", []) if bullet][:10]
    return entry


def _split_company_and_title(header: str) -> tuple[str, str]:
    separators = [" - ", " | ", " / ", "｜", "，", ","]
    for separator in separators:
        if separator in header:
            left, right = header.split(separator, 1)
            return left.strip(), right.strip()
    parts = header.split()
    if len(parts) >= 2:
        return parts[0].strip(), " ".join(parts[1:]).strip()
    return header.strip(), ""


def _parse_education(lines: Iterable[str]) -> list[dict]:
    entries = []
    for line in lines:
        if not line.strip():
            continue
        parts = [part.strip() for part in re.split(r"[|/｜]", line) if part.strip()]
        if len(parts) == 1:
            parts = line.split()

        entry = {
            "school": "",
            "degree": "",
            "major": "",
            "graduation_year": "",
        }
        year_match = YEAR_PATTERN.search(line)
        if year_match:
            entry["graduation_year"] = year_match.group(0)

        for part in parts:
            if not entry["degree"] and any(keyword.lower() in part.lower() for keyword in DEGREE_KEYWORDS):
                entry["degree"] = part
            elif not entry["school"] and not YEAR_PATTERN.fullmatch(part):
                entry["school"] = part
            elif not entry["major"] and not YEAR_PATTERN.fullmatch(part):
                entry["major"] = part

        if not entry["degree"]:
            for keyword in DEGREE_KEYWORDS:
                if keyword.lower() in line.lower():
                    entry["degree"] = keyword
                    break

        if entry["school"] or entry["degree"] or entry["major"]:
            entries.append(entry)
    return entries


def _parse_skills(lines: Iterable[str]) -> list[dict]:
    skills = []
    for line in lines:
        if not line.strip():
            continue

        if "：" in line:
            category, items_text = line.split("：", 1)
        elif ":" in line:
            category, items_text = line.split(":", 1)
        else:
            category, items_text = "技能", line

        items = [
            item.strip()
            for item in re.split(r"[,，/、;；]+", items_text)
            if item.strip()
        ]
        if items:
            skills.append({"category": category.strip() or "技能", "items": items})
    return skills


def _parse_projects(lines: Iterable[str]) -> list[dict]:
    projects = []
    current = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if line.startswith(("-", "•", "·", "▪", "●")):
            if current:
                bullet = BULLET_PREFIX_PATTERN.sub("", line).strip()
                if bullet:
                    current["bullets"].append(bullet)
            continue

        if current is None or current["description"]:
            if current:
                projects.append(current)
            current = {"name": stripped, "description": "", "tech_stack": [], "bullets": []}
            continue

        if re.search(r"(技术栈|Tech|Stack)", stripped, re.IGNORECASE):
            _, _, items_text = stripped.partition("：")
            if not items_text:
                _, _, items_text = stripped.partition(":")
            current["tech_stack"] = [
                item.strip() for item in re.split(r"[,，/、;；]+", items_text) if item.strip()
            ]
        else:
            current["description"] = stripped

    if current:
        projects.append(current)
    return projects


def _normalize_date(value: str) -> str:
    parts = re.split(r"[./-]", value)
    if len(parts) != 2:
        return value
    year, month = parts
    return f"{year}-{int(month):02d}"


def _normalize_end_date(value: str) -> str:
    if value.lower() == "present" or value in {"至今", "现在"}:
        return "Present"
    return _normalize_date(value)


def _has_meaningful_resume_content(resume_data: dict) -> bool:
    simple_fields = ["name", "phone", "email", "summary", "city", "github", "linkedin"]
    if any(resume_data.get(field) for field in simple_fields):
        return True
    return any(resume_data.get(field) for field in ["experience", "education", "skills", "projects"])
