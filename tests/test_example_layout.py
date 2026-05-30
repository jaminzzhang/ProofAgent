from pathlib import Path


def test_only_insurance_customer_service_is_public_example() -> None:
    public_examples = sorted(
        path.name
        for path in Path("examples").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )

    assert public_examples == ["insurance_customer_service"]
