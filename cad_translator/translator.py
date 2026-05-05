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

from .extractor import contains_chinese

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
                # 跳过标题行
                if cn in ("中文", "Chinese", "原文", "") or en in ("英文", "English", "译文", ""):
                    continue
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

        # 短文本预处理：为 LLM 提供上下文，提高翻译准确性
        user_text = text
        if len(text) <= 4 and contains_chinese(text):
            user_text = f"在工程图纸中，将以下文字翻译为英文: {text}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
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
                        result = content.strip()
                        # 如果 API 返回了原文（未翻译），视为失败触发重试
                        if result == text.strip():
                            logger.warning(
                                f"API 返回原文未翻译: '{text[:40]}'"
                            )
                            if attempt < max_retries - 1:
                                wait = 2 ** attempt
                                time.sleep(wait)
                                continue
                            return None
                        return result

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


# ---- 百度云翻译 API（MT，aip.baidubce.com） ----


class BaiduCloudTranslator(BaseTranslatorAPI):
    """百度云翻译 MT API (aip.baidubce.com).

    使用 OAuth2 access_token 认证，单次请求最大 6000 字符。
    文档：https://ai.baidu.com/ai-doc/MT/4kqryjku9
    控制台：https://console.bce.baidu.com/ai/#/ai/machinetranslation/overview
    """

    name = "baidu_cloud"

    def __init__(self, api_key: str, secret_key: str, app_id: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self.app_id = app_id
        self._token_url = "https://aip.baidubce.com/oauth/2.0/token"
        self._api_url = "https://aip.baidubce.com/rpc/2.0/mt/texttrans/v1"
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0
        self._token_failed: bool = False

    def _get_access_token(self) -> Optional[str]:
        """获取 OAuth2 access_token，带缓存."""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
        if self._token_failed:
            return None

        params = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        })
        url = f"{self._token_url}?{params}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if "access_token" in data:
                self._access_token = data["access_token"]
                expires_in = data.get("expires_in", 2592000)
                self._token_expiry = time.time() + expires_in - 300  # 提前 5 分钟
                logger.info("百度云 access_token 获取成功")
                return self._access_token
            else:
                error_desc = data.get("error_description",
                                       data.get("error", "未知错误"))
                logger.error(f"百度云 token 获取失败: {error_desc}")
                self._token_failed = True
                return None
        except Exception as e:
            logger.error(f"百度云 token 请求异常: {e}")
            self._token_failed = True
            return None

    def _translate_segment(
        self, text: str, token: str, max_retries: int
    ) -> Optional[str]:
        """翻译单段文本（<=6000 字符）。"""
        payload = {"q": text, "from": "zh", "to": "en"}
        url = f"{self._api_url}?access_token={token}"
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    url,
                    data=data_bytes,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode("utf-8"))

                if "result" in body and "trans_result" in body["result"]:
                    parts = [item["dst"] for item in body["result"]["trans_result"]]
                    return "\n".join(parts)

                error_code = body.get("error_code", "")
                error_msg = body.get("error_msg", "未知错误")
                # token 过期，尝试刷新
                if error_code in ("110", "111"):
                    logger.warning("百度云 token 过期，重新获取")
                    self._access_token = None
                    self._token_expiry = 0
                    new_token = self._get_access_token()
                    if new_token:
                        url = f"{self._api_url}?access_token={new_token}"
                        continue
                logger.warning(f"百度云 API 错误 [{error_code}]: {error_msg}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return None

            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    self._access_token = None
                    self._token_expiry = 0
                    new_token = self._get_access_token()
                    if new_token:
                        url = f"{self._api_url}?access_token={new_token}"
                        continue
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return None
        return None

    def translate(self, text: str, max_retries: int = 3) -> Optional[str]:
        """调用百度云 MT API 翻译。"""
        token = self._get_access_token()
        if token is None:
            return None

        if len(text) > 6000:
            return self._translate_long(text, token, max_retries)
        return self._translate_segment(text, token, max_retries)

    def _translate_long(
        self, text: str, token: str, max_retries: int
    ) -> Optional[str]:
        """将长文本按 6000 字符分段翻译。"""
        segments: list[str] = []
        for i in range(0, len(text), 6000):
            seg = text[i:i + 6000]
            result = self._translate_segment(seg, token, max_retries)
            if result is None:
                return None
            segments.append(result)
        return "\n".join(segments)


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

    @staticmethod
    def create_api(
        api_type: str = "null",
        baidu_api_key: str = "",
        baidu_secret_key: str = "",
        baidu_app_id: str = "",
        siliconflow_api_key: str = "",
        siliconflow_model: str = "Qwen/Qwen3.5-9B",
    ) -> BaseTranslatorAPI:
        """根据配置创建翻译 API 实例（不含术语表）."""
        if api_type == "baidu" and baidu_api_key and baidu_secret_key:
            return BaiduCloudTranslator(baidu_api_key, baidu_secret_key, baidu_app_id)
        elif api_type == "siliconflow" and siliconflow_api_key:
            return SiliconFlowTranslator(
                api_key=siliconflow_api_key,
                model=siliconflow_model,
            )
        else:
            return NullTranslator()

    @classmethod
    def from_config(
        cls,
        term_file: Optional[str] = None,
        api_type: str = "null",
        baidu_api_key: str = "",
        baidu_secret_key: str = "",
        baidu_app_id: str = "",
        siliconflow_api_key: str = "",
        siliconflow_model: str = "Qwen/Qwen3.5-9B",
        term_table: Optional[TermTable] = None,
    ) -> "TranslatorEngine":
        """从配置创建翻译引擎.

        Args:
            term_file: CSV 术语表路径（与 term_table 二选一）.
            api_type: API 类型 ("null", "baidu", "siliconflow").
            baidu_api_key: 百度云 API Key.
            baidu_secret_key: 百度云 Secret Key.
            baidu_app_id: 百度云 App ID（仅日志）.
            siliconflow_api_key: 硅基流动 API key.
            siliconflow_model: 硅基流动模型名.
            term_table: 已加载的术语表实例（与 term_file 二选一）.
        """
        if term_table is None:
            term_table = TermTable(term_file) if term_file else None

        api = cls.create_api(
            api_type=api_type,
            baidu_api_key=baidu_api_key,
            baidu_secret_key=baidu_secret_key,
            baidu_app_id=baidu_app_id,
            siliconflow_api_key=siliconflow_api_key,
            siliconflow_model=siliconflow_model,
        )
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
