"""翻译引擎模块.

支持 CSV 术语表精确匹配 + 通用翻译 API 回退。
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("cad_translator")

# ---- 数据模型 ----


@dataclass
class TranslationResult:
    """翻译结果."""

    original: str
    translated: str
    source: str  # "term_table", "api", "untranslated"
    success: bool = True


# ---- 术语表引擎 ----


class TermTable:
    """CSV 术语表，支持最长匹配优先."""

    def __init__(self, filepath: str | os.PathLike):
        self.filepath = str(filepath)
        self._pairs: list[tuple[str, str]] = []
        self._load()

    def _load(self) -> None:
        """从 CSV 文件加载术语表."""
        with open(self.filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                cn = row[0].strip()
                en = row[1].strip()
                if cn and en and cn != en:
                    self._pairs.append((cn, en))

        # 按长度降序排序（最长匹配优先）
        self._pairs.sort(key=lambda x: len(x[0]), reverse=True)

        logger.info(
            f"加载术语表: {self.filepath} ({len(self._pairs)} 条)"
        )

    @property
    def count(self) -> int:
        return len(self._pairs)

    def translate(self, text: str) -> Optional[str]:
        """对单段文本应用术语表替换.

        返回替换后的文本；如果没有命中任何术语则返回 None.
        """
        result = text
        matched = False
        for cn, en in self._pairs:
            if cn in result:
                result = result.replace(cn, en)
                matched = True
        return result if matched else None

    def translate_batch(
        self, texts: list[str]
    ) -> dict[str, TranslationResult]:
        """批量翻译."""
        results: dict[str, TranslationResult] = {}
        for text in texts:
            translated = self.translate(text)
            if translated is not None:
                results[text] = TranslationResult(
                    original=text,
                    translated=translated,
                    source="term_table",
                )
        return results


# ---- 翻译 API 基类 ----


class BaseTranslatorAPI:
    """翻译 API 基类."""

    name = "base"

    def translate(self, text: str, max_retries: int = 3) -> Optional[str]:
        """翻译单段文本."""
        raise NotImplementedError

    def translate_batch(
        self, texts: list[str], max_workers: int = 4
    ) -> dict[str, TranslationResult]:
        """批量翻译."""
        results: dict[str, TranslationResult] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._translate_with_retry, text): text
                for text in texts
            }
            for future in as_completed(future_map):
                text = future_map[future]
                try:
                    translated = future.result()
                    results[text] = TranslationResult(
                        original=text,
                        translated=translated,
                        source=self.name,
                        success=translated is not None,
                    )
                except Exception as e:
                    logger.error(f"翻译失败 [{text[:30]}...]: {e}")
                    results[text] = TranslationResult(
                        original=text,
                        translated=text,  # 保留原文
                        source="untranslated",
                        success=False,
                    )
        return results

    def _translate_with_retry(
        self, text: str, max_retries: int = 3
    ) -> Optional[str]:
        """带重试的翻译."""
        for attempt in range(max_retries):
            try:
                result = self.translate(text)
                if result is not None:
                    return result
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"翻译重试 ({attempt + 1}/{max_retries}): {e}"
                    )
                    time.sleep(wait)
                else:
                    raise
        return None


# ---- 百度翻译 API ----


class BaiduTranslator(BaseTranslatorAPI):
    """百度通用翻译 API.

    免费版每月 5 万字符额度。
    需在 https://fanyi-api.baidu.com/ 注册获取 appid 和 key.
    """

    name = "baidu"

    def __init__(self, appid: str, secret_key: str):
        self.appid = appid
        self.secret_key = secret_key
        self._api_url = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    def translate(self, text: str, max_retries: int = 3) -> Optional[str]:
        """调用百度翻译 API."""

        import hashlib
        import random

        def _make_md5(s: str) -> str:
            return hashlib.md5(s.encode("utf-8")).hexdigest()

        salt = str(random.randint(10000, 99999))
        sign = _make_md5(self.appid + text + salt + self.secret_key)

        params = {
            "q": text,
            "from": "zh",
            "to": "en",
            "appid": self.appid,
            "salt": salt,
            "sign": sign,
        }
        url = self._api_url + "?" + urllib.parse.urlencode(params)

        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                if "trans_result" in data:
                    translated = "\n".join(
                        item["dst"] for item in data["trans_result"]
                    )
                    return translated
                else:
                    error_msg = data.get("error_msg", "未知错误")
                    logger.warning(
                        f"百度翻译 API 错误: {error_msg}"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    else:
                        return None

            except Exception as e:
                logger.warning(
                    f"百度翻译 API 请求失败 ({attempt+1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return None

        return None


# ---- 硅基流动 LLM 翻译（OpenAI 兼容接口） ----


class SiliconFlowTranslator(BaseTranslatorAPI):
    """硅基流动 LLM 翻译，OpenAI 兼容接口.

    文档：https://docs.siliconflow.cn/cn/api-reference/chat-completions/chat-completions
    模型参考：https://cloud.siliconflow.cn/models
    """

    name = "siliconflow"

    def __init__(
        self,
        api_key: str,
        model: str = "Qwen/Qwen3.5-9B",
        base_url: str = "https://api.siliconflow.cn/v1",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens

    def translate(self, text: str, max_retries: int = 3) -> Optional[str]:
        """调用 SiliconFlow Chat Completions API 翻译."""
        system_prompt = (
            "You are a professional engineering translator. "
            "Translate the following Chinese text to English. "
            "Keep technical terms accurate and natural. "
            "Only output the translation, do not include any explanation or notes."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        url = f"{self.base_url}/chat/completions"
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    url,
                    data=data_bytes,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode("utf-8"))

                if "choices" in body and body["choices"]:
                    content = body["choices"][0].get("message", {}).get("content", "")
                    if content:
                        return content.strip()

                logger.warning(
                    f"SiliconFlow API 返回异常: {json.dumps(body, ensure_ascii=False)[:200]}"
                )
                return None

            except urllib.error.HTTPError as e:
                try:
                    err_body = e.read().decode("utf-8")
                    err_detail = json.loads(err_body)
                    err_msg = err_detail.get("error", {}).get("message", err_body)
                except Exception:
                    err_msg = str(e)

                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"SiliconFlow API HTTP {e.code} ({attempt+1}/{max_retries}): "
                        f"{err_msg}，等待 {wait}s 重试"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"SiliconFlow API HTTP {e.code} 已达最大重试次数: {err_msg}"
                    )
                    return None

            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"SiliconFlow 请求异常 ({attempt+1}/{max_retries}): {e}，"
                        f"等待 {wait}s 重试"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"SiliconFlow 请求异常已达最大重试次数: {e}"
                    )
                    return None

        return None


# ---- 空翻译（仅术语表，无 API） ----


class NullTranslator(BaseTranslatorAPI):
    """空翻译器，仅返回原文（当不使用 API 时）."""

    name = "null"

    def translate(self, text: str, max_retries: int = 3) -> Optional[str]:
        return text


# ---- 组合翻译引擎 ----


class TranslatorEngine:
    """组合翻译引擎：先术语表，再 API 回退."""

    def __init__(
        self,
        term_table: Optional[TermTable] = None,
        api: Optional[BaseTranslatorAPI] = None,
    ):
        self._term_table = term_table
        self._api = api
        self._stats = {
            "term_hits": 0,
            "api_calls": 0,
            "untranslated": 0,
            "total": 0,
        }

    @classmethod
    def from_config(
        cls,
        term_file: Optional[str] = None,
        api_type: str = "null",
        baidu_appid: str = "",
        baidu_secret: str = "",
        siliconflow_api_key: str = "",
        siliconflow_model: str = "Qwen/Qwen3.5-9B",
    ) -> "TranslatorEngine":
        """从配置创建翻译引擎.

        Args:
            term_file: CSV 术语表路径.
            api_type: API 类型 ("null", "baidu", "siliconflow").
            baidu_appid: 百度翻译 appid.
            baidu_secret: 百度翻译 secret key.
            siliconflow_api_key: 硅基流动 API key.
            siliconflow_model: 硅基流动模型名.
        """
        term_table = TermTable(term_file) if term_file else None

        if api_type == "baidu" and baidu_appid and baidu_secret:
            api = BaiduTranslator(baidu_appid, baidu_secret)
        elif api_type == "siliconflow" and siliconflow_api_key:
            api = SiliconFlowTranslator(
                api_key=siliconflow_api_key,
                model=siliconflow_model,
            )
        else:
            api = NullTranslator()

        return cls(term_table=term_table, api=api)

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def translate_text(self, text: str) -> TranslationResult:
        """翻译单段文本."""
        self._stats["total"] += 1

        # 1. 先尝试术语表
        if self._term_table is not None:
            result = self._term_table.translate(text)
            if result is not None:
                self._stats["term_hits"] += 1
                return TranslationResult(
                    original=text,
                    translated=result,
                    source="term_table",
                )

        # 2. API 回退
        if self._api is not None:
            self._stats["api_calls"] += 1
            result = self._api.translate(text)
            if result:
                return TranslationResult(
                    original=text,
                    translated=result,
                    source=self._api.name,
                )

        # 3. 翻译失败
        self._stats["untranslated"] += 1
        return TranslationResult(
            original=text,
            translated=text,
            source="untranslated",
            success=False,
        )

    def translate_batch(
        self, texts: list[str], max_workers: int = 4
    ) -> dict[str, TranslationResult]:
        """批量翻译."""
        results: dict[str, TranslationResult] = {}

        # 先用术语表处理所有文本
        for text in texts:
            result = self.translate_text(text)
            results[text] = result

        return results
