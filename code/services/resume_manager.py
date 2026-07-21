import copy
import os

import yaml


class ResumeManager:
    def __init__(
        self,
        base_yaml_path: str = "data/resume_base.yaml",
        template_path: str = "templates/resume.html",
        output_dir: str = "output/resumes",
    ):
        self.base_yaml_path = base_yaml_path
        self.template_path = template_path
        self.output_dir = output_dir

    def load_base(self) -> dict:
        """Load and return resume_base.yaml as dict. Raise FileNotFoundError if missing."""
        if not os.path.exists(self.base_yaml_path):
            raise FileNotFoundError(f"Resume base not found: {self.base_yaml_path}")

        with open(self.base_yaml_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        return data

    def is_available(self) -> bool:
        """Return True if resume_base.yaml exists and is non-empty."""
        if not os.path.exists(self.base_yaml_path):
            return False
        try:
            return bool(self.load_base())
        except Exception:
            return False

    def apply_patch(self, base: dict, patch: dict) -> dict:
        """
        Apply resume_patch to a copy of base resume without mutating base.
        """
        patched = copy.deepcopy(base)
        patch = patch or {}

        summary = patch.get("summary")
        if isinstance(summary, str) and summary.strip():
            patched["summary"] = summary.strip()

        highlights = patch.get("highlights") or []
        highlights = [item.strip() for item in highlights if isinstance(item, str) and item.strip()][:3]
        if highlights and patched.get("experience"):
            first_experience = patched["experience"][0]
            bullets = list(first_experience.get("bullets") or [])
            first_experience["bullets"] = highlights + bullets

        return patched

    def render_pdf(self, resume_data: dict, job_id: str) -> str:
        """
        Render the resume template with Jinja2 and export it to PDF through WeasyPrint.
        """
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise RuntimeError(
                "WeasyPrint is not installed. Install it with:\n"
                "  pip install weasyprint\n"
                "On Linux you may also need: apt-get install libpango-1.0-0 libharfbuzz0b libpangoft2-1.0-0"
            ) from exc

        os.makedirs(self.output_dir, exist_ok=True)

        template_abspath = os.path.abspath(self.template_path)
        template_dir = os.path.dirname(template_abspath)
        template_name = os.path.basename(template_abspath)

        env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(template_name)
        html = template.render(resume=resume_data)

        output_path = os.path.abspath(os.path.join(self.output_dir, f"{job_id}.pdf"))
        HTML(string=html, base_url=template_dir).write_pdf(output_path)
        return output_path

    def generate_for_job(self, job_id: str, patch: dict) -> str:
        """
        Load base resume, apply patch, then render a job-specific PDF.
        """
        base = self.load_base()
        patched = self.apply_patch(base, patch)
        return self.render_pdf(patched, job_id)
