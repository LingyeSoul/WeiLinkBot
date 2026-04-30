"""Local ONNX embedding support backed by ModelScope model files."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


class _TokenizerEncoding(Protocol):
    ids: list[int]
    attention_mask: list[int]
    type_ids: list[int]


class _TokenizerLike(Protocol):
    def encode_batch(self, input: list[str]) -> list[_TokenizerEncoding]: ...
    def enable_truncation(self, *, max_length: int) -> None: ...
    def enable_padding(self, *, pad_id: int, pad_token: str, length: int | None) -> None: ...


class _SessionInput(Protocol):
    name: str


class _SessionLike(Protocol):
    def get_inputs(self) -> Sequence[_SessionInput]: ...
    def run(self, output_names: object, input_feed: dict[str, np.ndarray]) -> Sequence[object]: ...


LOCAL_EMBEDDING_PROVIDER = "modelscope-local"
DEFAULT_MODELSCOPE_MODEL_ID = "Xenova/bge-small-zh-v1.5"
DEFAULT_DISPLAY_MODEL = "Xenova/bge-small-zh-v1.5"
DEFAULT_LOCAL_MODEL_PATH = "./data/models/bge-small-zh-v1.5"


@dataclass(frozen=True)
class OnnxModelOption:
    """A selectable ONNX model variant."""

    value: str
    label: str
    description: str
    recommended: bool = False
    advanced: bool = False


ONNX_MODEL_OPTIONS: tuple[OnnxModelOption, ...] = (
    OnnxModelOption(
        value="onnx/model_fp16.onnx",
        label="FP16 半精度（默认推荐）",
        description="体积约为 FP32 的一半，精度损失很小，适合大多数本地 CPU 场景。",
        recommended=True,
    ),
    OnnxModelOption(
        value="onnx/model_quantized.onnx",
        label="Quantized 通用量化",
        description="Transformers.js 常用默认量化版本，体积小、加载快。",
    ),
    OnnxModelOption(
        value="onnx/model_int8.onnx",
        label="INT8 量化",
        description="8-bit 整数量化，兼顾体积、速度和语义检索质量。",
    ),
    OnnxModelOption(
        value="onnx/model_uint8.onnx",
        label="UINT8 量化",
        description="无符号 8-bit 量化，可在 INT8 表现异常时尝试。",
    ),
    OnnxModelOption(
        value="onnx/model_q4f16.onnx",
        label="Q4F16 混合 4-bit",
        description="更小的 4-bit 混合量化版本，适合优先节省空间。",
    ),
    OnnxModelOption(
        value="onnx/model_q4.onnx",
        label="Q4 量化",
        description="4-bit 量化，体积未必最小但可作为低资源备选。",
    ),
    OnnxModelOption(
        value="onnx/model_bnb4.onnx",
        label="BNB4 量化",
        description="BitsAndBytes 4-bit 量化格式，兼容性取决于 ONNX Runtime 版本。",
    ),
    OnnxModelOption(
        value="onnx/model.onnx",
        label="FP32 全精度",
        description="全精度模型，体积最大；仅在明确需要最高精度时手动选择。",
    ),
)

DEFAULT_ONNX_MODEL_FILE = "onnx/model_fp16.onnx"
_DEFAULT_DOWNLOAD_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "config.json",
)


class LocalEmbeddingError(RuntimeError):
    """Raised when the local embedding model cannot be loaded or executed."""


def public_onnx_model_options(include_advanced: bool = False) -> list[dict[str, object]]:
    """Return model options for API/UI consumption.

    FP32 full precision is intentionally hidden unless include_advanced=True.
    """
    options = ONNX_MODEL_OPTIONS if include_advanced else tuple(
        item for item in ONNX_MODEL_OPTIONS if not item.advanced
    )
    return [
        {
            "value": item.value,
            "label": item.label,
            "description": item.description,
            "recommended": item.recommended,
            "advanced": item.advanced,
        }
        for item in options
    ]


def quantization_from_onnx_file(onnx_model_file: str) -> str:
    """Infer a stable quantization label from an ONNX model path."""
    file_name = Path(onnx_model_file).name
    mapping = {
        "model_fp16.onnx": "fp16",
        "model_quantized.onnx": "quantized",
        "model_int8.onnx": "int8",
        "model_uint8.onnx": "uint8",
        "model_q4.onnx": "q4",
        "model_q4f16.onnx": "q4f16",
        "model_bnb4.onnx": "bnb4",
        "model.onnx": "fp32",
    }
    return mapping.get(file_name, Path(file_name).stem)


def download_modelscope_embedding_files(
    *,
    model_id: str = DEFAULT_MODELSCOPE_MODEL_ID,
    local_dir: str = DEFAULT_LOCAL_MODEL_PATH,
    onnx_model_file: str = DEFAULT_ONNX_MODEL_FILE,
) -> str:
    """Download one ONNX variant plus tokenizer/config files from ModelScope."""
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError as exc:
        raise LocalEmbeddingError(
            "modelscope is not installed; install project dependencies first."
        ) from exc

    allow_patterns = [onnx_model_file, *_DEFAULT_DOWNLOAD_FILES]
    try:
        return snapshot_download(
            model_id=model_id,
            allow_patterns=allow_patterns,
            local_dir=local_dir,
        )
    except TypeError:
        # Older ModelScope builds used HF-compatible parameter names.
        return snapshot_download(
            model_id=model_id,
            allow_file_pattern=allow_patterns,
            local_dir=local_dir,
        )


class LocalOnnxEmbeddingService:
    """Runs BGE sentence embeddings locally with ONNX Runtime."""

    def __init__(
        self,
        *,
        model_dir: str,
        onnx_model_file: str = DEFAULT_ONNX_MODEL_FILE,
        modelscope_model_id: str = DEFAULT_MODELSCOPE_MODEL_ID,
        auto_download: bool = True,
        max_length: int = 512,
    ) -> None:
        self.model_dir: Path = Path(model_dir).expanduser().resolve()
        self.onnx_model_file: str = onnx_model_file or DEFAULT_ONNX_MODEL_FILE
        self.modelscope_model_id: str = modelscope_model_id or DEFAULT_MODELSCOPE_MODEL_ID
        self.auto_download: bool = auto_download
        self.max_length: int = max_length
        self._session: _SessionLike | None = None
        self._tokenizer: _TokenizerLike | None = None

    @property
    def model_path(self) -> Path:
        path = (self.model_dir / self.onnx_model_file).resolve()
        try:
            path.relative_to(self.model_dir)
        except ValueError as exc:
            raise LocalEmbeddingError(
                f"ONNX model path escapes model directory: {self.onnx_model_file}"
            ) from exc
        return path

    def ensure_available(self) -> None:
        """Ensure files are present and the ONNX session/tokenizer can load."""
        if not self.model_path.exists():
            if not self.auto_download:
                raise LocalEmbeddingError(f"ONNX model file not found: {self.model_path}")
            _ = download_modelscope_embedding_files(
                model_id=self.modelscope_model_id,
                local_dir=str(self.model_dir),
                onnx_model_file=self.onnx_model_file,
            )
        self._load()

    def embed(self, texts: str | Iterable[str]) -> list[list[float]]:
        """Embed one or more texts and return normalized vectors."""
        if isinstance(texts, str):
            batch = [texts]
        else:
            batch = list(texts)
        if not batch:
            return []
        if self._session is None or self._tokenizer is None:
            self.ensure_available()
        if self._session is None or self._tokenizer is None:
            raise LocalEmbeddingError("Local ONNX embedding model is not loaded")

        tokenizer = self._tokenizer
        session = self._session
        encoded = tokenizer.encode_batch(batch)
        input_ids = np.array(
            [item.ids[: self.max_length] for item in encoded],
            dtype=np.int64,
        )
        attention_mask = np.array(
            [item.attention_mask[: self.max_length] for item in encoded],
            dtype=np.int64,
        )
        token_type_ids = np.array(
            [item.type_ids[: self.max_length] for item in encoded],
            dtype=np.int64,
        )

        inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        session_input_names = {item.name for item in session.get_inputs()}
        if "token_type_ids" in session_input_names:
            inputs["token_type_ids"] = token_type_ids

        outputs = session.run(None, inputs)
        token_embeddings = np.asarray(outputs[0])
        pooled = self._mean_pool(token_embeddings, attention_mask)
        normalized = self._normalize(pooled)
        return normalized.astype(np.float32).tolist()

    def test(self) -> tuple[int, int]:
        """Run a smoke test and return (count, dimension)."""
        vectors = self.embed(["test"])
        if not vectors or not vectors[0]:
            raise LocalEmbeddingError("Local ONNX embedding produced an empty vector")
        return len(vectors), len(vectors[0])

    def _load(self) -> None:
        if self._session is None:
            try:
                import onnxruntime as ort
            except ImportError as exc:
                raise LocalEmbeddingError(
                    "onnxruntime is not installed; install project dependencies first."
                ) from exc
            if not self.model_path.exists():
                raise LocalEmbeddingError(f"ONNX model file not found: {self.model_path}")
            self._session = ort.InferenceSession(
                str(self.model_path),
                providers=["CPUExecutionProvider"],
            )

        if self._tokenizer is None:
            try:
                from tokenizers import Tokenizer
            except ImportError as exc:
                raise LocalEmbeddingError(
                    "tokenizers is not installed; install project dependencies first."
                ) from exc
            tokenizer_path = self.model_dir / "tokenizer.json"
            if not tokenizer_path.exists():
                raise LocalEmbeddingError(f"tokenizer.json not found: {tokenizer_path}")
            tokenizer = Tokenizer.from_file(str(tokenizer_path))
            tokenizer.enable_truncation(max_length=self.max_length)
            tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=None)
            self._tokenizer = tokenizer

    @staticmethod
    def _mean_pool(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        mask = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
        masked_embeddings = token_embeddings * mask
        summed = np.sum(masked_embeddings, axis=1)
        counts = np.clip(np.sum(mask, axis=1), a_min=1e-9, a_max=None)
        return summed / counts

    @staticmethod
    def _normalize(embeddings: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / np.clip(norms, a_min=1e-9, a_max=None)
