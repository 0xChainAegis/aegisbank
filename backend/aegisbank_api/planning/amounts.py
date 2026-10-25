"""Bounded CNY normalization with whole-token validation and original-text spans.

No financial arithmetic uses binary floats here. Conversion to float occurs only
at the existing tool-schema boundary. Unsupported notation must not yield a
numeric substring (e.g. 1,500 -> 500 or 1.5万 -> 1.5).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

_NUMERALS = "零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億"
_TOKEN = re.compile(
    rf"[+＋\-－负]?[0-9０-９{_NUMERALS}]"
    rf"[0-9０-９{_NUMERALS}.,，．点eE+＋\-－_/／:：]*"
)
_SUFFIX = re.compile(r"\s*(元|块(?:钱)?|人民币|rmb\b|cny\b|美元|美金|港币|欧元|usd\b)", re.I)
_PREFIX = re.compile(
    r"(?:人民币|rmb|cny|[¥￥$€]|转账|汇款|打款|转|预算|aa|总共|总计|合计|一共|"
    r"金额(?:为|是)?|transfer|send|budget|到|至|为|改成)\s*$",
    re.I,
)
_FOREIGN = re.compile(r"美元|美金|港币|欧元|英镑|日元|\b(?:usd|eur|hkd|jpy|gbp)\b|[$€£]", re.I)
_DIGITS = dict(zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9), strict=True))
_FORMAL = str.maketrans("壹贰叁肆伍陆柒捌玖拾佰仟萬億", "一二三四五六七八九十百千万亿")
_UNITS = {"十": 10, "百": 100, "千": 1000}


class AmountError(ValueError):
    """A monetary expression needs clarification, not partial extraction."""


@dataclass(frozen=True)
class MoneyMention:
    raw: str
    start: int
    end: int
    value: Decimal


def _chinese_integer(text: str) -> int:
    if not text:
        raise AmountError("中文金额不完整")
    if all(char in _DIGITS for char in text):
        # Positional Chinese digits are supported; 两 is only a unit multiplier.
        if "两" in text and len(text) > 1:
            raise AmountError("中文金额存在歧义")
        return int("".join(str(_DIGITS[char]) for char in text))
    for big, scale in (("亿", 100_000_000), ("万", 10_000)):
        if big in text:
            if text.count(big) != 1:
                raise AmountError("中文金额单位重复")
            left, right = text.split(big)
            high = _chinese_integer(left)
            low = _chinese_integer(right.lstrip("零〇")) if right.lstrip("零〇") else 0
            if high >= scale or low >= scale:
                raise AmountError("中文金额单位顺序不明确")
            if (
                right
                and right[-1] in _DIGITS
                and len(right.lstrip("零〇")) == 1
                and right[0] not in "零〇"
            ):
                raise AmountError("请将一万五等省略金额写完整")
            return high * scale + low
    total, digit, previous, zero = 0, None, 10_000, False
    for char in text:
        if char in _DIGITS:
            value = _DIGITS[char]
            if value == 0:
                if digit is not None or zero:
                    raise AmountError("中文金额数字顺序不明确")
                zero = True
            else:
                if digit is not None:
                    raise AmountError("中文金额数字顺序不明确")
                digit = value
        elif char in _UNITS:
            unit = _UNITS[char]
            if unit >= previous or (digit is None and not (unit == 10 and total == 0 and not zero)):
                raise AmountError("中文金额单位顺序不明确")
            total += (digit if digit is not None else 1) * unit
            previous, digit, zero = unit, None, False
        else:
            raise AmountError("不支持的中文金额格式")
    if digit is not None:
        if previous > 10 and not zero:
            raise AmountError("请将一百五等省略金额写完整")
        total += digit
    elif zero:
        raise AmountError("中文金额末尾不完整")
    return total


def parse_amount(raw: str) -> Decimal:
    # Token length is capped at 40; retain every digit before checking cents.
    with localcontext() as context:
        context.prec = 64
        text = unicodedata.normalize("NFKC", raw).translate(_FORMAL)
        if len(text) > 40:
            raise AmountError("金额过长")
        if re.fullmatch(r"(?:[0-9]+|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]+)?[千万亿]?", text):
            scale = {"千": 1000, "万": 10_000, "亿": 100_000_000}.get(text[-1], 1)
            number = text[:-1] if text[-1] in "千万亿" else text
            value = Decimal(number.replace(",", "")) * scale
        elif re.fullmatch(rf"[{_NUMERALS}]+(?:点[零〇一二三四五六七八九]+)?", text):
            integer, _, fraction = text.partition("点")
            value = Decimal(_chinese_integer(integer))
            if fraction:
                value += Decimal("0." + "".join(str(_DIGITS[c]) for c in fraction))
        else:
            raise AmountError("金额格式不支持，请使用完整人民币金额（例如 1,500.00 元）")
        try:
            if (
                value <= 0
                or value > Decimal("1000000000")
                or value != value.quantize(Decimal("0.01"))
            ):
                raise AmountError("金额必须为正数、精确到分，且不超过支持范围")
        except InvalidOperation as exc:
            raise AmountError("金额超出支持范围") from exc
        return value


def money_mentions(instruction: str) -> list[MoneyMention]:
    mentions = []
    for match in _TOKEN.finditer(instruction):
        before, after = instruction[: match.start()], instruction[match.end() :]
        suffix = _SUFFIX.match(after)
        prefix = _PREFIX.search(before)
        if not suffix and not prefix:
            continue
        # A continuation token is never a safe monetary substring.
        if re.search(r"(?:[\d][\s_/:：]+|[.,，．]\s*)$", before) or re.match(
            r"\s+[\d０-９]", after
        ):
            raise AmountError("金额含不明确的分隔符，请使用 1,500.00 元这样的完整格式")
        if re.search(
            r"大概|大约|差不多|左右|上下|至少|最多|最少|不超过|不到|约\s*$", before
        ) or re.match(r"(?:元|块)?(?:左右|上下|多|余|来|几)", after):
            raise AmountError("金额带有范围或约数，请明确精确金额")
        if _FOREIGN.search(unicodedata.normalize("NFKC", instruction)):
            raise AmountError("当前仅支持人民币金额，请明确币种与人民币金额")
        # Counters describe number of operations/dates, not monetary values.
        if not suffix and re.match(r"(?:笔|个|张|人|次|年|月|日|号)", after):
            continue
        # Avoid treating an amount prefix as the beginning of an account/date.
        if not suffix and not re.match(
            r"\s*(?:$|[,，。；;!?！？]|给|到|向|用于|备注|补充信息)", after
        ):
            raise AmountError("金额单位或格式不支持，请提供明确的人民币金额")
        if suffix and re.match(r"[0-9０-９零一二三四五六七八九角分]", after[suffix.end() :]):
            raise AmountError("请将角分写成小数金额，例如 500.50 元")
        mentions.append(
            MoneyMention(match.group(), match.start(), match.end(), parse_amount(match.group()))
        )
    return mentions


def extract_amounts(instruction: str) -> list[float]:
    return [float(mention.value) for mention in money_mentions(instruction)]
