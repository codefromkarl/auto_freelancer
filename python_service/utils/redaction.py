"""
敏感信息脱敏工具。

说明：
- 仅依赖正则表达式进行匹配，并将匹配内容替换为统一占位符 `<REDACTED>`
- 支持脱敏：邮箱、电话、URL、信用卡号
"""

from __future__ import annotations

import re
from typing import Any


# 统一脱敏占位符（用于替换敏感信息）
REDACTION_TOKEN = "<REDACTED>"

# 邮箱匹配（覆盖常见邮箱格式）
_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")

# URL 匹配（http/https）
# 说明：先用较宽松的规则匹配，再在替换函数中剔除结尾常见标点，避免“吞掉”句子符号
_URL_RE = re.compile(r"\bhttps?://\S+")

# 可能的信用卡号（13-19 位数字，允许空格/连字符分隔）
_CREDIT_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")

# 可能的电话号码（允许 +、括号、空格、连字符等分隔符）
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")


def _luhn_check(number: str) -> bool:
    """使用 Luhn 算法校验信用卡号，降低误伤概率。"""
    digits = [int(c) for c in number if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def desensitize_text(text: str) -> str:
    """
    对字符串进行脱敏处理。

    规则：
    - 邮箱、URL：直接替换为 `<REDACTED>`
    - 信用卡号：先用正则候选匹配，再用 Luhn 校验通过才替换（避免误匹配普通数字）
    - 电话：候选匹配后按数字位数（8-15）判断是否替换
    """
    if not text:
        return text

    # 1) 邮箱
    text = _EMAIL_RE.sub(REDACTION_TOKEN, text)

    # 2) URL（保留句末标点）
    def _url_repl(match: re.Match[str]) -> str:
        url = match.group(0)
        # 常见句末标点不应被吞掉（例如 "https://a.com)."）
        trailing = ""
        while url and url[-1] in ".,;:!?)]}\"'":
            trailing = url[-1] + trailing
            url = url[:-1]
        if not url:
            return match.group(0)
        return f"{REDACTION_TOKEN}{trailing}"

    text = _URL_RE.sub(_url_repl, text)

    # 3) 信用卡号（候选 + Luhn）
    def _cc_repl(match: re.Match[str]) -> str:
        candidate = match.group(0)
        digits_only = "".join(c for c in candidate if c.isdigit())
        return REDACTION_TOKEN if _luhn_check(digits_only) else candidate

    text = _CREDIT_CARD_CANDIDATE_RE.sub(_cc_repl, text)

    # 4) 电话（候选 + 位数判断）
    def _phone_repl(match: re.Match[str]) -> str:
        candidate = match.group(0)
        digits_only = "".join(c for c in candidate if c.isdigit())
        # 常见电话长度范围：8-15 位（兼容国际区号）
        if 8 <= len(digits_only) <= 15:
            return REDACTION_TOKEN
        return candidate

    text = _PHONE_CANDIDATE_RE.sub(_phone_repl, text)
    return text


def desensitize_obj(obj: Any) -> Any:
    """
    对任意 JSON-like 对象进行递归脱敏：
    - str：调用 desensitize_text
    - dict/list/tuple：递归处理子元素
    - 其他类型：原样返回
    """
    if isinstance(obj, str):
        return desensitize_text(obj)
    if isinstance(obj, dict):
        return {k: desensitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [desensitize_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(desensitize_obj(v) for v in obj)
    return obj
