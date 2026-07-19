from .process_lifetime import start_owner_watchdog_from_env


def main() -> None:
    start_owner_watchdog_from_env()

    from .windows_runtime import preload_frozen_torch_runtime

    runtime_warning = preload_frozen_torch_runtime()
    if runtime_warning:
        print(runtime_warning, flush=True)

    from .app import create_app
    from .config import BridgeConfig

    config = BridgeConfig.from_env()
    app = create_app(config)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    main()
