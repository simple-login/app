import tempfile
from io import BytesIO

import arrow

from app import s3, config
from app.models import File, BatchImport
from tasks.cleanup_old_imports import cleanup_old_imports
from tests.utils import random_token, create_new_user


def test_cleanup_old_imports():
    BatchImport.filter().delete()
    with tempfile.TemporaryDirectory() as tmpdir:
        config.UPLOAD_DIR = tmpdir
        user = create_new_user()
        path = random_token()
        s3.upload_from_bytesio(path, BytesIO("data".encode("utf-8")))
        file = File.create(path=path, commit=True)  # noqa: F821
        now = arrow.now()
        delete_batch_import_id = BatchImport.create(
            user_id=user.id,
            file_id=file.id,
            created_at=now.shift(minutes=-1),
            flush=True,
        ).id
        keep_batch_import_id = BatchImport.create(
            user_id=user.id,
            file_id=file.id,
            created_at=now.shift(minutes=+1),
            commit=True,
        ).id
        cleanup_old_imports(now)
        assert BatchImport.get(id=delete_batch_import_id) is None
        assert BatchImport.get(id=keep_batch_import_id) is not None
