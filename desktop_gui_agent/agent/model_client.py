# -*- coding: utf-8 -*-
"""模型客户端 — PDF 4.3.1

加载 Qwen2-VL 视觉语言模型，将截图和任务描述一起发送给模型，
返回模型的原始文本响应。优先使用本地 Transformers 推理，
同时支持 API 调用作为备选。
"""
import base64
import io
import os
import time
from typing import Optional

import requests
from PIL import Image

from desktop_gui_agent.config import (
    MODEL_API_KEY,
    MODEL_API_URL,
    MODEL_MAX_TOKENS,
    MODEL_MODE,
    MODEL_NAME,
)

import desktop_gui_agent.config as _config
from desktop_gui_agent.utils.exceptions import ModelError
from desktop_gui_agent.utils.logger import get_logger

# ===== 双层 AI 架构常量 =====
# 判断层和执行层分开，脑子管策略，手管精确坐标
_EXECUTOR_MAX_TOKENS = 128  # 执行层输出极短（只需一个动作），防止长篇生成卡住
_JUDGE_MAX_TOKENS = _config.MODEL_MAX_TOKENS_JUDGE  # 判断层输出更短


def _resolve_api_preset(preset: Optional[str]) -> dict:
    """根据预设名称解析 API 配置。

    Args:
        preset: 预设名称（"dashscope" / "ollama"），None 或空字符串不解析。

    Returns:
        {"mode": str, "model_name": str, "api_url": str, "api_key": str}
        若 preset 为 None 则返回空字典。

    Raises:
        ModelError: 预设名称不存在。
    """
    if not preset:
        return {}

    presets = getattr(_config, "API_PRESETS", {})
    if preset not in presets:
        raise ModelError(
            f"API 预设 '{preset}' 不存在。可用预设: {list(presets.keys())}"
        )

    entry = presets[preset]
    api_key = ""
    if entry.get("api_key_env"):
        api_key = os.environ.get(entry["api_key_env"], "")
        if not api_key:
            logger.warning(
                f"API 预设 '{preset}' 需要环境变量 {entry['api_key_env']}，"
                f"但未设置。请运行: set {entry['api_key_env']}=你的Key"
            )

    return {
        "mode": "api",
        "model_name": entry["model"],
        "api_url": entry["base_url"],
        "api_key": api_key,
    }

logger = get_logger(__name__)

try:
    from qwen_vl_utils import process_vision_info
except ImportError:
    process_vision_info = None
    logger.warning("qwen-vl-utils 未安装，本地推理将不可用。请运行: pip install qwen-vl-utils")

# ===== Prompt 模板 =====
# 从 config.py 读取，如需自定义可在 config.py 中修改


class ModelClient:
    """Qwen2-VL 模型客户端。

    封装模型加载、prompt 拼接和推理调用。

    Attributes:
        mode: 推理模式，"local" 或 "api"。
        model_name: 模型名称或路径。
        api_url: API 端点（仅 api 模式）。
    """

    def __init__(
        self,
        mode: str = MODEL_MODE,
        model_name: Optional[str] = None,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        # 判断层参数（双层架构）
        judge_mode: Optional[str] = None,
        judge_model_name: Optional[str] = None,
        judge_api_url: Optional[str] = None,
        judge_api_key: Optional[str] = None,
        # API 预设（一键切换）
        api_preset: Optional[str] = None,
    ):
        """初始化模型客户端。

        Args:
            mode: 推理模式，"local" 或 "api"。
            model_name: 模型名称，None 则使用 config.MODEL_NAME（执行层）。
            api_url: API 端点，None 则使用 config.MODEL_API_URL（执行层）。
            api_key: API 密钥，None 则使用 config.MODEL_API_KEY（执行层）。
            judge_mode: 判断层推理模式，None 则使用 config.MODEL_MODE_JUDGE。
            judge_model_name: 判断层模型，None 则使用 config.MODEL_NAME_JUDGE。
            judge_api_url: 判断层 API 端点，None 则使用 config.MODEL_API_URL_JUDGE。
            judge_api_key: 判断层 API 密钥，None 则使用 config.MODEL_API_KEY_JUDGE。
            api_preset: API 预设名称（"dashscope" / "ollama"），
                        自动解析 mode/model_name/api_url/api_key。
                        None 则使用默认 config 值。

        Raises:
            ModelError: 模式不合法或模型加载失败。
        """
        # 应用 API 预设（优先于单独参数）
        preset = _resolve_api_preset(api_preset)
        if preset:
            mode = preset["mode"]
            model_name = preset["model_name"]
            api_url = preset["api_url"]
            api_key = preset["api_key"]
            logger.info(f"API 预设 '{api_preset}' 已应用: {preset['model_name']} @ {preset['api_url']}")

        if mode not in ("local", "api"):
            raise ModelError(f"不支持的推理模式: {mode}，可选 'local' 或 'api'")

        self.mode = mode
        self.model_name = model_name or MODEL_NAME
        self.api_url = api_url or MODEL_API_URL
        self.api_key = api_key or MODEL_API_KEY
        self._model = None
        self._processor = None

        # 判断层配置
        self.judge_mode = judge_mode or _config.MODEL_MODE_JUDGE
        self.judge_model_name = judge_model_name or _config.MODEL_NAME_JUDGE
        self.judge_api_url = judge_api_url or _config.MODEL_API_URL_JUDGE
        self.judge_api_key = judge_api_key or _config.MODEL_API_KEY_JUDGE
        self._judge_model = None
        self._judge_processor = None

        logger.info(f"ModelClient 初始化，模式: {self.mode}，模型: {self.model_name}")
        if _config.TWO_STAGE_ENABLED:
            logger.info(
                f"双层架构已启用，判断层: {self.judge_model_name} ({self.judge_mode})"
            )

    # 模型输入图片最大边长（像素），超过则等比缩放
    # 2B 模型在 8GB 显存下安全值，过大易 OOM
    _MAX_IMAGE_SIZE = 896

    @staticmethod
    def _resize_image(image: Image.Image, max_size: int = _MAX_IMAGE_SIZE) -> Image.Image:
        """将图片等比缩放到最大边长以内，避免显存溢出。

        Args:
            image: 原始截图。
            max_size: 最大边长（像素）。

        Returns:
            缩放后的图片。
        """
        w, h = image.size
        if max(w, h) <= max_size:
            return image
        ratio = max_size / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        return image.resize((new_w, new_h), Image.LANCZOS)

    # ===== Prompt 构建辅助方法 =====

    @staticmethod
    def _build_system_prompt() -> str:
        """构建系统提示词（含 few-shot 示例）。"""
        system = _config.PROMPT_SYSTEM
        if _config.PROMPT_FEW_SHOT_EXAMPLES:
            system += "\n\n" + "\n\n".join(_config.PROMPT_FEW_SHOT_EXAMPLES)
        return system

    @staticmethod
    def _extract_keywords(task: str) -> list:
        """从任务文本中提取关键词，用于 OCR 结果排序。

        对中文任务：提取所有 2-4 字的连续中文片段。
        对英文任务：提取所有单词。

        Args:
            task: 用户任务文本。

        Returns:
            关键词列表（去重）。
        """
        import re
        keywords = []
        # 提取中文词组（2-4字）
        chinese_words = re.findall(r'[一-鿿]{2,4}', task)
        keywords.extend(chinese_words)
        # 对每个中文词组，再拆出所有2字子串（如"打开微信"→"打开"+"微信"）
        for word in chinese_words:
            for i in range(len(word) - 1):
                sub = word[i:i+2]
                if sub not in keywords:
                    keywords.append(sub)
        # 提取英文单词
        english_words = re.findall(r'[a-zA-Z]{2,}', task)
        keywords.extend(english_words)
        return list(set(keywords))


    # OCR 噪声过滤 —— 终端/CLI 文字和 agent 自己的 UI
    _OCR_NOISE_PATTERNS = [
        # Agent 自己的 UI
        "桌面GUI智能体", "输入任务开始", "输入 exit 退出",
        "已退出", ">>>", "❌ 未完成", "✅ 完成",
        "开始任务:", "任务历史已保存",
        # 日志输出碎片
        "| INFO", "| WARNING", "| ERROR", "| DEBUG",
        "desktop_gui_agent", "model_client",
        # PowerShell / CMD 提示符
        "PS D:", "PS C:", "PS E:", "C:\\Users", "C:\\Windows",
        # CLI 错误消息关键词
        "can't open", "No such file", "Errno", "Traceback",
        "ModuleNotFoundError", "Error:", "exit code",
    ]

    @staticmethod
    def _is_ocr_noise(text: str, task: str = "") -> bool:
        """判断 OCR 文字是否为噪声（终端/CLI/agent UI）。"""
        # 1. 匹配已知噪声模式
        noise = list(ModelClient._OCR_NOISE_PATTERNS)
        if task:
            noise.append(task)
        if any(n in text for n in noise):
            return True
        # 2. 路径特征：包含反斜杠或正斜杠+字母（如 D:\ 或 agent/gui）
        if "\\" in text or ("/" in text and any(c.isalpha() for c in text)):
            return True
        # 3. 冒号路径（D:、C:）
        import re
        if re.search(r'[A-Z]:[\\/]', text):
            return True
        # 4. 太短（1 字符 / 纯ASCII 2字符碎片往往是噪声，但2字中文可能是有效文本如"微信"）
        stripped = text.strip()
        if len(stripped) <= 1:
            return True
        if len(stripped) == 2 and stripped.isascii():
            return True  # 如 "OK", "ab" 等才是噪声
        # 5. 纯标点/特殊字符
        if re.match(r'^[\s\-_=#*.:;,/\\|><]+$', text):
            return True
        return False

    @staticmethod
    def _build_ocr_text(ocr_results: list, include_coords: bool = True,
                        max_items: int = 15, task: str = "") -> str:
        """将 OCR 结果格式化为 prompt 文本。

        自动过滤掉终端/CLI/agent UI 噪声文字。

        Args:
            ocr_results: OCR 结果列表。
            include_coords: True=含坐标（给执行层用），False=纯文字（给判断层用）。
            max_items: 最多取前 N 条。
            task: 当前用户任务文本，也会被过滤。
        """
        if not ocr_results:
            return ""
        # 排序：任务相关关键词优先排在前面（确保目标不在屏幕上时不被裁掉）
        task_keywords = ModelClient._extract_keywords(task)
        sorted_results = sorted(
            ocr_results,
            key=lambda item: (
                not any(kw in item["text"] or item["text"] in kw
                    for kw in task_keywords),  # 双向匹配：任务词↔OCR文本
            ),
        )
        lines = []
        for item in sorted_results[:max_items]:
            text = item["text"]
            if ModelClient._is_ocr_noise(text, task):
                continue
            if include_coords:
                x1, y1, x2, y2 = item["bbox"]
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                text_h = y2 - y1
                # 图标在文字上方约半个文字高度（~15-25px），开始菜单和桌面都适用
                icon_y = max(0, y1 - text_h)
                lines.append(
                    f'  "{text}" 图标({cx},{icon_y}) 文字({cx},{cy})'
                )
            else:
                lines.append(f'  "{text}"')
        if not lines:
            return ""
        header = (
            "【OCR识别结果】屏幕上的文字元素及其精确坐标："
            if include_coords
            else "【OCR识别结果】屏幕上的文字元素："
        )
        return "\n" + header + "\n" + "\n".join(lines) + "\n"

    def _build_user_prompt(
        self, task: str, context: list = None, ocr_results: list = None,
        cot_enabled: bool = True, extra_text: str = "",
    ) -> str:
        """构建用户提示词。"""
        prompt = _config.PROMPT_USER_TEMPLATE.format(task=task)

        if cot_enabled and _config.PROMPT_COT_ENABLED:
            prompt += "\n请按格式输出：观察 → 分析 → 动作，三行。"

        if context:
            history = "\n".join(
                f"  步骤{i+1}: {act}" for i, act in enumerate(context)
            )
            prompt += f"\n已完成步骤：\n{history}"

        if extra_text:
            prompt += f"\n{extra_text}"

        if ocr_results:
            prompt += self._build_ocr_text(ocr_results, include_coords=True, task=task)

        return prompt

    # ===== 公开查询接口 =====

    def query(
        self,
        image: Image.Image,
        task: str,
        context: Optional[list] = None,
        ocr_results: Optional[list] = None,
        extra_text: str = "",
    ) -> str:
        """向模型发送截图和任务，返回模型响应。

        双层架构（TWO_STAGE_ENABLED=True）：
          判断层(7B)分析屏幕→制定策略 → 执行层(2B)根据策略+OCR坐标输出精确动作。
        单层架构（TWO_STAGE_ENABLED=False）：
          直接由执行层模型一步完成理解和动作输出。

        Args:
            image: 当前屏幕截图 (PIL.Image)。
            task: 用户自然语言任务描述。
            context: 前几步的历史动作记录（可选）。
            ocr_results: OCR 识别结果列表（可选），用于提供精确坐标。

        Returns:
            模型的原始文本输出（含精确动作）。

        Raises:
            ModelError: 推理失败或超时。
        """
        if image is None:
            raise ModelError("输入截图不能为 None")

        image = self._resize_image(image)

        # 尝试双层架构
        if _config.TWO_STAGE_ENABLED:
            try:
                return self._query_two_stage(image, task, context, ocr_results)
            except Exception as e:
                logger.warning(
                    f"双层推理失败，降级为单层模式: {e}"
                )
                # 降级为单层，继续执行

        # 单层模式（默认/降级）
        return self._query_single(image, task, context, ocr_results, extra_text)

    def _query_two_stage(
        self, image: Image.Image, task: str,
        context: list, ocr_results: list,
    ) -> str:
        """双层推理：判断层分析 + 执行层精确动作。"""
        # === Stage 1: 判断层（脑子）—— 只看文字OCR，不懂坐标 ===
        judge_prompt = _config.PROMPT_JUDGE_USER.format(task=task)
        if context:
            history = "\n".join(
                f"  步骤{i+1}: {act}" for i, act in enumerate(context)
            )
            judge_prompt += f"\n已完成步骤：\n{history}"
        # 判断层只给文字列表（不含坐标），聚焦语义理解
        if ocr_results:
            judge_prompt += self._build_ocr_text(ocr_results, include_coords=False, task=task)

        logger.info("【判断层】开始分析…")
        judge_output = self._query_judge(image, judge_prompt)
        logger.info(f"【判断层】输出: {judge_output[:120]}")

        # 判断层输出过长时截断（防止垃圾文本污染执行层）
        if len(judge_output) > 300:
            logger.warning(f"判断层输出过长({len(judge_output)}字符)，截断至300字符")
            judge_output = judge_output[:300]

        # === Stage 2: 执行层（手）—— 大脑分析 + OCR坐标 → 精确动作 ===
        executor_prompt = _config.PROMPT_USER_TEMPLATE.format(task=task)
        # 注入判断层分析
        executor_prompt += (
            f"\n\n【大脑分析】\n{judge_output}"
            f"\n\n请根据以上分析，结合OCR坐标，输出下一步精确动作（只输出动作本身即可）。"
        )
        if context:
            history = "\n".join(
                f"  步骤{i+1}: {act}" for i, act in enumerate(context)
            )
            executor_prompt += f"\n已完成步骤：\n{history}"
        if ocr_results:
            executor_prompt += self._build_ocr_text(ocr_results, include_coords=True, task=task)
            executor_prompt += "\n请使用OCR提供的坐标来精确点击目标，不要自己猜测坐标。"

        logger.info("【执行层】根据大脑分析生成精确动作…")
        return self._query_executor(image, executor_prompt)

    def _query_single(
        self, image: Image.Image, task: str,
        context: list, ocr_results: list,
        extra_text: str = "",
    ) -> str:
        """单层推理（原逻辑，兼容 TWO_STAGE_ENABLED=False）。"""
        user_prompt = self._build_user_prompt(task, context, ocr_results, extra_text=extra_text)

        if self.mode == "local":
            return self._query_local(image, user_prompt, self.model_name)
        else:
            return self._query_api(image, user_prompt, self.model_name,
                                   self.api_url, self.api_key, MODEL_MAX_TOKENS)

    # ===== 判断层推理 =====

    def _query_judge(self, image: Image.Image, user_prompt: str) -> str:
        """调用判断层模型（7B），返回自由文本策略分析。"""
        if self.judge_mode == "local":
            return self._query_local(
                image=image,
                user_prompt=user_prompt,
                model_name=self.judge_model_name,
                max_tokens=_JUDGE_MAX_TOKENS,
                system_prompt=_config.PROMPT_JUDGE_SYSTEM,
            )
        else:
            return self._query_api(
                image=image,
                user_prompt=user_prompt,
                model_name=self.judge_model_name,
                api_url=self.judge_api_url,
                api_key=self.judge_api_key,
                max_tokens=_JUDGE_MAX_TOKENS,
                system_prompt=_config.PROMPT_JUDGE_SYSTEM,
            )

    # ===== 执行层推理 =====

    def _query_executor(self, image: Image.Image, user_prompt: str) -> str:
        """调用执行层模型（2B），根据 judge 分析 + OCR 坐标输出精确动作。"""
        if self.mode == "local":
            return self._query_local(
                image=image, user_prompt=user_prompt,
                model_name=self.model_name,
                max_tokens=_EXECUTOR_MAX_TOKENS,
            )
        else:
            return self._query_api(
                image=image, user_prompt=user_prompt,
                model_name=self.model_name,
                api_url=self.api_url, api_key=self.api_key,
                max_tokens=_EXECUTOR_MAX_TOKENS,
            )

    # ===== 本地推理 =====

    def _query_local(
        self, image: Image.Image, user_prompt: str,
        model_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """本地 Transformers 推理。

        Args:
            image: 截图。
            user_prompt: 用户提示词文本。
            model_name: 模型名，None 则用 self.model_name。
            max_tokens: 最大输出 token 数，None 则用 MODEL_MAX_TOKENS。
            system_prompt: 自定义系统提示词，None 则用 _build_system_prompt()。
        """
        model_name = model_name or self.model_name
        max_tokens = max_tokens or MODEL_MAX_TOKENS
        is_judge = system_prompt is not None

        # 判断层和执行层可能用不同模型
        # 如果模型名相同，复用同一个实例（节省显存）
        if is_judge:
            if model_name == self.model_name and self._model is not None:
                # 同模型复用（执行层先加载的场景）
                model, processor = self._model, self._processor
            elif self._judge_model is not None:
                model, processor = self._judge_model, self._judge_processor
            else:
                self._judge_model, self._judge_processor = _load_local_model(model_name)
                model, processor = self._judge_model, self._judge_processor
                # 模型名相同 → 执行层也指向同一实例，避免重复加载
                if model_name == self.model_name:
                    self._model, self._processor = self._judge_model, self._judge_processor
        elif self._model is not None:
            model, processor = self._model, self._processor
        else:
            self._model, self._processor = _load_local_model(model_name)
            model, processor = self._model, self._processor
            # 模型名相同 → 判断层也指向同一实例
            if model_name == self.judge_model_name:
                self._judge_model, self._judge_processor = self._model, self._processor

        try:
            system_content = system_prompt or self._build_system_prompt()
            messages = [
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ]

            # 使用 processor 处理消息
            text = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            if process_vision_info is None:
                raise ModelError(
                    "qwen-vl-utils 未安装，无法进行本地推理。"
                    "请运行: pip install qwen-vl-utils"
                )
            image_inputs, video_inputs = process_vision_info(messages)

            inputs = processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(model.device)

            start_time = time.time()
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=max_tokens,
            )
            elapsed = time.time() - start_time

            # 只取新生成的部分（去掉输入 token）
            generated_ids_trimmed = [
                out_ids[len(in_ids):]
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]

            label = "判断层" if is_judge else "本地"
            logger.info(
                f"{label}推理完成，耗时 {elapsed:.2f}s，输出: {output_text[:80]}"
            )
            return output_text.strip()

        except Exception as e:
            logger.error(f"本地推理失败: {e}")
            raise ModelError(f"本地推理失败: {e}")

    # ===== API 推理 =====

    def _query_api(
        self, image: Image.Image, user_prompt: str,
        model_name: Optional[str] = None,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """通过 HTTP API 调用远程模型。

        Args:
            image: 截图。
            user_prompt: 用户提示词文本。
            model_name: API 模型名，None 则用 self.model_name。
            api_url: API 端点，None 则用 self.api_url。
            api_key: API 密钥，None 则用 self.api_key。
            max_tokens: 最大输出 token 数，None 则用 MODEL_MAX_TOKENS。
            system_prompt: 自定义系统提示词，None 则用 _build_system_prompt()。
        """
        api_url = api_url or self.api_url
        api_key = api_key or self.api_key
        model_name = model_name or self.model_name
        max_tokens = max_tokens or MODEL_MAX_TOKENS

        if not api_url:
            raise ModelError("API 模式需要配置 API URL")

        # 系统提示词
        system_content = system_prompt or self._build_system_prompt()

        # PIL Image → base64
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_content},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            "max_tokens": max_tokens,
        }

        # 重试逻辑：最多 2 次
        last_error = None
        for attempt in range(2):
            try:
                start_time = time.time()
                resp = requests.post(
                    api_url.rstrip("/") + "/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=60,
                )
                resp.raise_for_status()
                elapsed = time.time() - start_time

                data = resp.json()
                output = data["choices"][0]["message"]["content"]
                logger.info(f"API 推理完成，耗时 {elapsed:.2f}s，输出: {output[:80]}")
                return output.strip()

            except Exception as e:
                last_error = e
                logger.warning(f"API 调用失败 (尝试 {attempt+1}/2): {e}")
                if attempt == 0:
                    time.sleep(1)  # 重试前等待 1 秒

        raise ModelError(f"API 调用失败（已重试）: {last_error}")


def _load_local_model(model_name: str):
    """加载本地 Qwen2-VL 模型和处理器。

    Args:
        model_name: HuggingFace 模型名称或本地路径。

    Returns:
        (model, processor) 元组。
    """
    from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

    logger.info(f"正在加载本地模型: {model_name}")
    try:
        # 使用 torch.float16 减少显存占用
        import torch

        # 动态计算 GPU 显存上限，防止 VRAM 耗尽导致系统崩溃
        # 笔记本 8GB 显卡：预留 2GB 给 KV Cache + 系统，上限 6GB
        max_memory = None
        if torch.cuda.is_available():
            gpu_id = 0
            total_vram = torch.cuda.get_device_properties(gpu_id).total_memory
            total_gb = total_vram / (1024 ** 3)
            # 使用配置中的比例（默认 0.75），或直接使用配置的绝对值
            if _config.MODEL_GPU_MEMORY_GB:
                limit_gb = _config.MODEL_GPU_MEMORY_GB
            else:
                limit_gb = int(total_gb * _config.MODEL_GPU_MEMORY_RATIO)
            max_memory = {gpu_id: f"{limit_gb}GB"}
            logger.info(
                f"GPU 总显存 {total_gb:.1f}GB，"
                f"模型加载上限设为 {limit_gb}GB"
            )

        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
            max_memory=max_memory,
        )
        processor = AutoProcessor.from_pretrained(model_name)
        logger.info("本地模型加载成功")
        return model, processor
    except Exception as e:
        logger.error(f"本地模型加载失败: {e}")
        raise ModelError(f"本地模型加载失败: {e}")
