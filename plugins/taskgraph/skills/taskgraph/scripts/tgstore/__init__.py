from tgstore.sqlite import SqliteStore


def open_store(args):
    return SqliteStore(args.db)
