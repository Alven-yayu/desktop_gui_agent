# 桌面感知模块 — 需求分析

> 参考：PDF 4.1 节（桌面感知模块）

---

## 模块职责

"看懂屏幕"——截取屏幕 → 识别文字 → 定位 UI 元素，为 Agent 决策提供结构化信息。

---

## 子模块

```
截图 (screenshot.py) → OCR识别 (ocr_recognizer.py) → UI定位 (ui_locator.py)
```

---

## 4.1.1 屏幕截图 (screenshot.py)

**功能：** 跨平台屏幕实时截图

| 输入 | 类型 | 说明 |
|------|------|------|
| `screen_id` | `int`（可选） | 屏幕编号，默认 0 |
| `region` | `tuple`（可选） | `(left, top, width, height)`，默认全屏 |

| 输出 | 类型 |
|------|------|
| 截图 | `PIL.Image` |

**业务规则：**
- 支持 Windows / macOS / Linux
- 自动适配分辨率与 DPI 缩放
- 单帧 ≤ 50ms
- 支持多屏幕

**异常处理：**

| 场景 | 处理 |
|------|------|
| 屏幕不存在 | 抛 `ScreenshotError`，记录日志 |
| 区域越界 | 裁剪到有效范围，记录警告 |

---

## 4.1.2 OCR文字识别 (ocr_recognizer.py)

**功能：** 识别截图中的文字内容与位置

| 输入 | 类型 |
|------|------|
| 截图 | `PIL.Image` |

| 输出字段 | 类型 | 说明 |
|----------|------|------|
| `text` | `str` | 识别到的文字 |
| `bbox` | `tuple` | 边界框 `(x1, y1, x2, y2)` |
| `confidence` | `float` | 置信度 0~1 |

**业务规则：**
- 使用 PaddleOCR PP-OCRv4
- 支持中英文混合
- 准确率 ≥ 90%（清晰屏幕文字）
- 单帧 ≤ 200ms

**异常处理：**

| 场景 | 处理 |
|------|------|
| 模型加载失败 | 抛 `OCRError`，记录日志 |
| 识别结果为空 | 返回空列表 `[]` |

---

## 4.1.3 UI元素定位与可视化 (ui_locator.py)

**功能：** 在截图上标注 UI 元素，可视化显示识别结果

| 输入 | 类型 | 说明 |
|------|------|------|
| `image` | `PIL.Image` | 原始截图 |
| `elements` | `list` | OCR 输出的元素列表（含 text、bbox、confidence） |

| 输出 | 类型 |
|------|------|
| 标注图 | `PIL.Image` |

**业务规则：**
- 矩形框标注每个元素边界
- 标注序号与文字内容
- 不同类型用不同颜色

**异常处理：**

| 场景 | 处理 |
|------|------|
| 输入为空 | 返回原图 |

---

## 模块数据流

```
screen_id, region
      │
      ▼
screenshot.py ──→ PIL.Image
                      │
                      ▼
              ocr_recognizer.py ──→ [{text, bbox, confidence}, ...]
                      │
                      ▼
              ui_locator.py ──→ 标注后的 PIL.Image（调试/可视化用）
```
