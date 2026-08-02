import getpass
import importlib.util
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

from services.exceptions import SessionExpiredError

logger = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class OnboardingChecker:
    def __init__(
        self,
        profile_path: str = "data/profile.yaml",
        resume_yaml_path: str = "data/resume_base.yaml",
        session_path: str = "data/session.json",
        config: dict = None,
        config_path: str = "config.yaml",
        resume_blocks_path: str = "data/resume_blocks.yaml",
    ):
        self.profile_path = profile_path
        self.resume_yaml_path = resume_yaml_path
        self.resume_blocks_path = resume_blocks_path
        self.session_path = session_path
        self.config = config or {}
        self.config_path = config_path

    def _file_non_empty(self, path: str) -> bool:
        return os.path.exists(path) and os.path.getsize(path) > 0

    def _check_llm_provider(self) -> bool:
        from services.llm_client import build_llm_client

        providers_config = self.config.get("llm", {}).get("providers", {})
        chain_names = list(providers_config.keys()) if isinstance(providers_config, dict) else []
        if not chain_names:
            chain_names = ["scoring", "generation"]

        for chain_name in chain_names:
            try:
                chain = build_llm_client(self.config, chain_name)
            except Exception:
                continue
            if chain.available_providers:
                return True
        return False

    def _blocks_available(self) -> bool:
        from services import resume_blocks
        pool_path = os.path.join(os.path.dirname(self.resume_blocks_path) or "data", "info_pool.yaml")
        try:
            return resume_blocks.is_available(self.resume_blocks_path) or resume_blocks.is_available(pool_path)
        except Exception:
            return False

    def check_all(self) -> dict:
        profile_ok = self._file_non_empty(self.profile_path)
        # 简历就绪 = 旧 resume_base.yaml（onboarding CLI 写）或块库 resume_blocks.yaml
        # （dashboard 上传的单一真相）任一存在。dashboard 视觉/文本解析都写块库。
        resume_ok = self._file_non_empty(self.resume_yaml_path) or self._blocks_available()
        session_ok = os.path.exists(self.session_path)
        llm_ok = self._check_llm_provider()
        return {
            "profile": profile_ok,
            "resume": resume_ok,
            "session": session_ok,
            "llm_provider": llm_ok,
            "all_ok": resume_ok and session_ok and llm_ok,
        }

    def run_interactive_setup(self) -> None:
        status = self.check_all()

        print("\n=== Step 1/4: Check Python Environment ===")
        if not self._step1_check_dependencies():
            print("Onboarding stopped at Step 1.")
            return

        print("\n=== Step 2/4: Configure LLM Provider ===")
        if not self._step2_configure_llm():
            print("Onboarding stopped at Step 2.")
            return

        print("\n=== Step 3/4: Login Boss鐩磋仒 ===")
        if status["session"] and self._session_is_valid():
            print("Session is valid. Skipping login.")
        elif not self._step3_login_boss():
            print("Onboarding stopped at Step 3.")
            return

        print("\n=== Step 4/4: Import Resume ===")
        if status["resume"]:
            redo = self._prompt_yes_no(
                "Resume already imported. Re-import? (y/n) [default: n]: ", default=False
            )
            if not redo:
                print("Keeping existing resume.")
            else:
                self._step4_import_resume()
        else:
            self._step4_import_resume()

        print("\n=== Onboarding Complete ===")
        print("Environment check: passed")
        print("LLM provider: configured")
        print("Boss鐩磋仒 session: ready")
        print("Resume: imported")
        print("Next step: 鍦?Dashboard 閰嶇疆姹傝亴鍋忓ソ锛岀劧鍚庤繍琛?python main.py --dry-run")

    def get_status(self) -> dict:
        return self.check_all()

    def _step1_check_dependencies(self) -> bool:
        required_modules = {
            "DrissionPage": "DrissionPage",
            "yaml": "PyYAML",
            "requests": "requests",
        }
        optional_modules = {
            "fastapi": "fastapi",
            "uvicorn": "uvicorn",
        }

        missing_required = [
            package_name
            for module_name, package_name in required_modules.items()
            if importlib.util.find_spec(module_name) is None
        ]
        missing_optional = [
            package_name
            for module_name, package_name in optional_modules.items()
            if importlib.util.find_spec(module_name) is None
        ]

        if missing_required:
            print(f"Missing required dependencies: {', '.join(missing_required)}")
            print("Install dependencies with: pip install -r requirements.txt")
            sys.exit(1)

        if missing_optional:
            print(f"Warning: Optional dependencies missing: {', '.join(missing_optional)}")
            print("Dashboard or PDF export features may be unavailable.")
        else:
            print("Python package dependencies look good.")

        # Verify DrissionPage can find a Chrome binary
        try:
            from DrissionPage import ChromiumOptions
            ChromiumOptions().browser_path  # triggers Chrome path resolution
            print("DrissionPage and Chrome browser are ready.")
        except Exception as exc:
            print(f"DrissionPage could not find Chrome: {exc}")
            print("Make sure Google Chrome is installed, then run: pip install DrissionPage")
            sys.exit(1)
        return True

    def _step2_configure_llm(self) -> bool:
        if self._check_llm_provider():
            redo = self._prompt_yes_no(
                "LLM provider already configured. Reconfigure? (y/n) [default: n]: ",
                default=False,
            )
            if not redo:
                print("Keeping existing LLM configuration.")
                return True

        selected_provider = (
            self._try_configure_claude_cli()
            or self._try_configure_codex_cli()
            or self._try_configure_anthropic_api()
            or self._try_configure_openai_compatible()
            or self._try_configure_ollama()
        )
        if not selected_provider:
            print("No available LLM provider was configured.")
            return False

        providers_config = self.config.setdefault("llm", {}).setdefault("providers", {})
        providers_config["scoring"] = [selected_provider]
        providers_config["generation"] = [dict(selected_provider)]
        self._write_config()
        print(f"Configured provider: {selected_provider['type']}")
        return True

    def _step3_login_boss(self) -> bool:
        # Retired: CLI browser login moved to the Dashboard (BrowserSession). Body
        # below is unreachable and goes away when onboarding is rewritten as a
        # workflow. See docs/browser-session-convergence.md.
        raise RuntimeError(
            "CLI onboarding 浏览器登录已退役：请在 Dashboard「设置 → 环境&Session」"
            "点「打开登录浏览器」完成登录（onboarding 待重写为 workflow）。"
        )

        session_path = Path(self.session_path)
        if session_path.exists():
            relogin = self._prompt_yes_no(
                "Existing session found. Re-login? (y/n) [default: n]: ",
                default=False,
            )
            if not relogin and self._session_is_valid():
                print("Reusing existing Boss鐩磋仒 session.")
                return True
            if not relogin:
                print("Existing session is invalid. Re-login is required.")

        try:
            with BrowserAgent(session_path=self.session_path) as agent:
                page = agent._require_page()
                page.get(f"{agent.BASE_URL}/web/user/?ka=header-login", timeout=30)
                print("\nBrowser window is now open. Please log in.")
                print("Waiting for login to complete (timeout: 3 min)...", flush=True)
                import time as _time
                login_url_fragment = "/web/user/"
                deadline = _time.time() + 180  # 3-minute timeout
                logged_in = False
                while _time.time() < deadline:
                    _time.sleep(2)
                    try:
                        current_url = page.url or ""
                        # Already logged in 鈫?Boss鐩磋仒 redirects away from /web/user/
                        # Just checking URL is sufficient; _assert_logged_in can
                        # misfire on the home page due to footer/hidden "鐧诲綍" text.
                        on_login_page = (
                            login_url_fragment in current_url
                            or "login" in current_url.lower()
                            or not current_url
                            or current_url == "about:blank"
                        )
                        if not on_login_page:
                            logged_in = True
                            break
                    except Exception as e:
                        print(f"Login check error: {e}", flush=True)
                        break

                if not logged_in:
                    print("\n3 minutes passed without detecting login.")
                    answer = input("If you are already logged in, press Enter to continue; input q to quit: ").strip().lower()
                    if answer == "q":
                        return False
                    # Trust user 鈥?session is in profile dir
                print("Login detected. Saving session...")
                agent.save_session()
        except Exception as exc:
            print(f"Boss鐩磋仒 login validation failed: {exc}")
            return False

        print("Session saved. Browser profile persisted.")
        return True

    def _step4_import_resume(self) -> bool:
        """Show a file picker dialog, copy the selected resume, then parse it."""
        import shutil
        from services.resume_parser import parse_resume_file

        print("\nA file picker window will open 鈥?select your resume PDF or Word file.")
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                title="Select your resume file",
                filetypes=[("Resume files", "*.pdf *.docx"), ("All files", "*.*")],
            )
            root.destroy()
        except Exception as exc:
            print(f"File picker unavailable: {exc}")
            selected = input("Please input resume file path: ").strip().strip('"')

        if not selected:
            skip = self._prompt_yes_no(
                "No file selected. Skip resume import? (y/n) [default: y]: ", default=True
            )
            if skip:
                print("Skipping resume import. You can upload via Dashboard later.")
                return True
            return False

        src = Path(selected)
        if not src.exists():
            print(f"File not found: {src}")
            return True  # non-fatal

        dest = Path("data") / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        print(f"Copied to {dest}. Parsing...")

        try:
            parse_resume_file(str(dest))
            print("Resume parsed and saved to data/resume_base.yaml")
        except Exception as exc:
            print(f"Resume parsing failed: {exc}")
            print("You can re-import later via Dashboard.")
        return True

    def _step5_create_profile(self) -> bool:
        """Interactively collect job search preferences and write data/profile.yaml."""
        if self._file_non_empty(self.profile_path):
            redo = self._prompt_yes_no(
                "Job preferences already configured. Reconfigure? (y/n) [default: n]: ",
                default=False,
            )
            if not redo:
                print("Keeping existing job preferences.")
                return True

        print("Please enter your job search preferences.")
        keywords_raw = input("Target job keywords (comma-separated, e.g. Python backend engineer, data engineer): ").strip()
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()] or ["Python backend engineer"]

        cities_raw = input("Target cities (comma-separated, e.g. 鍖椾含,涓婃捣): ").strip()
        cities = [c.strip() for c in cities_raw.split(",") if c.strip()] or ["鍖椾含"]

        salary = input("Expected salary range (e.g. 20-35k): ").strip() or "闈㈣"
        skills = input("Key skills (e.g. Python, FastAPI, PostgreSQL): ").strip() or ""
        years = input("Years of experience (e.g. 3): ").strip() or "0"

        self._create_default_profile(keywords, cities, salary, skills, years)
        return True

    def run_setup_profile(self) -> None:
        """Workflow 2 Phase A 鈥?CLI interactive job search preferences setup."""
        import questionary
        from questionary import Style

        # Boss鐩磋仒 filter options (aligned with actual search bar)
        CITIES    = ["鍖椾含", "涓婃捣", "娣卞湷", "骞垮窞", "鏉窞", "鎴愰兘", "姝︽眽", "鍗椾含", "瑗垮畨", "鍏朵粬"]
        JOB_TYPES = ["鍏ㄨ亴", "瀹炰範", "灞呭鍔炲叕"]
        SALARY    = ["涓嶉檺", "3K浠ヤ笅", "3-5K", "5-10K", "10-20K", "20-50K", "50K浠ヤ笂"]
        EXPERIENCE= ["Student", "New grad", "<1 year", "1-3 years", "3-5 years", "5-10 years", "10+ years"]
        DEGREE    = ["澶т笓", "鏈", "纭曞＋", "鍗氬＋"]
        SCALE     = ["0-20", "20-99", "100-499", "500-999", "1000-9999", "10000+"]

        q_style = Style([
            ("qmark",        "fg:#00bfff bold"),
            ("question",     "bold"),
            ("answer",       "fg:#00ff99 bold"),
            ("pointer",      "fg:#00bfff bold"),
            ("highlighted",  "fg:#00bfff bold"),
            ("selected",     "fg:#00ff99"),
            ("instruction",  "fg:#888888"),
        ])

        existing = {}
        if Path(self.profile_path).exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except Exception:
                pass

        print("\n" + "="*52)
        print("   姹傝亴鍋忓ソ閰嶇疆  锛堝搴?Boss鐩磋仒 鎼滅储鏍忥級")
        print("="*52)
        print("  鈫戔啌 绉诲姩   绌烘牸 閫夋嫨/鍙栨秷   Enter 纭   鎵€鏈夐」鍧囧彲鐣欑┖\n")

        # 鈹€鈹€ 1. 鎼滅储鍏抽敭璇嶏紙鍙暀绌猴級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        existing_kw = ",".join(existing.get("keywords") or [])
        raw = questionary.text(
            "Search keywords (blank = no limit, separate multiple values with comma):",
            default=existing_kw,
            instruction="渚嬶細Python鍚庣宸ョ▼甯堛€佹暟鎹伐绋嬪笀",
            style=q_style,
        ).ask()
        if raw is None:
            print("Cancelled.")
            return
        keywords = [k.strip() for k in re.split(r"[,锛屻€乚", raw) if k.strip()]

        # 鈹€鈹€ 2. 鐩爣鍩庡競锛堝彲涓嶉€夛級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        cities = questionary.checkbox(
            "Target cities (none selected = no limit):",
            choices=[
                questionary.Choice(c, checked=(c in (existing.get("cities") or [])))
                for c in CITIES
            ],
            instruction="鈫戔啌绉诲姩  绌烘牸閫夋嫨  Enter纭",
            style=q_style,
        ).ask()
        if cities is None:
            print("Cancelled.")
            return
        cities = [c for c in cities if c != "鍏朵粬"]

        # 鈹€鈹€ 鈼?3. 姹傝亴绫诲瀷锛堝崟閫夛級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        job_type = questionary.select(
            "鈼?姹傝亴绫诲瀷",
            choices=JOB_TYPES,
            default=existing.get("job_type") or "鍏ㄨ亴",
            instruction="鈫戔啌绉诲姩  Enter纭",
            style=q_style,
        ).ask()
        if job_type is None:
            job_type = existing.get("job_type") or "鍏ㄨ亴"

        # 鈹€鈹€ 鈼?4. 钖祫寰呴亣锛堝崟閫夛級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        salary_val = questionary.select(
            "鈼?钖祫寰呴亣",
            choices=SALARY,
            default=existing.get("salary") or "涓嶉檺",
            instruction="鈫戔啌绉诲姩  Enter纭",
            style=q_style,
        ).ask()
        if salary_val is None:
            salary_val = existing.get("salary") or ""
        salary = "" if salary_val == "涓嶉檺" else salary_val

        # 鈹€鈹€ 鈼?5. 宸ヤ綔缁忛獙锛堝閫夛級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        experience = questionary.checkbox(
            "Work experience (none selected = no limit):",
            choices=[
                questionary.Choice(e, checked=(e in (existing.get("experience") or [])))
                for e in EXPERIENCE
            ],
            instruction="鈫戔啌绉诲姩  绌烘牸閫夋嫨  Enter纭",
            style=q_style,
        ).ask()
        if experience is None:
            experience = existing.get("experience") or []

        # 鈹€鈹€ 鈼?6. 瀛﹀巻瑕佹眰锛堝閫夛級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        degree = questionary.checkbox(
            "Degree requirement (none selected = no limit):",
            choices=[
                questionary.Choice(d, checked=(d in (existing.get("degree") or [])))
                for d in DEGREE
            ],
            instruction="鈫戔啌绉诲姩  绌烘牸閫夋嫨  Enter纭",
            style=q_style,
        ).ask()
        if degree is None:
            degree = existing.get("degree") or []

        # 鈹€鈹€ 鈼?7. 鍏徃瑙勬ā锛堝彲閫夛紝鍏堣闂級鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        scale = existing.get("scale") or []
        want_scale = questionary.confirm(
            "鏄惁閰嶇疆鍏徃瑙勬ā绛涢€夛紵",
            default=bool(scale),
            style=q_style,
        ).ask()
        if want_scale:
            scale = questionary.checkbox(
                "Company size (none selected = no limit):",
                choices=[
                    questionary.Choice(s, checked=(s in scale))
                    for s in SCALE
                ],
                instruction="鈫戔啌绉诲姩  绌烘牸閫夋嫨  Enter纭",
                style=q_style,
            ).ask() or scale

        # 鈹€鈹€ 鈼?8. 浠呮樉绀?Boss 鏈€杩戞椿璺冣攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        existing_boss_online = existing.get("boss_online", False)
        boss_online = questionary.confirm(
            "Only show recently active Boss posts?",
            default=existing_boss_online,
            instruction="寮€鍚悗鎼滅储缁撴灉浼氳繃婊ゆ帀闀挎湡鏈椿璺冪殑 HR锛堟帹鑽愬紑鍚級",
            style=q_style,
        ).ask()
        if boss_online is None:
            boss_online = existing_boss_online

        # 鈹€鈹€ 鈼?9. 璇勫垎闃堝€尖攢鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
        existing_threshold = existing.get("score_threshold", 60)
        threshold_raw = questionary.text(
            "Score threshold (0-100, skip jobs below this):",
            default=str(existing_threshold),
            instruction="Recommended: 55-70. Lower means more applications.",
            style=q_style,
        ).ask()
        try:
            score_threshold = max(0, min(100, int(threshold_raw.strip())))
        except (ValueError, AttributeError):
            score_threshold = existing_threshold

        profile = {
            "keywords": keywords,
            "cities": cities,
            "job_type": job_type,
            "salary": salary,
            "experience": experience,
            "degree": degree,
            "scale": scale,
            "boss_online": boss_online,
            "score_threshold": score_threshold,
        }
        Path(self.profile_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            yaml.dump(profile, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        print("\n" + "="*52)
        print("  Configuration saved.")
        print("="*52)
        print("  Keywords: " + " / ".join(keywords))
        print("  Cities: " + " / ".join(cities))
        print("  Job Type: " + (job_type or "full-time"))
        print("  Salary: " + (salary or "no limit"))
        print("  Experience: " + (" / ".join(experience) if experience else "no limit"))
        print("  Degree: " + (" / ".join(degree) if degree else "no limit"))
        print("  Company Scale: " + (" / ".join(scale) if scale else "no limit"))
        print("  Boss Active: " + ("active only" if boss_online else "no limit"))
        print("  Tip: Greeting message can be configured in Boss app settings.")
        print(f"  Score Threshold: {score_threshold}")
        print("\nNext: run `python main.py --dry-run` to validate the flow.")

    def _step5_scan_history(self) -> None:
        """Step 5: 鎵弿鍘嗗彶浼氳瘽锛屾爣璁板凡鍙戠畝鍘嗙殑瀵硅瘽妗?stage=resume_sent銆?
        瀵规柊鐢ㄦ埛绗竴娆¤繍琛屾椂锛孌B 涓虹┖锛屾墍鏈変細璇濋兘浼氳璇诲彇銆?        瀵归噸鏂?onboarding 鐨勭敤鎴凤紝涔熶細鍏ㄩ噺閲嶆壂锛岀‘淇濇爣璁板噯纭€?        """
        # Retired: history scan used the legacy BrowserAgent. Pending onboarding
        # rewrite as a workflow; trigger W2 (check responses) from the Dashboard instead.
        raise RuntimeError(
            "CLI onboarding 历史扫描已退役：请用 Dashboard 触发 W2（检查回应）"
            "（onboarding 待重写为 workflow）。"
        )
        from services.tracker import ApplicationTracker

        do_scan = self._prompt_yes_no(
            "\n鏄惁鎵弿鏈€杩?N 鏉?Boss鐩磋仒 浼氳瘽锛屾爣璁板凡鍙戦€佽繃绠€鍘嗙殑瀵硅瘽妗嗭紵(y/n) [default: y]: ",
            default=True,
        )
        if not do_scan:
            print("Skipped history scan. You can run `python main.py --check` later.")
            return

        raw = input("鎵弿鏈€杩戝灏戞潯浼氳瘽锛焄default: 30]: ").strip()
        try:
            n = max(1, min(200, int(raw))) if raw else 30
        except ValueError:
            n = 30
        print(f"Scanning latest {n} conversations, please wait (about 5s interval per item)...")

        tracker = ApplicationTracker(db_path="data/jobs.db")
        try:
            with BrowserAgent(session_path=self.session_path) as agent:
                scan = agent.scan_chat_list(max_count=n, force_all=True)
                print(f"Found {scan.total_convs} conversations, will sync {len(scan.needs_sync)}.")

                synced = agent.sync_conversations(scan.needs_sync, tracker)

                marked = 0
                for conv in synced:
                    if BrowserAgent._has_sent_resume(conv.messages) and conv.stage != "resume_sent":
                        conv.stage = "resume_sent"
                        tracker.upsert_hr_conversation(conv)
                        marked += 1
                        print(f"  [宸插彂绠€鍘哴 {conv.company} / {conv.hr_name}")

                print(f"\nHistory scan completed: synced {len(synced)}, marked resume_sent {marked}.")
        except Exception as exc:
            print(f"History scan failed: {exc}")
            print("You can run `python main.py --check` later to trigger manually.")
        finally:
            tracker.close()

    def _session_is_valid(self) -> bool:
        # Session validity is now checked via the Dashboard (BrowserSession +
        # VerifySessionStep). CLI onboarding is pending a workflow rewrite, so this
        # always reports "not valid" and defers login to the Dashboard.
        return False

    def _try_configure_claude_cli(self) -> Optional[dict]:
        if not self._command_available(["claude", "--version"]):
            print("claude CLI not available, skipping.")
            return None
        print("Detected claude CLI.")
        if self._prompt_yes_no("Use claude CLI as the LLM provider? (y/n): ", default=True):
            return {"type": "claude_cli"}
        return None

    def _try_configure_codex_cli(self) -> Optional[dict]:
        if not self._command_available(["codex", "--version"]):
            print("codex CLI not available, skipping.")
            return None
        print("Detected codex CLI.")
        if self._prompt_yes_no("Use codex CLI as the LLM provider? (y/n): ", default=True):
            return {"type": "codex_cli"}
        return None

    def _try_configure_anthropic_api(self) -> Optional[dict]:
        api_key = getpass.getpass("Enter Anthropic API Key (leave blank to skip): ").strip()
        if not api_key:
            print("Anthropic API Key skipped.")
            return None

        if not self._validate_anthropic_key(api_key):
            print("Anthropic API Key validation failed.")
            return None

        os.environ["ANTHROPIC_API_KEY"] = api_key
        print("Anthropic API Key is valid. Export ANTHROPIC_API_KEY in your shell to persist it.")
        return {
            "type": "anthropic_api",
            "model": "claude-sonnet-4-6",
            "api_key_env": "ANTHROPIC_API_KEY",
        }

    def _try_configure_openai_compatible(self) -> Optional[dict]:
        base_url = input("Enter OpenAI-compatible base_url (leave blank to skip): ").strip()
        if not base_url:
            print("OpenAI-compatible API skipped.")
            return None

        api_key = getpass.getpass("Enter OpenAI-compatible API Key: ").strip()
        model = input("Enter model name [default: gpt-4o-mini]: ").strip() or "gpt-4o-mini"

        if not self._validate_openai_compatible(base_url, api_key, model):
            print("OpenAI-compatible API validation failed.")
            return None

        os.environ["OPENAI_API_KEY"] = api_key
        print("OpenAI-compatible API is valid. Export OPENAI_API_KEY in your shell to persist it.")
        return {
            "type": "openai_compatible",
            "model": model,
            "base_url": base_url.rstrip("/"),
            "api_key_env": "OPENAI_API_KEY",
        }

    def _try_configure_ollama(self) -> Optional[dict]:
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            print(f"Ollama not available, skipping. ({exc})")
            return None

        models = [item.get("name", "").strip() for item in data.get("models", []) if item.get("name")]
        if not models:
            print("Ollama is reachable but no models are installed.")
            return None

        print("Available Ollama models:")
        for index, model in enumerate(models, start=1):
            print(f"  {index}. {model}")

        while True:
            choice = input("Choose an Ollama model by number: ").strip()
            if choice.isdigit():
                selected_index = int(choice)
                if 1 <= selected_index <= len(models):
                    return {
                        "type": "ollama",
                        "model": models[selected_index - 1],
                        "base_url": "http://localhost:11434",
                    }
            print("Invalid selection. Please enter a valid number.")

    def _command_available(self, command: list[str]) -> bool:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _validate_anthropic_key(self, api_key: str) -> bool:
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "ping"}],
        }
        try:
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=20,
            )
            return response.status_code == 200
        except Exception as exc:
            print(f"Anthropic validation request failed: {exc}")
            return False

    def _validate_openai_compatible(self, base_url: str, api_key: str, model: str) -> bool:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
        }
        try:
            response = requests.post(
                f"{base_url.rstrip('/')}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=20,
            )
            return response.status_code == 200
        except Exception as exc:
            print(f"OpenAI-compatible validation request failed: {exc}")
            return False

    def _write_config(self) -> None:
        from services.config_manager import get_config_manager, ConfigManager

        # Ensure a fresh instance tied to this config_path is used.
        # _step2_configure_llm only touches the llm.providers sub-key; we write it
        # via the general dict merge below rather than save_system_config (which
        # blocks the "llm" section) because onboarding is the one authorised writer
        # for LLM provider configuration.
        config_dir = os.path.dirname(self.config_path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)

        on_disk: dict = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    on_disk = yaml.safe_load(f) or {}
            except Exception:
                pass

        # Merge: self.config wins for keys it contains, on_disk fills the rest
        merged = {**on_disk, **self.config}
        # Deep-merge llm section specifically so we don't lose other llm keys
        if "llm" in on_disk and "llm" in self.config:
            merged["llm"] = {**on_disk["llm"], **self.config["llm"]}

        with open(self.config_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(merged, file, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # Invalidate the module-level ConfigManager singleton so next access re-reads disk.
        import services.config_manager as _cm_mod
        _cm_mod._instance = None

    def _prompt_yes_no(self, prompt: str, default: bool) -> bool:
        suffix = "y" if default else "n"
        raw = input(prompt).strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print(f"Invalid input, defaulting to '{suffix}'.")
        return default

    def _create_default_profile(
        self, keywords: list, cities: list, salary: str, skills: str, years: str
    ) -> None:
        profile_dir = os.path.dirname(self.profile_path) or "data"
        os.makedirs(profile_dir, exist_ok=True)

        years_value: Any = years
        if isinstance(years, str) and years.isdigit():
            years_value = int(years)

        profile = {
            "keywords": keywords or ["Python Backend Engineer"],
            "cities": cities or ["Beijing"],
            "expected_salary": salary or "20-35k",
            "skills": skills or "Python, FastAPI, PostgreSQL, Redis",
            "years_experience": years_value,
            "notes": "",
        }
        with open(self.profile_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(profile, file, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"Profile saved to {self.profile_path}")

