import argparse

from .app import main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Bảng điều khiển cụm")
    ap.add_argument("--config", default="cluster.toml")
    main(ap.parse_args().config)
