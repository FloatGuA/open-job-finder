import logging
import os

_loggers: dict = {}


def _make_logger(name: str, file_path: str) -> logging.Logger:
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if logger.handlers:
        _loggers[name] = logger
        return logger

    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(file_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    _loggers[name] = logger
    return logger


def get_job_logger(job_id: str) -> logging.Logger:
    log_dir = os.path.join("logs", "jobs")
    os.makedirs(log_dir, exist_ok=True)
    file_path = os.path.join(log_dir, f"{job_id}.log")
    return _make_logger(f"job.{job_id}", file_path)


def get_orchestrator_logger() -> logging.Logger:
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    file_path = os.path.join(log_dir, "orchestrator.log")
    return _make_logger("orchestrator", file_path)
