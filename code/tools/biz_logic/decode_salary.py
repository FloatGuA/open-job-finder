from tools.base import BaseTool, ToolResult


def decode_boss_numbers(text: str) -> str:
    # Boss Zhipin encodes salary digits in PUA range - (=0, =1, ..., =9)
    result = []
    for ch in text:
        cp = ord(ch)
        if 0xe031 <= cp <= 0xe03a:
            result.append(str((cp - 0xe031) % 10))
        else:
            result.append(ch)
    return "".join(result)


class DecodeJobSalary(BaseTool):
    name = "decode_job_salary"
    description = "Decode Boss Zhipin PUA-encoded salary strings to human-readable text."
    input_schema = {
        "type": "object",
        "properties": {
            "raw_salary": {"type": "string"},
        },
        "required": ["raw_salary"],
    }

    def execute(self, *, raw_salary: str) -> ToolResult:
        return ToolResult(ok=True, data={"decoded_salary": decode_boss_numbers(raw_salary)})
