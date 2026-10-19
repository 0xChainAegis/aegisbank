"""最小可运行入口。"""


def greet(name: str) -> str:
    return f"hello, {name}"


def main() -> int:
    print(greet("world"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())