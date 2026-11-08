from tgstore.sqlite import SqliteStore


def open_store(args, load):
    return SqliteStore(args.db, load)
