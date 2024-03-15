import arrow

from app import s3
from app.log import LOG
from app.models import BatchImport


def cleanup_imports(oldest_allowed: arrow.Arrow):
    for batch_import in (
        BatchImport.filter(BatchImport.created_at < oldest_allowed).yield_per(500).all()
    ):
        LOG.i(
            f"Deleting batch import {batch_import} with file {batch_import.file.path}"
        )
        file = batch_import.file
        if file is not None:
            s3.delete(file.path)
        BatchImport.delete(batch_import.id)
