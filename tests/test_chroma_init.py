import sys
import types
from unittest.mock import MagicMock, patch

from app.rag import chroma_rag


def test_init_faq_chroma_rebuilds_legacy_persistence():
    fake_client = MagicMock()
    fake_client_instance = MagicMock()
    fake_module = types.SimpleNamespace(
        PersistentClient=MagicMock(side_effect=[RuntimeError("range start index 10 out of range for slice of length 9"), fake_client_instance])
    )
    fake_collection = MagicMock()
    fake_collection.count.return_value = 1

    with patch.dict(sys.modules, {"chromadb": fake_module}):
        with patch.object(chroma_rag, "get_settings", return_value=types.SimpleNamespace(chroma_path="tmp_chroma")):
            with patch.object(chroma_rag, "load_and_chunk_faq_md", return_value=[{"id": "faq_1", "text": "hello world", "metadata": {"header": "FAQ"}}]):
                with patch.object(chroma_rag, "_get_collection", return_value=fake_collection):
                    with patch.object(chroma_rag, "_reset_chroma_storage") as mock_reset:
                        result = chroma_rag.init_faq_chroma()

    assert result is True
    mock_reset.assert_called_once_with("tmp_chroma")
