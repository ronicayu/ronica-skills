from tgstore.sqlite import SqliteStore


def open_store(args, load):
    # A project the .taskgraph.toml names with a remote backend gets a cached remote store; everything else is the local database.
    from tgstore.config import find_config, load_config, project_entry

    path = find_config()
    entry = project_entry(load_config(path), args.project) if path is not None else None
    if entry is not None and entry.backend == "github":
        from tgstore.cached import CachedRemoteStore
        from tgstore.github.remote import GitHubRemote

        return CachedRemoteStore(GitHubRemote(entry), entry, load, args.project)
    return SqliteStore(args.db, load)
