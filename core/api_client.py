#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 客户端 — 支持 xAI/OpenAI/DeepSeek/Claude/Gemini/自定义引擎"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import threading
from dataclasses import dataclass, field
from urllib import request as urlreq
from urllib import error as urlerr
from collections import defaultdict

logger = logging.getLogger(__name__)

_USER_AGENT = "RenpyFileTranslator/1.0"

# ====== 定价表 (每百万 token, 美元) ======

# 按模型精确定价 (input, output)
_MODEL_PRICING = {
    # xAI / Grok — https://docs.x.ai/docs/models
    'grok-4-1-fast-reasoning':             (0.20, 0.50),
    'grok-4-1-fast-non-reasoning':         (0.20, 0.50),
    'grok-code-fast-1':                    (0.20, 1.50),
    'grok-4.20-multi-agent-beta-0309':     (2.00, 6.00),
    'grok-4.20-beta-0309-reasoning':       (2.00, 6.00),
    'grok-4.20-beta-0309-non-reasoning':   (2.00, 6.00),
    # OpenAI
    'gpt-4o-mini':       (0.15, 0.60),
    'gpt-4o':            (2.50, 10.00),
    'gpt-4.1-mini':      (0.40, 1.60),
    'gpt-4.1-nano':      (0.10, 0.40),
    'gpt-4.1':           (2.00, 8.00),
    'o3-mini':           (1.10, 4.40),
    'o1-mini':           (1.10, 4.40),
    'o1':                (15.00, 60.00),
    'o3':                (2.00, 8.00),
    'o4-mini':           (1.10, 4.40),
    # DeepSeek
    'deepseek-chat':     (0.14, 0.28),
    'deepseek-reasoner': (0.55, 2.19),
    # Claude
    'claude-sonnet-4-20250514':   (3.00, 15.00),
    'claude-opus-4-20250514':     (15.00, 75.00),
    'claude-3-5-haiku-20241022':  (0.80, 4.00),
    'claude-3-5-sonnet-20241022': (3.00, 15.00),
    # Gemini
    'gemini-2.5-flash':  (0.15, 0.60),
    'gemini-2.5-pro':    (1.25, 10.00),
    'gemini-2.0-flash':  (0.10, 0.40),
}

# 按提供商兜底（用中等价格，防止低估）
_PROVIDER_PRICING = {
    'xai':      (0.20, 0.50),
    'grok':     (0.20, 0.50),
    'openai':   (2.50, 10.00),
    'deepseek': (0.14, 0.28),
    'claude':   (3.00, 15.00),
    'gemini':   (0.15, 0.60),
}


def get_pricing(provider: str, model: str) -> tuple[float, float, bool]:
    """查询定价：先精确匹配模型名，再按模型家族模糊匹配，最后兜底到提供商。

    Returns:
        (input_price, output_price, is_exact)
        is_exact=True 表示从 _MODEL_PRICING 精确匹配到
    """
    model_lower = model.lower()

    # 1. 精确匹配
    if model_lower in _MODEL_PRICING:
        return (*_MODEL_PRICING[model_lower], True)

    # 2. 前缀匹配 — 处理带日期后缀的模型名（如 grok-3-mini-fast-20250301）
    for key in sorted(_MODEL_PRICING, key=len, reverse=True):
        if model_lower.startswith(key):
            return (*_MODEL_PRICING[key], True)

    # 3. 模型家族模糊匹配（去除版本号/日期后缀再试）
    #    例如 grok-4-1-fast-reasoning → 去掉 -reasoning → grok-4-1-fast
    parts = model_lower.split('-')
    for n in range(len(parts) - 1, 0, -1):
        prefix = '-'.join(parts[:n])
        if prefix in _MODEL_PRICING:
            return (*_MODEL_PRICING[prefix], True)

    # 4. 兜底到提供商
    p = _PROVIDER_PRICING.get(provider.lower(), (3.00, 15.00))
    return (*p, False)


def is_reasoning_model(model: str) -> bool:
    """检测是否为推理模型（会产生大量 thinking tokens 的模型）"""
    name = model.lower()
    # 显式包含推理关键词
    if any(kw in name for kw in ('reasoning', 'think', 'reasoner')):
        return True
    # OpenAI o 系列推理模型
    if re.match(r'^o[1-9]', name):
        return True
    return False


# ============================================================
# Custom engine plugin loader (extracted to core/api_plugin.py in r40)
# ============================================================
#
# Re-exported so callers / tests that used to import these symbols
# from core.api_client continue to work unchanged.
from core.api_plugin import _SubprocessPluginClient

@dataclass
class APIConfig:
    """API 连接配置"""
    provider: str       # xai, openai, deepseek, claude, gemini, custom
    api_key: str
    model: str = ""
    rpm: int = 0        # 每分钟请求数（0=不限）
    rps: int = 0        # 每秒请求数（0=不限）
    timeout: float = 180.0   # 整文件翻译需要更长超时
    temperature: float = 0.1  # 低温保证一致性
    max_retries: int = 5
    max_response_tokens: int = 32768
    custom_module: str = ""  # 自定义翻译引擎模块名（仅 provider="custom" 时使用）
    # Round 52 BREAKING: sandbox_plugin field retired.  All custom plugins
    # now run in subprocess sandbox unconditionally — the host no longer
    # offers in-process loading.  See core/api_plugin.py module docstring
    # for the migration contract (plugin must include __main__ block
    # with _plugin_serve() handling --plugin-serve argv).
    # 持久 HTTPS 连接复用（True=thread-local pool, False=每次新建 urllib 连接）。
    # 默认启用：典型游戏 600 次 API 调用可节省 ~90s 的 TCP+TLS 握手时间。
    # 若遇到兼容问题可通过配置文件设置 "use_connection_pool": false 回退。
    use_connection_pool: bool = True

    # 自动填充
    endpoint: str = field(init=False, default="")
    _resolved: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        providers = {
            'xai': ('https://api.x.ai/v1/chat/completions', 'grok-4-1-fast-reasoning'),
            'grok': ('https://api.x.ai/v1/chat/completions', 'grok-4-1-fast-reasoning'),
            'openai': ('https://api.openai.com/v1/chat/completions', 'gpt-4o-mini'),
            'deepseek': ('https://api.deepseek.com/v1/chat/completions', 'deepseek-chat'),
            'claude': ('https://api.anthropic.com/v1/messages', 'claude-sonnet-4-20250514'),
            'gemini': ('https://generativelanguage.googleapis.com/v1beta/chat/completions', 'gemini-2.5-flash'),
            'custom': ('', 'custom'),
        }
        key = self.provider.lower()
        if key in providers:
            self.endpoint, default_model = providers[key]
            if not self.model:
                self.model = default_model
        # 推理模型自动提高 timeout（推理过程耗时较长）
        if is_reasoning_model(self.model) and self.timeout < 300:
            logger.info(f"[API] 推理模型 {self.model} 检测到，timeout 从 {self.timeout}s 提升到 300s")
            self.timeout = 300.0
        self._resolved = True


class UsageStats:
    """API 用量统计"""

    def __init__(self, provider: str = 'xai', model: str = ''):
        self._lock = threading.Lock()
        self.provider = provider
        self.model = model
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_requests = 0

    def record(self, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_requests += 1

    @property
    def estimated_cost(self) -> float:
        price_in, price_out, _ = get_pricing(self.provider, self.model)
        return (self.total_input_tokens * price_in + self.total_output_tokens * price_out) / 1_000_000

    def summary(self) -> str:
        price_in, price_out, exact = get_pricing(self.provider, self.model)
        cost_str = f"${self.estimated_cost:.4f}"
        if not exact:
            cost_str += " (价格未精确匹配，仅供参考)"
        return (f"请求 {self.total_requests} 次 | "
                f"输入 {self.total_input_tokens:,} tokens | "
                f"输出 {self.total_output_tokens:,} tokens | "
                f"估计费用 {cost_str}")

    def to_dict(self) -> dict:
        """Structured usage snapshot for JSON reports.

        Companion to :meth:`summary`, which returns a human-readable log
        string. Use :meth:`to_dict` when embedding usage in a JSON document
        (e.g. ``pipeline_report.json``) — the string form includes pricing
        disclaimers that would break strict JSON consumption.
        """
        _price_in, _price_out, exact = get_pricing(self.provider, self.model)
        return {
            "provider": self.provider,
            "model": self.model,
            "total_requests": self.total_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(self.estimated_cost, 4),
            "pricing_exact": exact,
        }


class RateLimiter:
    """线程安全速率限制器（不在锁内 sleep）"""

    # Round 26 PF-H-4: cleanup of stale per-second / per-minute buckets
    # runs every N acquisitions instead of every call.  At 5 rps × 64 that
    # caps stale-bucket accumulation at ~13 seconds of history — well under
    # the 5-second and 1-minute relevance windows — while eliminating the
    # per-call ``[k for k in dict]`` scan under the lock.
    _CLEANUP_INTERVAL = 64

    def __init__(self, rpm: int = 0, rps: int = 0):
        self._rpm = rpm
        self._rps = rps
        self._lock = threading.Lock()
        self._minute_counts: dict[str, int] = defaultdict(int)
        self._second_counts: dict[int, int] = defaultdict(int)
        self._cleanup_counter: int = 0

    def acquire(self) -> None:
        while True:
            wait_time = 0.0
            with self._lock:
                if self._rps > 0 and self._second_counts.get(int(time.time()), 0) >= self._rps:
                    wait_time = 1.05
                if wait_time == 0 and self._rpm > 0:
                    minute = time.strftime("%H:%M")
                    if self._minute_counts.get(minute, 0) >= self._rpm:
                        wait_time = max(61 - time.localtime().tm_sec, 1)
                if wait_time == 0:
                    # 可以通过，记录计数
                    sec = int(time.time())
                    self._second_counts[sec] = self._second_counts.get(sec, 0) + 1
                    minute = time.strftime("%H:%M")
                    self._minute_counts[minute] = self._minute_counts.get(minute, 0) + 1

                    # Batch cleanup: drop stale buckets every _CLEANUP_INTERVAL
                    # acquisitions.  Staleness thresholds: 5 s for second
                    # counters, current-minute-only for minute counters.
                    self._cleanup_counter += 1
                    if self._cleanup_counter >= self._CLEANUP_INTERVAL:
                        self._cleanup_counter = 0
                        stale_sec = [k for k in self._second_counts if k < sec - 5]
                        for k in stale_sec:
                            del self._second_counts[k]
                        old_min = [k for k in self._minute_counts if k != minute]
                        for k in old_min:
                            del self._minute_counts[k]
                    return  # 获取成功
            # 在锁外等待
            time.sleep(wait_time)


class APIClient:
    """API 客户端，支持多提供商（含自定义引擎插件）"""

    def __init__(self, config: APIConfig):
        self.config = config
        self._limiter = RateLimiter(config.rpm, config.rps) if (config.rpm or config.rps) else None
        self.usage = UsageStats(config.provider, config.model)
        self._custom_module = None
        if config.provider.lower() == "custom":
            # Round 52 BREAKING: importlib in-process loader retired.
            # All custom plugins run in a sandboxed subprocess.  The
            # returned ``_SubprocessPluginClient`` is duck-typed as a
            # plugin module (exposes ``translate_batch``) so the rest
            # of this file continues to work unchanged.
            self._custom_module = _SubprocessPluginClient(
                config.custom_module, timeout=config.timeout,
            )
        # 持久连接池（仅 HTTPS 端点；custom provider 不走 HTTP 所以也不需要）
        self._pool = None
        if config.use_connection_pool and config.provider.lower() != "custom":
            from core.http_pool import HTTPSConnectionPool
            self._pool = HTTPSConnectionPool(timeout=config.timeout)

    def translate(self, system_prompt: str, user_prompt: str) -> list[dict]:
        """发送翻译请求，返回解析后的 JSON 数组

        Returns:
            [{"line": N, "original": "...", "zh": "..."}, ...]
        """
        if self._limiter:
            self._limiter.acquire()

        raw = self._call_api(system_prompt, user_prompt)
        result = self._parse_json_response(raw)

        # 如果原始响应非空但解析失败，重试一次（附加格式强调）
        if not result and len(raw.strip()) > 20:
            logger.warning("JSON 解析失败，重试中...")
            if self._limiter:
                self._limiter.acquire()
            retry_suffix = "\n\n⚠️ 你必须只返回纯 JSON 数组，不要包含任何其他文字、解释或 markdown 标记。"
            raw = self._call_api(system_prompt, user_prompt + retry_suffix)
            result = self._parse_json_response(raw)
            if not result:
                logger.warning("重试后仍无法解析，跳过该块")

        return result

    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        """调用 API，返回原始响应文本"""
        provider = self.config.provider.lower()

        # 自定义引擎：直接调用用户模块，不走 HTTP 重试逻辑
        if provider == "custom" and self._custom_module is not None:
            return self._call_custom(system_prompt, user_prompt)

        import random

        for attempt in range(1, self.config.max_retries + 1):
            try:
                if provider == 'claude':
                    return self._call_claude(system_prompt, user_prompt)
                else:
                    return self._call_openai_format(system_prompt, user_prompt)
            except urlerr.HTTPError as e:
                status = e.code
                body = ""
                retry_after = 0
                try:
                    # 优先使用服务端返回的 Retry-After header
                    ra = e.headers.get("Retry-After", "") if e.headers else ""
                    if ra and ra.isdigit():
                        retry_after = int(ra)
                except (AttributeError, KeyError, ValueError):
                    pass
                try:
                    body = e.read().decode('utf-8', errors='replace')[:500]
                except (AttributeError, OSError, ValueError):
                    pass

                if status == 404:
                    raise RuntimeError(
                        f"API 404: 模型 '{self.config.model}' 不存在或已下线，"
                        f"请检查 --model 参数是否正确 (body: {body[:200]})"
                    )
                elif status == 401:
                    raise RuntimeError(
                        f"API 401: 认证失败，请检查 --api-key 是否正确 (provider: {self.config.provider})"
                    )
                elif status == 429:
                    base = retry_after if retry_after > 0 else min(2 ** attempt * 5, 60)
                    jitter = random.uniform(0, min(base * 0.3, 5))
                    wait = base + jitter
                    logger.warning(f"429 限速，等待 {wait:.1f}s 后重试 ({attempt}/{self.config.max_retries})")
                    time.sleep(wait)
                    continue
                elif status >= 500:
                    base = min(2 ** attempt * 3, 60)
                    jitter = random.uniform(0, min(base * 0.3, 5))
                    wait = base + jitter
                    logger.warning(f"{status} 服务端错误，等待 {wait:.1f}s 后重试 ({attempt}/{self.config.max_retries})")
                    time.sleep(wait)
                    continue
                else:
                    raise RuntimeError(f"API {status} 错误: {body}")
            except (urlerr.URLError, OSError, TimeoutError) as e:
                if attempt < self.config.max_retries:
                    base = min(2 ** attempt * 3, 60)
                    jitter = random.uniform(0, min(base * 0.3, 5))
                    wait = base + jitter
                    logger.warning(f"网络错误: {e}, 等待 {wait:.1f}s 后重试 ({attempt}/{self.config.max_retries})")
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"API 调用失败，已重试 {self.config.max_retries} 次")

    def _call_openai_format(self, system_prompt: str, user_prompt: str) -> str:
        """OpenAI 兼容格式 (xAI / OpenAI / DeepSeek)"""
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_response_tokens,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "User-Agent": _USER_AGENT,
        }
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        if self._pool is not None:
            raw = self._pool.post(self.config.endpoint, data, headers)
            result = json.loads(raw.decode('utf-8'))
        else:
            from core.http_pool import read_bounded
            req = urlreq.Request(self.config.endpoint, data=data, headers=headers)
            with urlreq.urlopen(req, timeout=self.config.timeout) as resp:
                result = json.loads(read_bounded(resp).decode('utf-8'))

        # 记录 token 用量
        usage = result.get("usage", {})
        self.usage.record(
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )

        choices = result.get("choices") or []
        if not choices:
            logger.warning("[API] 响应中无 choices 字段，返回空内容")
            return ""
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        # grok reasoning 模型可能有 reasoning_content
        if not content and msg.get("reasoning_content"):
            reasoning = msg["reasoning_content"]
            # 尝试多种 JSON 数组开头模式（direct-mode: [{"line", tl-mode: [{"id"）
            bracket_start = -1
            for pattern in ('[{"line"', '[{"id"', '[{"original"', '[{'):
                pos = reasoning.rfind(pattern)
                if pos >= 0:
                    bracket_start = pos
                    break
            if bracket_start >= 0:
                bracket_end = reasoning.rfind(']')
                if bracket_end > bracket_start:
                    content = reasoning[bracket_start:bracket_end + 1]
            if not content:
                content = reasoning
        return content or ""

    def _call_claude(self, system_prompt: str, user_prompt: str) -> str:
        """Anthropic Claude 格式"""
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_response_tokens,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.config.temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": _USER_AGENT,
        }
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

        if self._pool is not None:
            raw = self._pool.post(self.config.endpoint, data, headers)
            result = json.loads(raw.decode('utf-8'))
        else:
            from core.http_pool import read_bounded
            req = urlreq.Request(self.config.endpoint, data=data, headers=headers)
            with urlreq.urlopen(req, timeout=self.config.timeout) as resp:
                result = json.loads(read_bounded(resp).decode('utf-8'))

        # 记录 token 用量
        usage = result.get("usage", {})
        self.usage.record(
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )

        blocks = result.get("content", [])
        if not blocks:
            return ""
        return blocks[0].get("text", "")

    def _call_custom(self, system_prompt: str, user_prompt: str) -> str:
        """调用自定义翻译引擎模块。

        优先使用 ``translate_batch(items, source_lang, target_lang)`` 批量接口。
        如果模块未实现批量接口，降级为 ``translate(text, source_lang, target_lang)``
        逐条翻译，结果包装为 JSON 数组字符串返回。
        """
        mod = self._custom_module
        if mod is None:
            raise RuntimeError("自定义引擎模块未加载")

        if hasattr(mod, "translate_batch"):
            # 批量接口：直接传 user_prompt（JSON 数组），返回 JSON 数组字符串
            result = mod.translate_batch(system_prompt, user_prompt)
            if isinstance(result, str):
                return result
            # 如果返回的是 list[dict]，序列化为 JSON 字符串
            return json.dumps(result, ensure_ascii=False)

        if hasattr(mod, "translate"):
            # 单句降级：解析 user_prompt 中的条目，逐条调用 translate()
            try:
                items = json.loads(user_prompt) if user_prompt.strip().startswith("[") else []
            except (json.JSONDecodeError, ValueError):
                items = []

            if not items:
                # 非 JSON 数组格式，直接传整个 prompt
                return mod.translate(user_prompt, "en", self.config.model or "zh")

            results = []
            for item in items:
                original = item.get("original", item.get("text", ""))
                if not original:
                    continue
                translated = mod.translate(original, "en", self.config.model or "zh")
                entry = dict(item)
                entry["zh"] = translated
                results.append(entry)
            return json.dumps(results, ensure_ascii=False)

        raise RuntimeError(
            f"自定义引擎模块必须实现 translate_batch() 或 translate() 函数"
        )

    @staticmethod
    def _parse_json_response(text: str) -> list[dict]:
        """从 AI 响应中提取 JSON 数组

        处理常见格式问题：markdown 代码块、多余文字等
        """
        text = text.strip()

        # 1. 尝试直接解析
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # 2. 从 markdown 代码块提取
        md_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
        if md_match:
            try:
                result = json.loads(md_match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 3. 找到第一个 [ 和最后一个 ]
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end > start:
            try:
                result = json.loads(text[start:end + 1])
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 4. 尝试修复常见 JSON 问题（末尾逗号）
        if start != -1 and end > start:
            fixed = re.sub(r',\s*([}\]])', r'\1', text[start:end + 1])
            try:
                result = json.loads(fixed)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 5. 逐个提取翻译对象（容错：即使整体 JSON 损坏也能挽救部分结果）
        # 5a. direct-mode: {"line": N, "original": "...", "zh": "..."}
        obj_re = re.compile(
            r'\{\s*"line"\s*:\s*\d+\s*,\s*"original"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"zh"\s*:\s*"(?:[^"\\]|\\.)*"\s*\}'
        )
        matches = obj_re.findall(text)
        if matches:
            results = []
            for m in matches:
                try:
                    results.append(json.loads(m))
                except json.JSONDecodeError:
                    continue
            if results:
                return results

        # 5b. tl-mode: {"id": "xxx", "original": "...", "zh": "..."}
        obj_re_tl = re.compile(
            r'\{\s*"id"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"original"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"zh"\s*:\s*"(?:[^"\\]|\\.)*"\s*\}'
        )
        matches_tl = obj_re_tl.findall(text)
        if matches_tl:
            results = []
            for m in matches_tl:
                try:
                    results.append(json.loads(m))
                except json.JSONDecodeError:
                    continue
            if results:
                return results

        # 6. 尝试容忍字段顺序变化（部分模型可能调换字段顺序）
        obj_re2 = re.compile(
            r'\{[^{}]*"(?:line|id)"\s*:\s*(?:\d+|"[^"]*")[^{}]*"zh"\s*:\s*"(?:[^"\\]|\\.)*"[^{}]*\}'
        )
        matches2 = obj_re2.findall(text)
        if matches2:
            results = []
            for m in matches2:
                try:
                    obj = json.loads(m)
                    if ('line' in obj or 'id' in obj) and 'zh' in obj:
                        results.append(obj)
                except json.JSONDecodeError:
                    continue
            if results:
                return results

        # 7. Round 53 W2: escape-fix preprocessing for LLM mis-escape.
        #    LLMs occasionally emit unescaped `"` inside string values
        #    (e.g. ``{"zh": "他说"你好""}`` where the inner quotes should
        #    be ``\"``). Layers 1-6 are structural — they cannot recover
        #    from a tokenizer break inside a value. Layer 7 char-walks
        #    the text, escapes stray quotes inside string scopes, then
        #    re-runs layers 1 + 3.
        repaired = _repair_unescaped_quotes_in_strings(text)
        if repaired != text:
            try:
                result = json.loads(repaired)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
            r_start = repaired.find('[')
            r_end = repaired.rfind(']')
            if r_start != -1 and r_end > r_start:
                try:
                    result = json.loads(repaired[r_start:r_end + 1])
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    pass

        logger.error(f"无法解析 AI 响应为 JSON 数组，响应前200字符: {text[:200]}")
        return []


def _repair_unescaped_quotes_in_strings(text: str) -> str:
    """Round 53 W2: escape stray `"` inside JSON string values.

    LLMs occasionally emit JSON like ``{"zh": "他说"你好""}`` where the
    inner ``"`` should be ``\\"``. The 6-layer structural fallback chain
    in :func:`APIClient._parse_json_response` cannot recover from this
    because the tokenizer breaks inside a value. This helper walks the
    text char-by-char, tracking string-scope state, and escapes any
    ``"`` that does not look like a string boundary.

    A ``"`` is treated as a closing string boundary when the next non-
    whitespace character is one of ``,]}:``. Otherwise it is escaped.
    Properly skips over backslash-escape sequences (``\\X`` always
    passes through unchanged when inside a string).

    Returns the repaired text. Pathological inputs (unbalanced braces,
    nested escape sequences across multiple values) may not be fully
    repaired — the caller still attempts ``json.loads`` and falls
    through to the final logger.error if repair is insufficient.

    Pure standard library — no third-party dependencies.
    """
    out: list[str] = []
    in_string = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\' and in_string and i + 1 < n:
            # Pass through any escape sequence (\", \\, \n, \uXXXX, etc.)
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c == '"':
            if not in_string:
                in_string = True
                out.append(c)
            else:
                # Peek the next non-whitespace character to decide.
                j = i + 1
                while j < n and text[j] in (' ', '\t', '\n', '\r'):
                    j += 1
                if j >= n or text[j] in (',', ']', '}', ':'):
                    in_string = False
                    out.append(c)
                else:
                    # Stray quote inside string value — escape it.
                    out.append('\\"')
        else:
            out.append(c)
        i += 1
    return ''.join(out)
