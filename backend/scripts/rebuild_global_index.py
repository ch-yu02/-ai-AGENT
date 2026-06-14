"""Rebuild the cross-classroom global search index.

This script is intentionally small and uses the same ``GlobalSearchService`` as
the API route. That keeps CLI behavior aligned with search behavior: bad saved
sessions are skipped with warnings, documents are generated through the same RAG
conversion path, and optional LlamaIndex persistence remains a cache layer.
"""

import argparse
import json

from backend.app.agent import GlobalSearchService
from backend.app.storage import local_storage


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild EDU-Mate global index")
    parser.add_argument(
        "--llamaindex",
        action="store_true",
        help="also rebuild data/indexes/global/llama_index",
    )
    args = parser.parse_args()

    service = GlobalSearchService(local_storage)
    result = service.rebuild_global_index(build_llamaindex=args.llamaindex)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
