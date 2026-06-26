# -*- coding: utf-8 -*-
"""模型客户端 — PDF 4.3.1

加载 Qwen2-VL 视觉语言模型，将截图和任务描述一起发送给模型，
返回模型的原始文本响应。优先使用本地 Transformers 推理，
同时支持 API 调用作为备选。
"""
import base64
import io
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
from desktop_gui_agent.utils.exceptions import ModelError
from desktop_gui_agent.utils.logger import get_logger

logger = get_logger(__name__)

try:
    from qwen_vl_utils import process_vision_info
except ImportError:
    process_vision_info = None
    logger.warning("qwen-vl-utils 未安装，本地推理将不可用。请运行: pip install qwen-vl-utils")

# ===== Prompt 模板 =====

_SYSTEM_PROMPT = """你是桌面GUI智能体。根据截图和任务，输出下一步操作。

有效动作：
- click(x=<int>, y=<int>)           # 点击指定坐标
- type(text="<str>")                 # 输入文本
- scroll(direction="up|down", steps=<int>)  # 滚动
- hotkey(key1, key2, ...)            # 组合键
- finish(result="<str>")             # 任务完成

请根据当前截图，输出下一步需要执行的一个动作。只输出动作本身，不要解释。"""

_USER_PROMPT_TEMPLATE = "用户任务：{task}\n请输出下一步动作："


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
    ):
        """初始化模型客户端。

        Args:
            mode: 推理模式，"local" 或 "api"。
            model_name: 模型名称，None 则使用 config.MODEL_NAME。
            api_url: API 端点，None 则使用 config.MODEL_API_URL。
            api_key: API 密钥，None 则使用 config.MODEL_API_KEY。

        Raises:
            ModelError: 模式不合法或模型加载失败。
        """
        if mode not in ("local", "api"):
            raise ModelError(f"不支持的推理模式: {mode}，可选 'local' 或 'api'")

        self.mode = mode
        self.model_name = model_name or MODEL_NAME
        self.api_url = api_url or MODEL_API_URL
        self.api_key = api_key or MODEL_API_KEY
        self._model = None
        self._processor = None

        logger.info(f"ModelClient 初始化，模式: {self.mode}，模型: {self.model_name}")

    def query(
        self,
        image: Image.Image,
        task: str,
        context: Optional[list] = None,
    ) -> str:
        """向模型发送截图和任务，返回模型响应。

        Args:
            image: 当前屏幕截图 (PIL.Image)。
            task: 用户自然语言任务描述。
            context: 前几步的历史动作记录（可选）。

        Returns:
            模型的原始文本输出。

        Raises:
            ModelError: 推理失败或超时。
        """
        if image is None:
            raise ModelError("输入截图不能为 None")

        user_prompt = _USER_PROMPT_TEMPLATE.format(task=task)

        if context:
            history_lines = "\n".join(f"  步骤{i+1}: {act}" for i, act in enumerate(context))
            user_prompt += f"\n已完成步骤：\n{history_lines}"

        if self.mode == "local":
            return self._query_local(image, user_prompt)
        else:
            return self._query_api(image, user_prompt)

    # ===== 本地推理 =====

    def _query_local(self, image: Image.Image, user_prompt: str) -> str:
        """本地 Transformers 推理。"""
        if self._model is None:
            self._model, self._processor = _load_local_model(self.model_name)

        try:
            # 构建 Qwen2-VL 的标准输入格式
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ]

            # 使用 processor 处理消息
            text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            if process_vision_info is None:
                raise ModelError(
                    "qwen-vl-utils 未安装，无法进行本地推理。"
                    "请运行: pip install qwen-vl-utils"
                )
            image_inputs, video_inputs = process_vision_info(messages)

            inputs = self._processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            ).to(self._model.device)

            start_time = time.time()
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=MODEL_MAX_TOKENS,
            )
            elapsed = time.time() - start_time

            # 只取新生成的部分（去掉输入 token）
            generated_ids_trimmed = [
                out_ids[len(in_ids):]
                for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            output_text = self._processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0]

            logger.info(f"本地推理完成，耗时 {elapsed:.2f}s，输出: {output_text[:80]}")
            return output_text.strip()

        except Exception as e:
            logger.error(f"本地推理失败: {e}")
            raise ModelError(f"本地推理失败: {e}")

    # ===== API 推理 =====

    def _query_api(self, image: Image.Image, user_prompt: str) -> str:
        """通过 HTTP API 调用远程模型。"""
        if not self.api_url:
            raise ModelError("API 模式需要配置 MODEL_API_URL")

        # PIL Image → base64
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
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
            "max_tokens": MODEL_MAX_TOKENS,
        }

        # 重试逻辑：最多 2 次
        last_error = None
        for attempt in range(2):
            try:
                start_time = time.time()
                resp = requests.post(
                    self.api_url.rstrip("/") + "/chat/completions",
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
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            device_map="auto",
        )
        processor = AutoProcessor.from_pretrained(model_name)
        logger.info("本地模型加载成功")
        return model, processor
    except Exception as e:
        logger.error(f"本地模型加载失败: {e}")
        raise ModelError(f"本地模型加载失败: {e}")
