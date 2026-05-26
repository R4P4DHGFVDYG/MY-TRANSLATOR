from .app import create_app
from .config import BridgeConfig


def main() -> None:
    config = BridgeConfig.from_env()
    app = create_app(config)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    main()
