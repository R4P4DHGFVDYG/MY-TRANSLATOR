from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()

    from hq_ocr_bridge.__main__ import main

    main()
