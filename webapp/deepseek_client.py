import json
import time
import requests
from pathlib import Path

from config import config

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """加载 prompt 模板文件"""
    prompt_path = PROMPTS_DIR / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def call_deepseek(
    api_key: str,
    system_prompt: str,
    user_message: str,
    model: str = "deepseek-v4-pro",
    temperature: float = 0.1,
    max_tokens: int = 8192,
    timeout: int = 120,
    max_retries: int = 3,
) -> str:
    """调用 DeepSeek API（OpenAI 兼容格式），含自动重试"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                config.DEEPSEEK_API_URL,
                headers=headers,
                json=body,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout as e:
            last_error = e
            wait = (attempt + 1) * 10
            time.sleep(wait)
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2**attempt
                time.sleep(wait)

    raise RuntimeError(
        f"DeepSeek API 调用失败（重试 {max_retries} 次）: {last_error}"
    )


def translate_to_chinese(
    texts: list[str],
    api_key: str | None = None,
    model: str | None = None,
    batch_size: int = 20,
    timeout: int = 60,
) -> list[str]:
    """批量翻译英文文本为中文，使用 DeepSeek Flash 降低成本。

    Args:
        texts: 英文文本列表
        api_key: 默认使用 config.DEEPSEEK_API_KEY
        model: 默认使用 DEEPSEEK_FLASH_MODEL（更快更便宜）
        batch_size: 每次 API 调用处理的文本数
        timeout: 每次 API 调用超时秒数

    Returns:
        与输入等长的翻译后文本列表；翻译失败时返回原文
    """
    if not texts:
        return []

    api_key = api_key or config.DEEPSEEK_API_KEY
    model = model or getattr(config, "DEEPSEEK_FLASH_MODEL", "deepseek-chat")

    results = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        user_message = (
            "请将以下英文文本翻译成简体中文。"
            "保持专业技术术语的准确性，保留所有专有名词（公司名、产品名、人名、URL、数字）。"
            "每个 [CHUNK_N] 标记后是该段落的翻译结果。只输出翻译，不要额外解释。\n\n"
        )
        for j, text in enumerate(batch):
            user_message += f"\n[CHUNK_{j}]\n{text[:2000]}\n"

        try:
            translated = call_deepseek(
                api_key,
                "You are a professional Chinese translator specialized in technology "
                "and business content. Translate English to simplified Chinese accurately.",
                user_message,
                model=model,
                temperature=0.1,
                max_tokens=4096,
                timeout=timeout,
                max_retries=2,
            )

            # 解析 [CHUNK_N] 分隔符
            import re
            pattern = re.compile(r'\[CHUNK_(\d+)\]\s*(.*?)(?=\[CHUNK_\d+\]|$)', re.DOTALL)
            chunk_map = {}
            for match in pattern.finditer(translated):
                idx = int(match.group(1))
                translation = match.group(2).strip()
                chunk_map[idx] = translation

            for j, original in enumerate(batch):
                results.append(chunk_map.get(j, original))

        except Exception as e:
            print(f"[translate] batch failed: {e}")
            results.extend(batch)

    return results


def call_deepseek_with_prompt_file(
    api_key: str,
    prompt_name: str,
    user_message: str,
    model: str = "deepseek-v4-pro",
    temperature: float = 0.1,
    **kwargs,
) -> str:
    """从 prompt 文件加载系统提示词，调用 DeepSeek"""
    system_prompt = load_prompt(prompt_name)
    return call_deepseek(
        api_key, system_prompt, user_message, model=model, temperature=temperature, **kwargs
    )
