__all__ = ["create_app"]


def create_app(*args, **kwargs):
    from .app import create_app as app_factory

    return app_factory(*args, **kwargs)
