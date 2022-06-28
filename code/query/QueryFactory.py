from core.Arguments import Arguments
from db.Db import Db
from query.Detail import Detail
from query.Listing import Listing
from query.Summarization import Summarization


def build_query(db: Db, arguments: Arguments):
    query_name = arguments.query
    if not query_name:
        return None
    query_name = query_name.lower()
    query = None
    if query_name.startswith("l"):
        query = Listing
    elif query_name.startswith("s"):
        query = Summarization
    elif query_name.startswith("d"):
        query = Detail

    return query(db, arguments)
