"""简历文件的**原始内容提取**——只负责"把文件变成模型能读的东西"，不做解析。

原本这个文件还有一套 377 行的正则解析器（`parse_resume_file` 及其一大堆
`_parse_xxx` 辅助函数），把简历文本硬解成 `data/resume_base.yaml` 那套结构
（name/phone/email/city/linkedin/github/summary/experience/education/skills/projects）。

**那条路 v2.14 视觉解析上线后就被绕过了，但一直没删**（2026-08-15 清理）：
- 现役上传路径是 `dashboard/server.py::_parse_resume_upload`
  → PDF 走 `render_pdf_to_images` + 视觉模型，docx 走 `_extract_text_from_docx` + LLM，
    两条最后都写**信息池 / 块库**；
- 唯一还调 `parse_resume_file` 的是 CLI 首次引导（`onboarding._step4_import_resume`），
  于是 `resume_base.yaml` 成了同一个人的**第三套表示**，跟 `info_pool.yaml` 各存各的，
  谁也不同步谁。留着它只会让"个人信息到底以哪份为准"永远说不清。

现在这里只剩两个真正在用的提取函数。解析（把内容变成结构）全部归
`services/resume_blocks.py`，存储全部归信息池。
"""


def render_pdf_to_images(file_path: str, dpi: int = 150, max_pages: int = 4) -> list[str]:
    """把 PDF 每页渲染成 PNG，返回原始 base64 字符串列表（无 data-URI 前缀）。

    供视觉模型解析用（qwen2.5vl / claude vision）——排版型简历的正则文本提取会丢结构，
    直接喂页面图片让视觉模型读。简历一般 1-2 页，max_pages 兜底防超长文档。
    """
    import base64

    import fitz  # PyMuPDF

    images: list[str] = []
    doc = fitz.open(file_path)
    try:
        for page in doc[:max_pages]:
            pix = page.get_pixmap(dpi=dpi)
            images.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    finally:
        doc.close()
    return images


def _extract_text_from_docx(file_path: str) -> str:
    import docx

    document = docx.Document(file_path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs)
