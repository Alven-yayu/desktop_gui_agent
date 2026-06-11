"""Verify environment setup for Desktop GUI Agent"""
import os
import sys

# Workaround for Windows SSL certificate store corruption
import certifi
os.environ['SSL_CERT_FILE'] = certifi.where()

import ssl
_orig_create_default_context = ssl.create_default_context
def _patched_create_default_context(*args, **kwargs):
    """Patched version that skips Windows cert store"""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(certifi.where())
    return context
ssl.create_default_context = _patched_create_default_context

import torch
import cv2
import mss
import paddleocr
from agentscope.model import OpenAIChatModel

print("PyTorch版本:", torch.__version__)
print("OpenCV版本:", cv2.__version__)
print("PaddleOCR版本:", paddleocr.__version__)
print("CUDA可用:", torch.cuda.is_available())
print("mss版本:", mss.__version__)
print("AgentScope导入成功")
print("所有依赖验证通过！")